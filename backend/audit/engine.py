"""确定性审计与门控；输入无标签AuditPackage、候选，输出可追溯AuditResult。"""
from backend.audit.authority import inspect_authority
from backend.audit.checks import compare, conflicts, time_checks, usable, verify_time_inference
from backend.audit.constraints import evidence_context_issues
from backend.audit.risk_policy import evaluate_risk_policy
from backend.evidence import canonical, group_evidence
from backend.models import AuditResult, Issue
from backend.paths import read_rules


def audit(package, candidate, original_text):
    """依次审查来源、要件、主张、依赖与越权，R4/R3/R2/R1决定输出。"""
    gate_rules, depth_rules = read_rules('decision_gate'), read_rules('audit_depth')
    groups = group_evidence(package.evidence)
    required = list(dict.fromkeys(canonical(name) for name in package.required_evidence))
    missing = [name for name in required if not any(usable(e.value) for e in groups.get(name, []))]
    issues = conflicts(package.evidence) + time_checks(package) + evidence_context_issues(package)
    claims = [c.model_copy(deep=True) for c in candidate.claims]
    if not required:
        missing.append('required_evidence_spec')
    for name in missing:
        issues.append(Issue(issue_type='INSUFFICIENT_EVIDENCE', reason=f'缺少关键要件：{name}'))
    authority_findings = inspect_authority(original_text, gate_rules)
    for finding in authority_findings:
        if finding.decision == 'BLOCK':
            issues.append(Issue(issue_type='EXCEEDS_AUTHORITY', reason=finding.trace))
        elif finding.decision == 'MANUAL_REVIEW':
            issues.append(Issue(issue_type='INSUFFICIENT_EVIDENCE', reason='处置权限/语境待核对；' + finding.trace))
    fields_mentioned = {canonical(c.field) for c in claims}
    for name in required:
        if name not in fields_mentioned and name not in missing:
            issues.append(Issue(issue_type='OMISSION', reason=f'已提供的关键字段未在主张中覆盖：{name}',
                                evidence_ids=[e.evidence_id for e in groups[name]]))
    # 先处理事实，再核对依赖；风险等级本身不能只通过和参考标签比较来判对。
    for claim in claims:
        if canonical(claim.field) in ('risk_level', 'overall_assessment'):
            continue
        compare(claim, package.evidence)
        if claim.evidence_status == 'CONTRADICTED':
            issues.append(Issue(issue_type='FACTUAL_ERROR', reason=claim.reason, claim_id=claim.claim_id,
                                evidence_ids=claim.contradicting_evidence))
        if claim.value is False and any(e.value == 'UNKNOWN' for e in groups.get(canonical(claim.field), [])):
            issues.append(Issue(issue_type='UNKNOWN_AS_NEGATION', reason='将未知字段作为否定事实', claim_id=claim.claim_id))
    by_id = {c.claim_id: c for c in claims}
    risk_grounding = evaluate_risk_policy(package)
    if risk_grounding['status'] != 'SUPPORTED':
        issues.append(Issue(issue_type='INSUFFICIENT_EVIDENCE', reason=risk_grounding['reason']))
    elif candidate.risk_level != risk_grounding['risk_level']:
        ranks = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CRITICAL': 3, 'UNKNOWN': -1}
        underestimated = ranks[candidate.risk_level] < ranks[risk_grounding['risk_level']]
        issue_type = 'HIGH_RISK_NOT_ESCALATED' if underestimated and risk_grounding['risk_level'] in ('HIGH', 'CRITICAL') else 'RULE_MISMATCH'
        issues.append(Issue(issue_type=issue_type,
                            reason=f"候选风险与合成机制规则不一致：候选{candidate.risk_level}，规则{risk_grounding['risk_level']}；不作法规或真实场景定性",
                            evidence_ids=risk_grounding['evidence_ids']))
    for claim in claims:
        if canonical(claim.field) in ('risk_level', 'overall_assessment'):
            claim.supporting_evidence = []
            claim.contradicting_evidence = []
            if canonical(claim.field) == 'overall_assessment':
                claim.evidence_status = 'INSUFFICIENT'
                claim.reason = '整体安全或合法性结论缺少可执行适用规则；合成风险分级不能证明该结论'
            elif risk_grounding['status'] != 'SUPPORTED':
                claim.evidence_status = 'INSUFFICIENT'
                claim.reason = risk_grounding['reason']
            elif claim.value != risk_grounding['risk_level']:
                claim.evidence_status = 'CONTRADICTED'
                claim.reason = '风险主张与已匹配合成机制规则不一致；不作真实场景定性'
                claim.contradicting_evidence = risk_grounding['evidence_ids']
            else:
                claim.evidence_status = 'SUPPORTED'
                claim.reason = risk_grounding['reason']
                claim.supporting_evidence = risk_grounding['evidence_ids']
        if claim.claim_type != 'fact':
            # 原文没有依赖图时不能替模型补图；审计已执行的独立规则证明可直接引用原始证据。
            # 仅支持已证明的风险结论；其他结论及显式但失效的模型依赖仍需复核。
            independently_grounded_risk = (
                claim.claim_type == 'conclusion' and canonical(claim.field) == 'risk_level'
                and not claim.depends_on and risk_grounding['status'] == 'SUPPORTED'
                and claim.evidence_status == 'SUPPORTED' and bool(claim.supporting_evidence))
            if independently_grounded_risk:
                claim.reason += '；原文未提供主张依赖，审计独立执行规则并直接链接证据，未补造模型依赖图'
            broken = (not claim.depends_on and not independently_grounded_risk) or any(
                dep not in by_id or by_id[dep].evidence_status != 'SUPPORTED' for dep in claim.depends_on)
            if broken or missing:
                issues.append(Issue(issue_type='OVER_INFERENCE', reason='推理/结论依赖缺失、未获支持或关键要件不足', claim_id=claim.claim_id))
                if claim.evidence_status == 'SUPPORTED':
                    claim.evidence_status = 'INSUFFICIENT'
                    claim.reason = '字段比对成立，但推理/结论的依赖或要件不完整'
            if claim.claim_type == 'inference' and not verify_time_inference(claim, by_id, package):
                # TODO: NEEDS_SPEC 业务推理规则尚无可执行的适用性条件。
                claim.evidence_status = 'INSUFFICIENT'
                claim.reason = '数值比对不能独立证明业务推理；需要经确认的规则适用性'
    # 来源规则适用于关键要件；公共报道不能独立支撑PASS。
    weak_source = any(not any(e.source_type in ('sensor', 'official_record', 'constructed') and e.confidence == 'high'
                             for e in groups.get(name, [])) for name in required if name not in missing)
    if weak_source:
        issues.append(Issue(issue_type='INSUFFICIENT_EVIDENCE', reason='关键要件来源等级不足；公开报道不得独立支持PASS'))
    explicit_hazards = any(e.field in ('firmware_status', 'geofence_violation') and e.value is True
                           or e.field in ('registration_status', 'flight_permission') and e.value is False for e in package.evidence)
    if explicit_hazards and candidate.status == 'PASS':
        issues.append(Issue(issue_type='OVER_INFERENCE', reason='存在明确异常字段，候选仍直接放行，需核查适用规则'))
    unresolved = bool(missing or issues or candidate.uncertainty or candidate.risk_level == 'UNKNOWN'
                      or candidate.status == 'MANUAL_REVIEW'
                      or any(c.evidence_status != 'SUPPORTED' for c in claims))
    exceeds = candidate.status == 'EXCEEDS_AUTHORITY' or any(i.issue_type == 'EXCEEDS_AUTHORITY' for i in issues)
    if candidate.status == 'EXCEEDS_AUTHORITY' and not any(i.issue_type == 'EXCEEDS_AUTHORITY' for i in issues):
        issues.append(Issue(issue_type='EXCEEDS_AUTHORITY', reason='候选结构化状态明确标记越权，阻断展示'))
    if exceeds:
        rule = 'R4'
    elif unresolved:
        rule = 'R3'
    elif candidate.risk_level != 'LOW' or candidate.status != 'PASS':
        rule = 'R2'
    else:
        rule = 'R1'
    high = candidate.risk_level in ('HIGH', 'CRITICAL')
    flags = {'high_and_unresolved': high and unresolved, 'high_or_unresolved': high or unresolved,
             'medium': candidate.risk_level == 'MEDIUM', 'low_complete': not unresolved and candidate.risk_level == 'LOW'}
    depth = next((level for level in depth_rules['match_order'] if flags[depth_rules['levels'][level]['condition']]), depth_rules['default_level'])
    for issue in issues:
        if issue.issue_type not in gate_rules['issue_types']:
            raise ValueError('未登记IssueType')
        issue.code_e = gate_rules['confirmed_code_mapping'].get(issue.issue_type)
        issue.code_status = 'mapped_per_resolution' if issue.code_e else 'pending_code_table'
    rationale = {'R4': '候选输出越权，阻断展示并转人工处理', 'R3': '存在未解问题，需人工复核',
                 'R2': '有风险且合成分级规则支持，自动预警', 'R1': '当前要件与主张通过合成机制检查，可自动展示辅助研判'}[rule]
    if risk_grounding['status'] == 'SUPPORTED':
        rationale += f"；{risk_grounding['reason']}"
    contextual_authority = [finding.trace for finding in authority_findings if finding.decision == 'CONTEXT_ONLY']
    if contextual_authority:
        rationale += '；有限文本处置检查（不证明引述事实为真）：' + '；'.join(contextual_authority)
    return AuditResult(final_decision=gate_rules['actions'][rule], audit_depth=depth, claims=claims,
        issues=issues, missing_required=missing, rule_hits=[rule] + [f'research:{identity}' for identity in risk_grounding['rule_ids']],
        rule_version_used={'decision_gate': gate_rules['version'], 'audit_depth': depth_rules['version'], 'fields': read_rules('fields')['version']},
        rationale=rationale)
