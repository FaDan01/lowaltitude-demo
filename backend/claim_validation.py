"""核对抽取器输出与被审查原文；输入候选和原文，输出校验后的有序主张。"""
import re
from backend.evidence import canonical
from backend.models import Claim
from backend.paths import read_rules
from backend.atomic import assertion_fields, split_clauses


_PERMISSION_NEGATIVE = re.compile(
    r'(?:未(?:曾)?|没有|尚未|从未|不曾)\s*'
    r'(?:(?:提出|提交|完成|办理)\s*(?:了\s*)?)?(?:飞行(?:活动)?\s*)?申请'
    r'|(?:未(?:曾)?|没有|尚未|从未|不曾)\s*(?:(?:进行|完成)\s*)?报备')
_PERMISSION_POSITIVE = re.compile(
    r'已(?:经)?\s*(?:(?:提出|提交|完成|办理)\s*(?:了\s*)?)?(?:飞行(?:活动)?\s*)?申请'
    r'|已(?:经)?\s*(?:(?:进行|完成)\s*)?报备')
_PERMISSION_AMBIGUOUS = re.compile(
    r'并非|不是|非(?:未|没有)|否认|不存在|不代表|不意味着|不等于|未必|不一定|不见得'
    r'|不能(?:认定|说明|证明|排除|确认|确定)|无法(?:确认|确定|排除)|没有证据'
    r'|未(?:能|明确)?确认|尚不明确|尚不能|不清楚|不确定|是否|疑似|可能|或许|据称|据说|待核实'
    r'|未(?:查询到|查到|发现)|没有(?:查询到|查到|发现)'
    r'|无需|无须|免于|免申请|免报备|不需|不必'
    r'|(?:应当|必须|需要|要求|建议|拟|计划|将|尚待).{0,8}(?:提出|提交|报备|申请)')
_ALTITUDE_NON_EQUALITY = re.compile(
    r'未(?:曾)?(?:达到|超过)|没有(?:达到|超过)|不(?:等于|超过|高于|低于|足|到)'
    r'|(?:不足|低于|高于|超过|至少|至多|最多)')


def _unmapped(claim, reason):
    """保留原文并撤销不可证明的结构化断言，不替抽取器补值或反转布尔值。"""
    claim.field, claim.operator, claim.value = 'unmapped', 'unknown', None
    claim.evidence_status = 'UNKNOWN'
    claim.supporting_evidence, claim.contradicting_evidence = [], []
    claim.reason = reason


def _validate_permission(claim):
    """只审查明确申请/报备状态；缺记录、豁免及双重否定均不等同实际未申请。"""
    negative = bool(_PERMISSION_NEGATIVE.search(claim.text))
    positive = bool(_PERMISSION_POSITIVE.search(claim.text))
    if _PERMISSION_AMBIGUOUS.search(claim.text) or negative == positive:
        _unmapped(claim, '申请原文含模糊否定、双重否定或未明确实际申请状态；保留原文待核查')
        return
    mapping = read_rules('fields')['boolean_values'].get('flight_permission', {})
    parsed = mapping.get(claim.value, claim.value) if isinstance(claim.value, str) else claim.value
    if type(parsed) is not bool:
        _unmapped(claim, '申请状态未抽取为明确布尔值；数字0/1、空值与未知不能代替否定/肯定')
        return
    if negative and parsed is True:
        raise ValueError('抽取值与原文否定申请/报备状态冲突')
    if positive and parsed is False:
        raise ValueError('抽取值与原文肯定申请/报备状态冲突')


def validate_candidate(candidate, original=None):
    """拒绝悬空/循环、值与原文矛盾；未覆盖语句保留UNKNOWN而非悄悄丢弃。"""
    index = {c.claim_id: c for c in candidate.claims}
    if len(index) != len(candidate.claims):
        raise ValueError('重复claim_id')
    visited, ordered = set(), []

    def visit(identity, stack):
        if identity in stack or identity not in index:
            raise ValueError('主张依赖循环或悬空')
        if identity in visited:
            return
        for dependency in index[identity].depends_on:
            visit(dependency, stack | {identity})
        visited.add(identity)
        ordered.append(index[identity])

    for claim in candidate.claims:
        visit(claim.claim_id, set())
        if original is not None and claim.text not in original:
            raise ValueError(f'抽取主张不是原文子串: {claim.claim_id}')
        field = canonical(claim.field)
        if field == 'registration_status':
            mapping = read_rules('fields')['boolean_values']['registration_status']
            parsed = mapping.get(claim.value, claim.value) if isinstance(claim.value, str) else claim.value
            if re.search(r'未.{0,5}(?:实名)?登记', claim.text) and parsed is True:
                raise ValueError('抽取值与原文否定登记状态冲突')
            if re.search(r'已.{0,10}登记', claim.text) and parsed is False:
                raise ValueError('抽取值与原文肯定登记状态冲突')
        if field == 'flight_permission':
            _validate_permission(claim)
        if field == 'altitude' and type(claim.value) in (int, float):
            numbers = {float(x) for x in re.findall(r'(?<!\d)(\d+(?:\.\d+)?)', claim.text)}
            if float(claim.value) not in numbers:
                raise ValueError('抽取高度值不在主张原文中')
            if claim.operator == 'eq' and _ALTITUDE_NON_EQUALITY.search(claim.text):
                _unmapped(claim, '高度原文表达范围或否定关系，不能抽取为等值事实；未自动改写比较关系')
        # 一个布尔字段不能替整句的高度、授权或安全结论提供证据。
        # 抽取不完整时保留原文待核查，禁止悄悄把剩余判断视作已验证。
        other_fields = assertion_fields(claim.text) - {field}
        if other_fields:
            _unmapped(claim, '复合主张含多个不同判断，尚未完整拆为可核验的原子主张')
    candidate.claims = ordered
    if original:
        explicit = re.findall(r'(?:风险(?:等级)?|初步风险)[：:为\s]*(LOW|MEDIUM|HIGH|CRITICAL)', original)
        if explicit and explicit[-1] != candidate.risk_level:
            raise ValueError('抽取风险与原文显式风险不一致')
        residual = original
        for claim in sorted(candidate.claims, key=lambda c: len(c.text), reverse=True):
            residual = residual.replace(claim.text, '')
        residual = re.sub(r'(?:事件摘要|初步判断|初步结论|风险等级|初步风险|初步理由)\s*[：:]', '', residual)
        for segment in split_clauses(residual):
            if len(re.sub(r'[\W\d_]', '', segment)) >= 4:
                identity = f'UNCOVERED-{len(candidate.claims)}'
                candidate.claims.append(Claim(claim_id=identity, text=segment.strip(), claim_type='fact',
                    field='unmapped', operator='unknown', reason='抽取器未覆盖的原文，保留待核查'))
