"""三幕反事实演示：同一场景只改一项，看审计结论为什么改变。

只读 evaluation/mechanism_v1/replay.json，不调用模型、不写任何记录。
差异由本组件实时对比前后两份原始证据算出，避免文案与数据不一致。
"""
import json
from html import escape
from pathlib import Path

import streamlit as st

from frontend.labels_zh import label, translate_report

_DECISION_STYLE = {
    'PASS': ('#15803d', '#dcfce7'),
    'WARNING': ('#b45309', '#fef3c7'),
    'MANUAL_REVIEW': ('#c2410c', '#ffedd5'),
    'BLOCK': ('#b91c1c', '#fee2e2'),
    'EXCEEDS_AUTHORITY': ('#991b1b', '#fecaca'),
}

SCENES = [
    {
        'title': '第一幕　事实说对了，风险结论仍然可能错',
        'before': 'clean_high',
        'afters': ['risk_underestimate'],
        'change': '只把模型自己写出的风险结论改小（改成低风险、放行），原始证据一字未动。',
        'takeaway': '风险结论必须有独立规则依据。系统不采信模型自报的“低风险”来证明它自己正确。',
    },
    {
        'title': '第二幕　数值相同，不等于可以相比',
        'before': 'clean_low',
        'afters': ['wrong_aircraft', 'mixed_datum'],
        'change': '① 只把“申请记录”的航空器标识换成另一架；② 另加一条数值相同的雷达记录，但基准是海拔而不是离地高度。',
        'takeaway': '数字相等不代表能拼成同一结论。系统比对航空器标识、高度基准与单位，对不上就拦下——这是低空场景特有的坑。',
    },
    {
        'title': '第三幕　说不清的地方变成待办，而不是含糊过去',
        'before': 'missing',
        'afters': ['clean_low'],
        'change': '先删掉“申请记录”，再补回来。',
        'takeaway': '证据不足转为人工并列出补证要求；补齐后重新审计才恢复有限自动展示。补证不等于放行，也不覆盖原结果。',
    },
]

_SIDE_CSS = '''
.demo-wrap {border:1px solid #E2E8F0;border-radius:14px;padding:16px 18px;margin-bottom:18px;background:#FFFFFF;box-shadow:0 1px 4px rgba(24,43,58,.06);}
.demo-h {font-size:15px;font-weight:700;color:#0F172A;margin-bottom:6px;}
.demo-change {font-size:13px;color:#7C2D12;background:#FFF7ED;border:1px solid #FED7AA;border-radius:8px;padding:8px 12px;margin:10px 0 4px 0;}
.demo-take {font-size:13.5px;color:#083344;background:#ECFEFF;border-left:4px solid #06B6D4;border-radius:8px;padding:10px 14px;margin-top:12px;line-height:1.7;}
.demo-side {border:1px solid #E2E8F0;border-radius:10px;padding:12px 14px;background:#FAFAFA;}
.demo-side.after {border-color:#CBD5E1;background:#F8FAFC;}
.demo-tag {font-size:12px;font-weight:700;color:#64748B;letter-spacing:.03em;margin-bottom:8px;}
.demo-row {font-size:13px;color:#334155;margin:6px 0;line-height:1.6;}
.demo-diff {font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#475569;background:#F1F5F9;border-radius:6px;padding:4px 8px;margin:4px 0;display:block;word-break:break-all;}
.demo-none {font-size:13px;color:#15803d;background:#F0FDF4;border-radius:6px;padding:6px 10px;display:inline-block;}
'''


def _flat(node, prefix=''):
    out = {}
    if isinstance(node, dict):
        for key, value in node.items():
            out.update(_flat(value, prefix + '/' + str(key)))
    elif isinstance(node, list):
        out[prefix] = json.dumps(node, ensure_ascii=False)
    else:
        out[prefix] = node
    return out


