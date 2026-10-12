"""把已保存结果导出为可打印中文报告；仅展示快照，不重新研判。"""
from html import escape

from frontend.labels_zh import label, translate_report
from backend.remediation import build_remediation


def render_report_html(record, package, audit, candidate=None):
    """越权候选不进入报告；原始编号保留，动态文字全部转义。"""
    text = lambda value: escape(translate_report(value))
    rows = ''.join(f'<tr><th>{escape(name)}</th><td>{text(value)}</td></tr>' for name,value in (
        ('案例编号',record.get('case_id','未记录')), ('运行编号',record.get('run_id','未记录')),
        ('运行方式',label(record.get('mode'))), ('保存时间',record.get('created_at','未记录')),
        ('自动判定',label(audit.final_decision)), ('审计级别',label(audit.audit_depth)),
        ('数据来源',label(record.get('ground_truth_source'))),
        ('专家确认','已确认' if record.get('expert_validated') is True else '未确认')))
    body = f'<table>{rows}</table><p>{text(audit.rationale)}</p>'
    if audit.final_decision == 'BLOCK':
        body += '<p>候选输出涉及越权，普通报告已隐藏候选原文及主张。原记录仅供本机审计追溯。</p>'
    else:
        if candidate:
            body += '<h2>模型候选摘要（未经逐句核验）</h2><p>'+text(candidate.event_summary)+'</p>'
        body += '<h2>逐条主张核验</h2><table><tr><th>编号</th><th>主张</th><th>状态</th><th>依据与证据编号</th></tr>'
        for claim in audit.claims:
            ids = ', '.join(claim.supporting_evidence + claim.contradicting_evidence)
            body += f'<tr><td>{text(claim.claim_id)}</td><td>{text(claim.text)}</td><td>{text(label(claim.evidence_status))}</td><td>{text(claim.reason)}<br>{text(ids)}</td></tr>'
        body += '</table>'
    body += '<h2>问题与核对要求</h2><ul>'
    body += ''.join(f'<li>{text(label(issue.issue_type))}：{text(issue.reason)}</li>' for issue in audit.issues)
    body += '</ul><h2>补证建议</h2><ul>'
    for item in build_remediation(package, audit):
        body += '<li>'+text(item['reason'])+'：'+text(item['request'])+'</li>'
    body += '</ul>'
    if audit.final_decision != 'BLOCK':
        body += '<h2>证据索引</h2><table><tr><th>编号</th><th>字段</th><th>来源</th><th>定位路径</th></tr>'
        for evidence in package.evidence:
            body += f'<tr><td>{text(evidence.evidence_id)}</td><td>{text(label(evidence.field))}</td><td>{text(label(evidence.source))}</td><td>{text(evidence.path)}</td></tr>'
        body += '</table>'
    versions = '；'.join(f'{label(name)} {version}' for name,version in audit.rule_version_used.items())
    body += '<h2>记录与适用范围</h2><p>'+text(versions)+'</p>'
    body += '<p>输入摘要：'+text(record.get('input_sha256','未记录'))+'</p>'
    body += '<p>本报告用于辅助研判。附件接收不等于内容核验；合成回放不证明真实准确率。补证须重新审计，人工复核另行记录，自动结论不因此改写。</p>'
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>低空安全辅助研判报告</title><style>
body{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:#182b3a;max-width:1100px;margin:32px auto;padding:0 24px;line-height:1.7}
h1{font-size:26px}h2{font-size:19px;margin-top:28px}table{border-collapse:collapse;width:100%;font-size:13px;table-layout:fixed}
th,td{border:1px solid #cbd5e1;padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#f1f5f9}
@media print{body{margin:0;padding:0}h2{break-after:avoid}tr{break-inside:avoid}a{color:inherit}}
</style></head><body><h1>低空安全辅助研判报告</h1>'''+body+'</body></html>'
