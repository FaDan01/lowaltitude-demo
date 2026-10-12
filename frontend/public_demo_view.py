"""以确定性审计在内存演示合成案例；不接入原案例、收件箱或运行目录。"""
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from backend.audit.engine import audit
from backend.models import AuditPackage, Candidate
from backend.paths import ROOT
from backend.remediation import build_remediation
from backend.report_export import render_report_html as _render_report_html
from frontend.demo_scenarios import render_demo_scenarios
from frontend.labels_zh import display_value, label, translate_report
from frontend.verification_view import VARIANT_LABELS, render_verification


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


def _read_json(path, maximum=2_000_000):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('演示资料缺失、过大或路径无效')
    return json.loads(path.read_text(encoding='utf-8'))


def load_public_payload(demo_root, rules_root):
    """仅载入已校验的14条合成示例，摘要和当前规则必须对应。"""
    demo_root, rules_root = Path(demo_root), Path(rules_root)
    effective_rules = Path(os.getenv('LOWALTITUDE_RULES_DIR', str(ROOT / 'rules')))
    if effective_rules.resolve() != rules_root.resolve():
        raise ValueError('演示校验规则与实际执行目录不一致')
    folder = demo_root / 'evaluation/mechanism_v1'
    manifest = _read_json(folder / 'manifest.json')
    if (manifest.get('schema') != 'public_demo_subset/v1' or manifest.get('model_calls') != 0
            or manifest.get('expert_validated') is not False or manifest.get('public_cases') != 14
            or manifest.get('scope') != 'synthetic_mechanism_only'):
        raise ValueError('演示资料来源说明不符合约定')
    entries = manifest.get('files', [])
    if {entry['path'] for entry in entries} != {'replay.json', 'summary.json'} or len(entries) != 2:
        raise ValueError('演示文件清单不符合约定')
    for entry in entries:
        path = folder / entry['path']
        _read_json(path)
        payload = path.read_bytes()
        if len(payload) != entry['size'] or hashlib.sha256(payload).hexdigest() != entry['sha256']:
            raise ValueError('演示文件摘要改变')
    replay, summary = _read_json(folder / 'replay.json'), _read_json(folder / 'summary.json')
    if len(replay) != 14 or hashlib.sha256(_canonical(replay)).hexdigest() != manifest['replay_sha256']:
        raise ValueError('演示示例数量或摘要不符')
    identities = {f'MECH-00-{variant}' for variant in VARIANT_LABELS}
    if {row['case_id'] for row in replay} != identities or len(manifest['case_ids']) != 14:
        raise ValueError('演示示例编号不符')
    if set(manifest['case_ids']) != identities:
        raise ValueError('演示编号与清单不符')
    for row in replay:
        package = AuditPackage.model_validate(row['input'])
        Candidate.model_validate(row['candidate'])
        if (package.case_id != row['case_id'] or package.is_constructed is not True
                or not isinstance(package.raw_evidence, dict)
                or package.raw_evidence.get('research_policy', {}).get('scope') != 'synthetic_mechanism_only'
                or any(not e.constructed or e.source_type != 'constructed' for e in package.evidence)):
            raise ValueError('演示资料包含非合成证据')
    if (summary.get('kind') != 'synthetic_mechanism_challenge_v1' or summary.get('model_calls') != 0
            or summary.get('expert_validated') is not False or summary.get('cases') != manifest['source_cases']
            or summary.get('replay_sha256') != manifest['source_replay_sha256']):
        raise ValueError('研究汇总与合成示例来源不符')
    for name in ['fields', 'decision_gate', 'audit_depth']:
        path = rules_root / f'{name}.json'
        rules = _read_json(path)
        if rules != summary['rules'][name] or rules['version'] != manifest['rules_versions'][name]:
            raise ValueError('当前规则与演示版本不一致')
        if hashlib.sha256(_canonical(rules)).hexdigest() != manifest['rules_sha256'][name]:
            raise ValueError('当前规则摘要不一致')
    return replay, summary


def audit_demo_snapshot(snapshot):
    """保持输入与候选快照不变；结果仅保存在调用者内存。"""
    snapshot = copy.deepcopy(snapshot)
    package = AuditPackage.model_validate(snapshot['input'])
    candidate = Candidate.model_validate(snapshot['candidate'])
    result = audit(package, candidate, snapshot['original'])
    record = {'run_id':'分享演示-' + uuid4().hex[:10], 'case_id':package.case_id,
              'created_at':datetime.now(timezone.utc).isoformat(), 'mode':'fixture',
              'status':'success', 'ground_truth_source':'constructed', 'expert_validated':False,
              'model_calls':0, 'input_sha256':hashlib.sha256(_canonical(snapshot['input'])).hexdigest(),
              'rule_version_used':result.rule_version_used, 'gate_final_decision':result.final_decision}
    return {'record':record, 'input':package.model_dump(), 'candidate':candidate.model_dump(),
            'audit':result.model_dump()}


