"""仅对合成机制实验执行输入中明示的风险规则，禁止把候选标签当成证据。"""
import math

from backend.audit.checks import conflicts, usable
from backend.audit.constraints import evidence_context_issues
from backend.evidence import canonical, group_evidence


RISKS = {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}
OPERATORS = {'eq', 'lte', 'gte', 'lt', 'gt'}


def _insufficient(reason):
    return {'status': 'INSUFFICIENT', 'risk_level': None, 'evidence_ids': [],
            'rule_ids': [], 'reason': reason}


def _predicate(predicate, groups):
    """返回匹配、不匹配或不可确定；高度谓词检查给定全轨迹峰值。"""
    field = canonical(predicate['field'])
    rows = groups.get(field, [])
    if not rows or any(not usable(row.value) for row in rows):
        return None, []
    if any(row.source_type not in ('constructed', 'sensor', 'official_record')
           or row.confidence != 'high' for row in rows):
        return None, []
    expected, operator = predicate['value'], predicate['operator']
    values = [row.value for row in rows]
    if type(expected) in (int, float):
        finite_number = lambda value: type(value) is int or (type(value) is float and math.isfinite(value))
        if not finite_number(expected) or any(not finite_number(value) for value in values):
            return None, []
        if field == 'altitude':
            values = [max(values)]
    elif type(expected) in (bool, str):
        if operator != 'eq' or not usable(expected) or any(type(value) is not type(expected) for value in values):
            return None, []
    else:
        return None, []
    comparisons = {
        'eq': lambda actual: actual == expected,
        'lte': lambda actual: actual <= expected,
        'gte': lambda actual: actual >= expected,
        'lt': lambda actual: actual < expected,
        'gt': lambda actual: actual > expected,
    }
    return all(comparisons[operator](value) for value in values), [row.evidence_id for row in rows]


def _altitude_context_matches(package, policy):
    """高度阈值须明示离地高度与米；每个原始高度记录也须给出相同口径。"""
    if policy.get('altitude_datum') != 'AGL' or policy.get('altitude_unit') != 'm':
        return False
    sources = package.raw_evidence.get('sources', {})
    if not isinstance(sources, dict):
        return False
    declared_sources = set()
    for source, value in sources.items():
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict) or not any(canonical(field) == 'altitude' for field in row):
                continue
            if row.get('altitude_datum') != 'AGL' or row.get('altitude_unit') != 'm':
                return False
            declared_sources.add(source)
    altitude_evidence = [row for row in package.evidence if canonical(row.field) == 'altitude']
    return bool(altitude_evidence) and all(row.source in declared_sources for row in altitude_evidence)


def evaluate_risk_policy(package):
    """策略是版本化输入的一部分，只证明合成分级机制，不证明法规合法或真实安全。

    research_policy={policy_id, scope:'synthetic_mechanism_only', altitude_datum:'AGL', altitude_unit:'m', rules:[
      {rule_id, risk_level, all:[{field, operator, value}, ...]}]}
    每条规则须覆盖整个 required_evidence，且不存在空谓词、冲突或歧义。
    此模块不接收 candidate、ground_truth 或 expected_audit。
    """
    raw = package.raw_evidence
    policy = raw.get('research_policy') if isinstance(raw, dict) else None
    if not package.is_constructed or not isinstance(policy, dict) \
            or policy.get('scope') != 'synthetic_mechanism_only':
        return _insufficient('缺少明确可执行的风险规则；事实正确及候选自报低风险不能证明风险结论')
    policy_id, rules = policy.get('policy_id'), policy.get('rules')
    if not isinstance(policy_id, str) or not policy_id.strip() or not isinstance(rules, list) or not rules:
        return _insufficient('合成机制规则缺少策略编号或非空规则集')
    required = {canonical(field) for field in package.required_evidence}
    if not required:
        return _insufficient('合成机制规则缺少明确的关键证据要件')
    if conflicts(package.evidence):
        return _insufficient('证据存在来源冲突，合成机制规则不能证明风险结论')
    if evidence_context_issues(package):
        return _insufficient('显式证据主体或高度语义不一致，合成机制规则不能证明风险结论')
    groups = group_evidence(package.evidence)
    matches, seen_ids = [], set()
    for rule in rules:
        if not isinstance(rule, dict):
            return _insufficient('合成机制规则格式不完整')
        rule_id, level, predicates = rule.get('rule_id'), rule.get('risk_level'), rule.get('all')
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in seen_ids \
                or not isinstance(level, str) or level not in RISKS or not isinstance(predicates, list) or not predicates:
            return _insufficient('合成机制规则存在无效编号、风险等级或空谓词')
        seen_ids.add(rule_id)
        if any(not isinstance(item, dict) or not isinstance(item.get('field'), str)
               or not item['field'].strip() or not isinstance(item.get('operator'), str)
               or item['operator'] not in OPERATORS or 'value' not in item
               for item in predicates):
            return _insufficient('合成机制规则存在不能可靠执行的谓词')
        if not required <= {canonical(item['field']) for item in predicates}:
            return _insufficient('合成机制规则未覆盖全部关键证据要件')
        if any(canonical(item['field']) == 'altitude' for item in predicates) and not _altitude_context_matches(package, policy):
            return _insufficient('合成高度规则与全部原始高度记录须显式声明同一离地高度基准和米单位；缺少口径或不一致时不能证明')
        outcomes = [_predicate(item, groups) for item in predicates]
        if any(matched is None for matched, _ in outcomes):
            return _insufficient('合成机制规则条件缺失、来源不足或比较类型不可靠')
        if all(matched for matched, _ in outcomes):
            matches.append((rule_id, level, [identity for _, ids in outcomes for identity in ids]))
    if not matches:
        return _insufficient('证据未匹配任何合成机制规则，不能由候选风险倒推规则成立')
    if len({level for _, level, _ in matches}) != 1:
        return _insufficient('多个合成机制规则匹配不同风险等级，结论存在歧义')
    return {'status': 'SUPPORTED', 'risk_level': matches[0][1],
            'evidence_ids': list(dict.fromkeys(identity for _, _, ids in matches for identity in ids)),
            'rule_ids': [rule_id for rule_id, _, _ in matches],
            'reason': f'匹配合成机制规则 {policy_id}；仅验证研究分级，不证明法规合法或真实场景安全'}