def _diff(before, after):
    fb, fa = _flat(before), _flat(after)
    rows = []
    for key in sorted(set(fb) | set(fa)):
        old, new = fb.get(key, '<无>'), fa.get(key, '<无>')
        if old != new:
            rows.append((key, old, new))
    return rows


@st.cache_data(show_spinner=False)
def _load_replay(path_text, modified_ns):
    return {item['case_id']: item for item in json.loads(Path(path_text).read_text(encoding='utf-8'))}


def _pill(status):
    fg, bg = _DECISION_STYLE.get(status, ('#334155', '#e2e8f0'))
    return f'<span class="pill" style="color:{fg};background:{bg};">{escape(label(status))}</span>'


def _side(snapshot, tag, css_extra=''):
    candidate = snapshot['candidate']
    audit = snapshot['audit']
    issues = audit.get('issues', [])
    issue_html = ''.join(
        f'<div class="demo-row">· {escape(label(i["issue_type"]))}</div>' for i in issues) or '<div class="demo-row" style="color:#64748B;">无待处理问题</div>'
    return f'''<div class="demo-side {css_extra}">
<div class="demo-tag">{tag}</div>
<div class="demo-row">候选研判：{_pill(candidate.get("status"))}<span style="color:#64748B;">（风险 {escape(label(candidate.get("risk_level")))}）</span></div>
<div class="demo-row">审计与门控：{_pill(audit["final_decision"])}</div>
<div class="demo-row" style="margin-top:10px;color:#64748B;font-size:12px;font-weight:700;">拦截理由</div>
{issue_html}
</div>'''


def render_demo_scenarios(root):
    replay_path = root / 'evaluation/mechanism_v1/replay.json'
    st.markdown(f'<style>{_SIDE_CSS}</style>', unsafe_allow_html=True)
    st.subheader('现场对照：改变一类判断或证据')
    st.caption('下列每一幕比较同一场景的一类判断或证据变化，显示全部字段差异。全部为离线回放，不调用模型。')
    if not replay_path.exists():
        st.info('尚未生成离线回放文件，无法展示对照演示。')
        return
    replay = _load_replay(str(replay_path), replay_path.stat().st_mtime_ns)

    for scene in SCENES:
        before = replay.get(f'MECH-00-{scene["before"]}')
        if before is None:
            continue
        st.markdown(f'<div class="demo-h">{scene["title"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="demo-change">改动：{scene["change"]}</div>', unsafe_allow_html=True)
        for after_key in scene['afters']:
            after = replay.get(f'MECH-00-{after_key}')
            if after is None:
                continue
            left, right = st.columns(2)
            with left:
                st.markdown(_side(before, '改动前'), unsafe_allow_html=True)
            with right:
                st.markdown(_side(after, '改动后'), unsafe_allow_html=True)
            diffs = _diff(before['input']['raw_evidence'], after['input']['raw_evidence'])
            if diffs:
                rows = ''.join(
                    f'<span class="demo-diff">{escape(" / ".join(label(part) for part in key.split("/") if part))}：{escape(translate_report(old))} → {escape(translate_report(new))}</span>'
                    for key, old, new in diffs)
                st.markdown(f'<div class="demo-row" style="color:#64748B;font-size:12px;font-weight:700;margin-top:8px;">'
                            f'两次输入的原始证据差异（{len(diffs)} 处）</div>{rows}', unsafe_allow_html=True)
            else:
                st.markdown('<div class="demo-none">两次输入的原始证据完全一致（0 处差异）——变的只有模型自己写出的结论。</div>',
                            unsafe_allow_html=True)
        st.markdown(f'<div class="demo-take">{scene["takeaway"]}</div>', unsafe_allow_html=True)
        st.divider()

    st.caption('说明：以上为人工构造的白盒机制验证，仅证明机制在既定变体上按预期工作；'
               '100 米为研究阈值，不是法规限高；自动展示不等于飞行许可或自动执法。')
