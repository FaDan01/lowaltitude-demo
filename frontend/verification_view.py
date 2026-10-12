"""展示独立合成挑战集与固定候选的现场对照，不混入模型实验记录。"""
import json

import pandas as pd
import streamlit as st

from frontend.labels_zh import display_value, label, translate_report


VARIANT_LABELS = {
    'clean_low':'完整证据、正确低风险', 'clean_high':'完整证据、正确高风险',
    'wording':'等义表达', 'reordered':'调整主张顺序', 'irrelevant':'添加无关记录',
    'zero_altitude':'有效的零高度', 'fact_error':'高度事实错误', 'omission':'遗漏登记事实',
    'missing':'缺少申请记录', 'conflict':'高度来源冲突', 'risk_underestimate':'事实正确、风险低估',
    'wrong_aircraft':'申请记录属于另一架航空器', 'mixed_datum':'相同数值、不同高度基准',
    'compound':'复合句只映射登记字段',
}


@st.cache_data(show_spinner=False)
def _read_saved(path, modified_ns):
    return json.loads(path.read_text(encoding='utf-8'))


def render_verification(root):
    folder = root / 'evaluation/mechanism_v1'
    st.subheader('证据审计为什么需要分开核验')
    st.warning('本页是人工构造的机制验证。100米仅为研究规则阈值，不是法规限高；自动采用只指辅助报告展示。')
    if not (folder/'summary.json').exists():
        st.info('独立挑战集尚未运行。')
        return
    summary = _read_saved(folder/'summary.json', (folder/'summary.json').stat().st_mtime_ns)
    st.caption(f'{summary["families"]}个参数化场景组、{summary["cases"]}条固定候选变体；'
               f'正常对照占{summary["normal_fraction"]:.1%}。同一场景的全部变体留在同一开发或测试分组。')
    names = {'direct':'直接采用候选', 'all_manual':'全部人工',
             'fields_only':'仅核验事实字段（消融）', 'full':'完整证据审计'}
    fmt = lambda value:'不可计算' if value is None else f'{value:.1%}'
    rows = [{'对照条件':names[condition], '错误候选自动采用比例':fmt(metrics['error_release_rate']),
             '采用后错误率':fmt(metrics['selective_error_rate']), '自动覆盖率':fmt(metrics['automatic_coverage']),
             '正确候选保留率':fmt(metrics['clean_retention'])}
            for condition, metrics in summary['metrics']['test'].items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    st.caption('三个分母分别为错误候选、自动采用候选、全部候选。全部人工的采用后错误率不可计算。结果只验证这些设计好的机制。')
    checks = summary['property_checks']
    st.caption(f'等义表达、顺序、无关证据、删证、冲突与补证恢复性质检查：{checks["passed"]}/{checks["total"]}。'
               '本轮未调用模型，不评价模型生成和自然语言抽取精度。')
    if not (folder/'replay.json').exists():
        st.info('本机尚无逐条回放文件。执行独立合成验证命令后可查看对照证据。')
        return
    replay = _read_saved(folder/'replay.json', (folder/'replay.json').stat().st_mtime_ns)
    options = list(VARIANT_LABELS)
    selected = st.selectbox('选择同一场景的对照形态', options, format_func=VARIANT_LABELS.get)
    snapshot = next(item for item in replay if item['case_id']==f'MECH-00-{selected}')
    audit = snapshot['audit']
    left, right = st.columns(2)
    left.metric('候选原始判定', label(snapshot['candidate']['status']))
    right.metric('证据审计后', label(audit['final_decision']))
    st.write(translate_report(snapshot['original']))
    st.write(translate_report(audit['rationale']))
    for issue in audit['issues']:
        st.write(f'{label(issue["issue_type"])}：{translate_report(issue["reason"])}')
    with st.expander('查看该变体的证据和规则'):
        st.json(display_value(snapshot['input']['raw_evidence']))
    st.caption('缺失记录补齐后的对应样本是“完整证据、正确低风险”；系统不会替用户推填未知值。'
               '已有44条案例、专家确认状态及原始文件保持独立。')