def render_report_html(record, package, result, candidate=None):
    """使用原后端报告，保留查找快照所需的原始编号。"""
    html = _render_report_html(record, package, result, candidate)
    for field, heading in [('case_id','案例编号'),('run_id','运行编号')]:
        if field in record:
            value = str(record[field])
            old = f'<th>{heading}</th><td>{escape(translate_report(value))}</td>'
            new = f'<th>{heading}</th><td>{escape(value)}</td>'
            html = html.replace(old, new, 1)
    return html


def _show_result(saved):
    result = saved['audit']
    candidate = saved['candidate']
    left,right = st.columns(2)
    left.metric('候选原始判定', label(candidate['status']))
    right.metric('证据审计后', label(result['final_decision']))
    st.write(translate_report(result['rationale']))
    if result['final_decision'] != 'BLOCK':
        st.subheader('逐条主张核验')
        rows = [{'主张':translate_report(c['text']), '核验状态':label(c['evidence_status']),
                 '依据':translate_report(c['reason']),
                 '证据编号':'、'.join(c['supporting_evidence'] + c['contradicting_evidence'])}
                for c in result['claims']]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    else:
        st.error('候选涉及越权内容，普通报告已隐藏候选原文。')
    st.subheader('问题与补证')
    for issue in result['issues']:
        st.write(f'{label(issue["issue_type"])}：{translate_report(issue["reason"])}')
    package = AuditPackage.model_validate(saved['input'])
    from backend.models import AuditResult
    advice = build_remediation(package, AuditResult.model_validate(result))
    if advice:
        st.dataframe(pd.DataFrame(display_value(advice)), hide_index=True, width='stretch')
    elif not result['issues']:
        st.caption('当前合成示例没有新增补证请求。')


def render_public_demo(demo_root, rules_root):
    try:
        replay,summary = load_public_payload(demo_root, rules_root)
    except (ValueError, KeyError, TypeError, OSError):
        st.error('演示资料或规则未通过校验，请联系部署者。')
        st.stop()
    st.markdown('### 🛰 低空安全可信态势研判与风险预警原型')
    st.caption('候选研判 → 证据核验 → 四态审计 → 决策门控 · 仅合成示例，模型调用为零')
    overview,work,comparison,report = st.tabs(['📊 项目总览','🧭 研判工作台','🧪 对照与机制验证','📄 本次报告'])
    with overview:
        columns = st.columns(4)
        columns[0].metric('研究合成变体', summary['cases'])
        columns[1].metric('可交互演示示例', len(replay))
        columns[2].metric('演示模型调用', 0)
        columns[3].metric('专家确认', '尚未完成')
        st.subheader('这个系统解决什么问题')
        st.write('模型生成的报告可能把不同航空器的记录混在一起、忽略证据冲突，或给出没有规则依据的低风险结论。'
                 '系统逐条核对判断的依据，把矛盾和缺失资料交给使用者复核。')
        st.write('本页演示与本机网站使用同一个审计引擎。你可以选择合成案例，在工作台运行证据审计，'
                 '也可以查看三个对照场景，了解一项证据或判断变化怎样影响结论。')
        st.info('这里的14条示例取自已完成的420条合成机制验证。420条汇总是既有研究记录，'
                '现场点击只重算当前示例；这些结果尚不能证明真实业务准确率或人工提效。')
        st.caption('演示不提供资料上传、人工签字和真实模型生成。你的操作结果仅留在本次会话，刷新或退出后可能清除。')
    with work:
        options = {row['case_id']:row for row in replay}
        selected = st.selectbox('选择演示案例', list(options),
            format_func=lambda identity:VARIANT_LABELS[identity.removeprefix('MECH-00-')])
        snapshot = options[selected]
        st.write('候选原始输出：' + translate_report(snapshot['original']))
        with st.expander('查看本次示例的原始证据'):
            st.json(display_value(snapshot['input']['raw_evidence']))
        if st.button('运行证据审计', type='primary'):
            st.session_state['public_demo_result'] = audit_demo_snapshot(snapshot)
        saved = st.session_state.get('public_demo_result')
        if saved:
            if saved['record']['case_id'] != selected:
                st.info('下面是上次审计的结果，当前所选案例尚未运行。')
            st.caption('结果对应案例：' + saved['record']['case_id'])
            _show_result(saved)
        else:
            st.info('选择案例并运行，可查看每项判断与证据的对应关系。')
    with comparison:
        render_demo_scenarios(Path(demo_root))
        render_verification(Path(demo_root))
        st.caption('交互示例为第一个参数化场景组的14个变体；上方汇总来自原30组、420条完整机制集。')
    with report:
        saved = st.session_state.get('public_demo_result')
        if not saved:
            st.info('在研判工作台运行一次审计后，可在这里下载对应报告。')
        else:
            from backend.models import AuditResult
            result = AuditResult.model_validate(saved['audit'])
            package = AuditPackage.model_validate(saved['input'])
            candidate = None if result.final_decision == 'BLOCK' else Candidate.model_validate(saved['candidate'])
            st.caption('报告对应案例：' + saved['record']['case_id'])
            st.write(translate_report(result.rationale))
            printable = render_report_html(saved['record'], package, result, candidate)
            st.download_button('下载可打印中文报告', printable,
                f'{package.case_id}-演示报告.html', mime='text/html')
            st.caption('报告由当前会话的输入与审计结果生成；没有写入本机运行目录。')
