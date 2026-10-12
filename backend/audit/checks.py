"""执行字段比对、独立源冲突和有效期检查；输入证据与主张，输出四态及问题。"""
from datetime import datetime
import re
from backend.evidence import canonical, group_evidence
from backend.models import Issue
from backend.paths import read_rules


def usable(value):
    """False和0是有效观测；UNKNOWN和EMPTY不是。"""
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None and value not in ('', 'UNKNOWN', 'EMPTY')


def compare(claim, evidence):
    """针对可结构化原子主张比对证据，不以结论标签替代证据。"""
    rows = [e for e in evidence if e.field == canonical(claim.field)]
    good = [e for e in rows if usable(e.value)]
    claim.supporting_evidence = []
    claim.contradicting_evidence = []
    if not rows:
        claim.evidence_status, claim.reason = 'UNKNOWN', '未发现可映射的字段证据'
        return claim
    if not good:
        claim.evidence_status, claim.reason = 'INSUFFICIENT', '相关来源存在，但值为UNKNOWN或EMPTY'
        return claim
    if canonical(claim.field) == 'flight_permission' and re.search('获批|获得批复|已批准|取得批准', claim.text):
        if not any(e.field == 'approval_no' and usable(e.value) for e in evidence):
            claim.evidence_status, claim.reason = 'INSUFFICIENT', '提出申请不等于获得批复，缺少明确批复记录'
            return claim
    # 全轨迹聚合峰值；独立来源冲突由conflicts独立报告。
    if canonical(claim.field) == 'altitude':
        numeric = [e for e in good if type(e.value) in (int, float)]
        if numeric:
            peak = max(e.value for e in numeric)
            good = [e for e in numeric if e.value == peak]
    for row in good:
        actual, expected = row.value, claim.value
        mapping = read_rules('fields').get('boolean_values', {}).get(canonical(claim.field), {})
        if isinstance(expected, str) and expected in mapping:
            expected = mapping[expected]
        if claim.operator == 'unknown' or not usable(expected):
            continue
        if claim.operator in ('lte', 'gte'):
            if type(actual) not in (int, float) or type(expected) not in (int, float):
                continue
            matched = actual <= expected if claim.operator == 'lte' else actual >= expected
        elif claim.operator == 'contains':
            if not isinstance(actual, str) or not isinstance(expected, str):
                continue
            matched = expected in actual
        else:
            if type(actual) != type(expected) and not (type(actual) in (int, float) and type(expected) in (int, float)):
                # 类型不能比较不是反证，避免“已登记”字符串被错误判为事实矛盾。
                continue
            matched = type(actual) == type(expected) and actual == expected
            if type(actual) in (int, float) and type(expected) in (int, float):
                matched = abs(actual - expected) < 1e-6
        target = claim.supporting_evidence if matched else claim.contradicting_evidence
        target.append(row.evidence_id)
    if claim.contradicting_evidence:
        claim.evidence_status, claim.reason = 'CONTRADICTED', '存在字段级反证；未忽略反向证据'
    elif claim.supporting_evidence:
        claim.evidence_status, claim.reason = 'SUPPORTED', '可定位字段支持该原子主张'
    else:
        claim.evidence_status, claim.reason = 'INSUFFICIENT', '字段已定位，但比较关系尚不能可靠执行'
    return claim


def conflicts(evidence):
    """同字段不同独立来源值不一致即保留冲突；同轨迹时间变化不算冲突。"""
    issues = []
    for field, rows in group_evidence(evidence).items():
        by_source = {}
        for row in rows:
            if usable(row.value) and not isinstance(row.value, (list, dict)):
                by_source.setdefault(row.source, []).append(row)
        if len(by_source) < 2:
            continue
        summaries = []
        for values in by_source.values():
            numeric = [e.value for e in values if type(e.value) in (int, float)]
            summaries.append(max(numeric) if numeric else values[-1].value)
        def same_value(first, second):
            numeric = type(first) in (int, float) and type(second) in (int, float)
            return (numeric or type(first) is type(second)) and first == second
        if any(not same_value(value, summaries[0]) for value in summaries[1:]):
            issues.append(Issue(issue_type='EVIDENCE_CONFLICT', reason=f'{field}的独立来源不一致，未擅自挑选有利来源',
                                evidence_ids=[e.evidence_id for e in rows]))
    return issues


def time_checks(package):
    """核对实际事件时间与许可有效期，含时区；缺日期不编造。"""
    raw = package.raw_evidence
    sources = raw.get('sources', {}) if isinstance(raw, dict) else {}
    permission = sources.get('permission_query', {})
    start, end = permission.get('valid_from'), permission.get('valid_to')
    if not start or not end:
        return []
    try:
        moment = datetime.fromisoformat(package.event['event_time'].replace('Z', '+00:00'))
        valid_from = datetime.fromisoformat(start.replace('Z', '+00:00'))
        valid_to = datetime.fromisoformat(end.replace('Z', '+00:00'))
        valid = valid_from <= moment <= valid_to
    except (TypeError, ValueError):
        return [Issue(issue_type='INSUFFICIENT_EVIDENCE', reason='时间格式/时区不可可靠比较')]
    if not valid:
        return [Issue(issue_type='TIMELINESS_ERROR', reason='事件时间不在批复有效期内',
                      evidence_ids=[e.evidence_id for e in package.evidence if e.source == 'permission_query'])]
    return []


def verify_time_inference(claim, by_id, package):
    """仅验证显式时间窗口内判断，不把数值关系当成法律合规。"""
    import re
    dependencies = [by_id[x] for x in claim.depends_on if x in by_id]
    fields = {canonical(c.field) for c in dependencies}
    if not {'valid_from', 'valid_to'} <= fields:
        return False
    if not re.search(r'(?:有效期|有效时间|有效窗口).{0,80}(?:内|期间)', claim.text):
        return False
    if not all(c.evidence_status == 'SUPPORTED' for c in dependencies):
        return False
    values = {canonical(c.field): c.value for c in dependencies}
    # 事件时间可直接来自输入证据，必须保留相应证据链接，不凭空补时间。
    if 'flight_time' not in values:
        values['flight_time'] = package.event.get('event_time', 'UNKNOWN')
    try:
        parsed = {key: datetime.fromisoformat(values[key].replace('Z', '+00:00'))
                  for key in ('valid_from', 'valid_to', 'flight_time')}
        valid = parsed['valid_from'] <= parsed['flight_time'] <= parsed['valid_to']
    except (TypeError, ValueError, AttributeError):
        return False
    claim.evidence_status = 'SUPPORTED' if valid else 'CONTRADICTED'
    claim.reason = '事件时间与批复起止时间的确定性区间比较；不推导其他法律结论'
    ids = [eid for c in dependencies for eid in c.supporting_evidence]
    ids.extend(e.evidence_id for e in package.evidence if e.field == 'flight_time' and e.value == values['flight_time'])
    claim.supporting_evidence = ids if valid else []
    claim.contradicting_evidence = [] if valid else ids
    return True
