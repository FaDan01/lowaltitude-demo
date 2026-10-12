"""强类型运行契约；保留原始案例扩展字段，分离标注和运行时输入。"""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Risk = Literal['LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNKNOWN']
Decision = Literal['PASS', 'WARNING', 'MANUAL_REVIEW', 'BLOCK']
EvidenceStatus = Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT', 'UNKNOWN']


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra='allow')
    correct_case_status: str
    correct_risk: Risk
    expert_validated: bool


class Case(BaseModel):
    model_config = ConfigDict(extra='allow')
    case_id: str = Field(min_length=1)
    event_type: str
    case_type: str
    context: str | dict
    raw_evidence: str | dict
    ai_output: dict
    ground_truth: GroundTruth
    expected_audit: dict
    data_tier: str
    evidence_mode: str
    ground_truth_source: str
    evidence_refs: list
    is_synthetic_demo: bool


class Evidence(BaseModel):
    evidence_id: str
    field: str
    value: Any
    source: str
    source_type: str
    confidence: str
    path: str
    timestamp: str | None = None
    constructed: bool = False


class Claim(BaseModel):
    claim_id: str
    text: str = Field(min_length=1)
    claim_type: Literal['fact', 'inference', 'conclusion']
    field: str
    operator: Literal['eq', 'lte', 'gte', 'contains', 'unknown'] = 'eq'
    value: Any = None
    depends_on: list[str] = Field(default_factory=list)
    evidence_status: EvidenceStatus = 'UNKNOWN'
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    reason: str = ''


class Candidate(BaseModel):
    event_summary: str
    risk_level: Risk
    status: Literal['PASS', 'WARNING', 'MANUAL_REVIEW', 'EXCEEDS_AUTHORITY']
    risk_reasons: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(min_length=1)


class AuditPackage(BaseModel):
    case_id: str
    raw_evidence: str | dict
    context: str | dict
    required_evidence: list[str]
    evidence: list[Evidence]
    event: dict
    missing_fields: list[str]
    empty_fields: list[str]
    existing_ai_output: str | None = None
    is_constructed: bool


class Issue(BaseModel):
    issue_type: str
    code_e: str | None = None
    code_status: str = 'pending_code_table'
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    claim_id: str | None = None


class AuditResult(BaseModel):
    final_decision: Decision
    audit_depth: Literal['L0', 'L1', 'L2', 'L3']
    claims: list[Claim]
    issues: list[Issue]
    missing_required: list[str]
    rule_hits: list[str]
    rule_version_used: dict[str, str]
    rationale: str


class ExperimentRecord(BaseModel):
    run_id: str
    case_id: str
    status: Literal['success', 'failed', 'unavailable']
    mode: str
    created_at: str
    metric_source: str = 'actual_gate'
    pre_audit_status: str | None = None
    gate_final_decision: Decision | None = None
    rule_version_used: dict[str, str] = Field(default_factory=dict)
    cost: float | None = None
    cost_note: str = '未配置经核验单价；不将未知费用写成0'
