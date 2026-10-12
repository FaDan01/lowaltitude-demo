"""中文展示适配：只生成展示副本，不修改后端字段、编号或存储结果。"""
from __future__ import annotations

import re
from typing import Any


CASE_TYPE_LABELS = {
    'control_ai_correct': '研判正确对照',
    'evidence_conflict': '证据冲突',
    'evidence_missing': '证据缺失',
    'fact_error': '事实错误',
    'normal': '正常案例',
    'over_inference': '过度推断',
    'risk_underestimate': '风险低估',
    'rule_error': '规则错误',
    'selective_evidence': '选择性采证',
    'temporal_error': '时间逻辑错误',
    'unknown_case': '待明确案例',
    'hidden_error': '隐含错误',
}

EVIDENCE_MODE_LABELS = {
    'narrative_only': '叙事文本',
    'structured_public_report': '公开报道结构化',
    'structured_constructed': '构造结构化证据',
}

DECISION_LABELS = {
    'PASS': '通过',
    'WARNING': '预警',
    'MANUAL_REVIEW': '人工复核',
    'BLOCK': '阻断',
    'EXCEEDS_AUTHORITY': '越权',
}

EVIDENCE_STATUS_LABELS = {
    'SUPPORTED': '证据支持',
    'CONTRADICTED': '证据矛盾',
    'INSUFFICIENT': '证据不足',
    'UNKNOWN': '未知',
}

RISK_LABELS = {
    'LOW': '低风险',
    'MEDIUM': '中风险',
    'HIGH': '高风险',
    'CRITICAL': '极高风险',
    'UNKNOWN': '未知',
}

MODE_LABELS = {
    'generate': '独立研判（真实模型）',
    'review': '审查已有输出',
    'fixture': '原包回放',
}

ISSUE_TYPE_LABELS = {
    'FACTUAL_ERROR': '事实错误',
    'INSUFFICIENT_EVIDENCE': '证据不足',
    'OVER_INFERENCE': '过度推断',
    'RULE_MISMATCH': '规则不匹配',
    'HIGH_RISK_NOT_ESCALATED': '高风险未升级',
    'EXCEEDS_AUTHORITY': '越权',
    'EVIDENCE_CONFLICT': '证据冲突',
    'TIMELINESS_ERROR': '时间逻辑错误',
    'BIASED_OUTPUT': '偏向性输出',
    'UNKNOWN_AS_NEGATION': '将未知当作否定',
    'OMISSION': '关键事实遗漏',
    'SELECTIVE_EVIDENCE': '选择性采证',
    'RISK_OVERESTIMATE': '风险高估',
}

SOURCE_LABELS = {
    'constructed': '人工构造',
    'public_case': '公开案例',
    'sensor': '传感器',
    'official_record': '官方记录',
    'public_report': '公开报道',
    'unknown': '未知',
    'high': '高',
    'medium': '中',
    'low': '低',
    'structured': '结构化',
    'text_derived': '文本提取',
    'stated_in_report': '通报转述',
    'present': '已提供',
    'partial': '部分提供',
    'absent': '缺失',
    'actual_gate': '实际门控结果',
    'legacy_proxy': '旧版代理指标',
    'pending_code_table': '编码表待确认',
    'mapped_per_resolution': '已按决议映射',
    'PENDING_SIGNOFF': '待签字确认',
    'APPLIED_IN_MEMORY': '已应用展示加载修正',
    'actual_ai_output': '实际研判输出',
    'constructor_design': '构造设计',
    'typical_error_placeholder': '典型错误占位',
    'L1_synthetic': '一级合成数据',
    'L0_synthetic': '零级合成数据',
    'L2_real': '二级真实数据',
    'L3_gold': '三级专家金标数据',
    'A_narrative': '公开叙事案例集',
    'A_structured': '公开结构化案例集',
    'B_constructed': '构造案例集',
    'B_structured': '构造结构化层',
    'LEGAL': '合法',
    'VIOLATION': '违规',
    'success': '成功',
    'successful': '成功',
    'failed': '失败',
    'unavailable': '不可用',
    'EMPTY': '空值',
    'none': '无',
    'null': '未提供',
    'None': '未提供',
    'True': '是',
    'False': '否',
    'true': '是',
    'false': '否',
    'fact': '事实主张',
    'inference': '推理主张',
    'conclusion': '结论主张',
    'rule': '规则主张',
    'eq': '等于',
    'lte': '小于或等于',
    'gte': '大于或等于',
    'gt': '大于',
    'lt': '小于',
    'contains': '包含',
    'FALSE_PASS': '错误放行',
    'OVER_FLAG': '过度预警',
    'RISK_UNDERESTIMATE': '风险低估',
}

AUDIT_DEPTH_LABELS = {
    'L0': '零级审计',
    'L1': '一级审计',
    'L2': '二级审计',
    'L3': '三级审计',
}

RULE_LABELS = {
    'R1': '规则一：通过',
    'R2': '规则二：预警',
    'R3': '规则三：人工复核',
    'R4': '规则四：阻断',
}

FIELD_LABELS = {
    'event_id': '事件编号', 'event_time': '事件时间',
    'location': '位置', 'drone_identity': '无人机身份',
    'registration_status': '登记状态', 'altitude': '高度',
    'speed': '速度', 'trajectory': '轨迹', 'region_type': '区域属性',
    'behavior': '行为', 'text_records': '文字记录',
    'documents': '文档', 'images': '图像', 'videos': '视频', 'metadata': '元数据',
    'evidence_id': '证据编号', 'field': '字段', 'value': '观测值',
    'source': '来源', 'source_type': '来源类型', 'confidence': '置信度',
    'path': '证据路径', 'timestamp': '时间戳',
    'claim_id': '主张编号', 'claim_type': '主张类型', 'text': '主张内容',
    'operator': '比较关系', 'depends_on': '依赖主张',
    'evidence_status': '证据状态', 'supporting_evidence': '支持证据',
    'contradicting_evidence': '反向证据', 'reason': '依据和理由',
    'issue_type': '问题类型', 'code_e': '错误编码', 'code_status': '编码状态',
    'evidence_ids': '证据编号', 'final_decision': '最终决策',
    'audit_depth': '审计级别', 'claims': '主张', 'issues': '问题',
    'missing_required': '缺失要件', 'rule_hits': '命中规则',
    'rule_version_used': '使用的规则版本', 'rationale': '决策依据',
    'case_id': '案例编号', 'case_name': '案例名称', 'event_type': '事件类型',
    'case_type': '案例类型', 'context': '背景信息', 'raw_evidence': '原始证据',
    'required_evidence': '必需证据要件', 'evidence': '证据', 'event': '事件字段',
    'missing_fields': '未知字段', 'empty_fields': '空值字段',
    'existing_ai_output': '待审查的研判输出', 'is_constructed': '是否人工构造',
    'ai_output': '人工智能研判输出', 'ground_truth': '标准答案',
    'expected_audit': '预期审计', 'data_tier': '数据层级',
    'evidence_mode': '证据形态', 'ground_truth_source': '标准答案来源',
    'evidence_refs': '证据引用', 'is_synthetic_demo': '是否合成演示',
    'correct_case_status': '参考事件状态', 'correct_risk': '参考风险等级',
    'expert_validated': '专家已确认', 'risk_level': '风险等级',
    'risk_reasons': '风险依据', 'uncertainty': '不确定性', 'event_summary': '事件摘要',
    'status': '状态', 'mode': '模式', 'run_id': '运行编号',
    'created_at': '创建时间', 'metric_source': '指标来源',
    'pre_audit_status': '审计前判定', 'gate_final_decision': '审计后决策',
    'cost': '费用', 'cost_note': '费用说明', 'failure_reason': '失败原因',
    'error_type': '错误类型', 'claims_count': '主张数量', 'issues_count': '问题数量',
    'input_sha256': '输入摘要', 'implementation_sha256': '实现摘要',
    'is_fixture': '是否回放', 'sources': '证据来源', 'narrative': '叙事原文',
    'rid_trajectory': '远程识别轨迹', 'rid_broadcast': '远程识别广播',
    'radar_track': '雷达轨迹', 'registration_query': '登记查询',
    'permission_query': '飞行许可查询', 'airspace_query': '空域查询',
    'aviation_query': '民航信息查询', 'firmware_query': '固件查询',
    'geofence_query': '电子围栏查询', 'payload_query': '载荷查询',
    'target_query': '目标查询', 'aircraft_class': '航空器类别',
    'approach_path': '进近航线', 'flight_schedule': '航班计划',
    'image_disposition': '图像处置', 'impact_on_flight': '对航班的影响',
    'notam': '航行通告', 'operation': '操作记录',
    'alt_true_m': '真高（米）', 'true_altitude': '真高',
    'altitude_agl': '离地高度', 'max_height': '最大高度',
    'max_alt_m': '最大高度（米）', 'altitude_m': '高度（米）',
    'flight_trajectory_max_altitude': '轨迹最大高度',
    'zone_type': '空域类型', 'airspace_zone_type': '空域类型',
    'registered': '已登记', 'applied': '已提出飞行申请',
    'flight_permission': '飞行申请状态', 'firmware_status': '固件状态',
    'modified': '已修改固件', 'flight_time': '飞行时间', 'ts': '时间戳',
    'crossing': '穿越航线', 'flight_schedule_overlap': '与航班计划重叠',
    'overlap': '时间重叠', 'geofence_violation': '电子围栏违规',
    'violation': '违规状态', 'target_type': '目标类型', 'uploaded': '已上传',
    'payload_evidence': '载荷证据', 'notam_window': '航行通告有效期',
    'flight_trajectory': '飞行轨迹', 'approval_no': '批复编号',
    'valid_from': '有效期开始', 'valid_to': '有效期结束',
    'effective_from': '生效时间', 'effective_to': '失效时间',
    'note': '备注', 'detail': '详情', 'seq': '序号',
    'speed_mps': '速度（米／秒）', 'uas_id': '无人机编号',
    'area': '区域', 'area_type': '区域类型', 'audit_note': '审计说明',
    'audit_should_output': '预期审计决策', 'auto_passable': '可自动放行',
    'before': '修正前', 'after': '修正后', 'from': '原状态', 'to': '调整后状态',
    'case_set': '案例集合', 'case_type_note': '案例类型说明',
    'claim': '主张', 'claim_check_draft': '主张核验草案', 'claim_text': '主张内容',
    'code': '问题编码', 'decision_change': '决策调整',
    'derived': '派生字段', 'derived_note': '派生说明',
    'difficulty_tags': '难点标签', 'distance_to_runway_m': '距跑道距离（米）',
    'event_object': '事件对象', 'evidence_index': '证据索引', 'evidence_type': '证据类型',
    'exceeds_authority': '是否越权', 'expected_status': '预期状态',
    'expert_result': '专家参考意见', 'false_pass': '错误放行',
    'filing': '报备状态', 'cruise_layer_note': '巡航高度层说明',
    'handling_advice': '处理建议', 'id': '编号', 'is_simulated': '是否模拟输出',
    'item': '项目', 'label_basis': '标注依据', 'layer': '数据层',
    'legacy_case_type': '原案例类型', 'metric_flag': '指标标记',
    'metric_flags': '指标标记', 'metrics_applicable': '指标适用性',
    'nearby_airways': '附近航路', 'origin': '原始来源',
    'original_expected_issues': '原预期问题', 'original_expected_status_text': '原预期状态文本',
    'original_output': '原始输出', 'over_flag': '过度预警',
    'parsed_risk': '提取的风险等级', 'parsed_status': '提取的状态',
    'pending_review': '待复核事项', 'quote': '原文引文',
    'reference_corrections': '参考答案修正', 'req_source': '要件依据来源',
    'review_flags': '复核标记', 'risk_uncertain': '风险是否不确定',
    'risk_underestimate': '风险低估', 'ai_risk_delta': '研判风险偏差',
    'secondary_types': '次要案例类型', 'std_field': '标准字段',
    'strict_by_definition': '严格符合定义', 'target_claim': '关联主张',
    'upload_time': '上传时间', 'why': '核验理由',
    'actor_behavior': '操作者行为', 'actor_intent': '操作者意图',
    'actor_knowledge': '操作者知情状态', 'actor_motive': '操作者动机',
    'alert_source': '预警来源', 'altitude_limit': '高度限制',
    'approval_status': '审批状态', 'battery': '电量',
    'city_level_infrastructure': '城市基础设施信息', 'control_area': '管制区域',
    'control_window': '管制时间窗口', 'discovery_time': '发现时间',
    'flight_summary': '飞行摘要', 'frequency': '频次', 'handler': '处理单位',
    'impact': '影响', 'injury': '人员伤害', 'legal_status': '法律状态',
    'notice_name': '通告名称', 'operator_identity': '操作者身份',
    'penalty': '处罚', 'trace_claim': '轨迹可追溯主张',
    'required_evidence_spec': '必需证据要件规范',
    'decision_gate': '决策门控', 'fields': '字段映射',
    'version': '版本', 'available_fields': '可用字段', 'rule': '规则',
    'request': '补证或核对要求', 'unmapped': '未映射主张',
    'risk_rule_spec': '风险分级规则', 'rule_applicability': '业务规则适用性',
    'claim_dependencies': '主张依赖关系', 'aircraft_id': '航空器标识',
    'altitude_datum': '高度基准', 'altitude_unit': '高度单位',
    'research_policy': '合成研究规则', 'policy_id': '研究规则编号',
    'scope': '适用范围', 'rules': '规则集', 'rule_id': '规则编号', 'all': '全部满足条件',
    'synthetic_mechanism_only': '仅限合成机制验证',
    'AGL': '离地高度', 'AMSL': '平均海平面高度', 'm': '米',
    'rid': '运行识别数据', 'registry': '登记记录', 'radar': '雷达记录',
    'mechanism-envelope-v1': '合成分级规则第一版',
    'low-envelope': '合成低风险条件', 'high-envelope': '合成高风险条件',
    'research:low-envelope': '命中合成低风险条件', 'research:high-envelope': '命中合成高风险条件',
    'USER_UNVERIFIED': '用户资料待核验', 'user_provided': '用户提供',
    'user_transcription': '用户转录', 'user_submission': '用户提交材料',
    'media_unparsed': '媒体未解析', 'text_unverified': '文本未核验',
    'user_unverified': '用户材料未核验', 'intake_notes': '收件说明',
    'intake_id': '收件编号', 'source_note': '来源说明', 'received_at': '收件时间',
    'media_attachments': '媒体附件', 'original_filename': '原文件名',
    'storage_name': '存储文件名', 'sha256': '内容摘要', 'size_bytes': '字节数',
    'mime_type': '媒体类型', 'parsed': '已解析', 'verified': '已核验',
    'processing_status': '处理状态', 'case_sha256': '案例内容摘要',
    'image/png': '便携网络图形图片', 'image/jpeg': '联合图像编码图片',
    'image/webp': '网页图片', 'video/mp4': '数字视频', 'video/webm': '网页视频',
    'text/plain': '纯文本', 'text/markdown': '标记文本', 'application/json': '结构化数据',
}

TEXT_LABELS = {
    'Claim-Level': '逐条主张', 'Claim': '主张', 'AI': '人工智能',
    'RID': '远程识别', 'UOM': '无人驾驶航空器综合管理',
    'NOTAM': '航行通告', 'JSON': '结构化数据',
    'ValueError': '数据校验错误', 'ValidationError': '格式校验错误',
    'RuntimeError': '运行错误', 'TimeoutError': '请求超时',
    'blend': '混合', 'NEEDS_SPEC': '规则规范待确认',
}

LABELS: dict[str, str] = {}
for _table in (FIELD_LABELS, CASE_TYPE_LABELS, EVIDENCE_MODE_LABELS, DECISION_LABELS,
               EVIDENCE_STATUS_LABELS, RISK_LABELS, MODE_LABELS, ISSUE_TYPE_LABELS,
               SOURCE_LABELS, AUDIT_DEPTH_LABELS, RULE_LABELS, TEXT_LABELS):
    LABELS.update(_table)

# 英文 token 边界使用 ASCII 字符，允许“相关值为UNKNOWN或EMPTY”等中文句子。
# 日期、哈希、案例编号和证据编号先保护；不能把 S:… 的字段片段当展示枚举翻译。
_TOKEN_RE = re.compile(
    r'(?<![A-Za-z0-9_])(?:' + '|'.join(re.escape(k) for k in sorted(LABELS, key=len, reverse=True))
    + r')(?![A-Za-z0-9_])'
)
_IDENTIFIER_RE = re.compile(
    r'\bS:[A-Za-z0-9_:.-]+|'
    r'\b(?:CASE|L2B|EV|UAS|UOM|NOTAM)[-:][A-Za-z0-9_:/.-]+|'
    r'\b\d{8}T\d{6}Z-[A-Za-z0-9]+\b|'
    r'\b[0-9a-f]{32,64}\b|'
    r'\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b'
)
_PROTECTED_RE = re.compile(
    _IDENTIFIER_RE.pattern + '|'
    r'https?://[^\s<>]+|[A-Za-z]:[\\/][^\s<>]+|'
    r'\b[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?'
    r'(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?)+'
)
_IDENTITY_FIELDS = {'event_id', 'case_id', 'run_id', 'evidence_id', 'evidence_ids',
                    'claim_id', 'depends_on', 'supporting_evidence', 'contradicting_evidence',
                    'uas_id', 'aircraft_id', 'drone_identity', 'intake_id', 'sha256', 'case_sha256',
                    'id', 'approval_no', 'input_sha256', 'implementation_sha256'}


def translate_report(text: Any) -> str:
    """翻译已登记 token，保留编号、未知原文和 HTML（转义由调用方负责）。"""
    if text is None:
        return '未提供'
    value = str(text)
    parts: list[str] = []
    start = 0
    for match in _PROTECTED_RE.finditer(value):
        parts.append(_TOKEN_RE.sub(lambda item: LABELS[item.group()], value[start:match.start()]))
        path = None if _IDENTIFIER_RE.fullmatch(match.group()) else _translated_path(match.group())
        parts.append(path if path is not None else match.group())
        start = match.end()
    parts.append(_TOKEN_RE.sub(lambda item: LABELS[item.group()], value[start:]))
    return ''.join(parts)


def _translated_path(value: str) -> str | None:
    """只翻译全部已登记的点分字段路径；任一未知片段都保留原路径。"""
    if '.' not in value or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.\[\]-]*', value):
        return None
    translated = []
    for part in value.split('.'):
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)(\[\d+\])?', part)
        if not match or match[1] not in FIELD_LABELS:
            return None
        translated.append(FIELD_LABELS[match[1]] + (match[2] or ''))
    return '.'.join(translated)


def label(value: Any) -> str:
    """已登记枚举的中文标签；未知枚举展示为待登记，编号和原文保留。"""
    if value is None:
        return '未提供'
    if isinstance(value, bool):
        return '是' if value else '否'
    text = str(value)
    if not text:
        return '空值'
    if text in LABELS:
        return LABELS[text]
    path = _translated_path(text)
    if path is not None:
        return path
    if _IDENTIFIER_RE.fullmatch(text):
        return text
    if re.fullmatch(r'[A-Za-z][A-Za-z_]*', text):
        return '未登记类别'
    return translate_report(text)


def _field_label(value: Any) -> str:
    text = str(value)
    if text in FIELD_LABELS:
        return FIELD_LABELS[text]
    if text in LABELS:
        return LABELS[text]
    path = _translated_path(text)
    if path is not None:
        return path
    if re.search(r'[A-Za-z]', text) and not _IDENTIFIER_RE.fullmatch(text):
        return '未登记字段'
    return text


def display_value(value: Any, *, _field: str | None = None) -> Any:
    """返回递归中文展示副本；保留有效数值，布尔值、空值和未知值明确区分。"""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            translated_key = _field_label(key)
            # 未知字段和同义字段也必须保留全部观测，避免翻译键碰撞丢失证据。
            unique_key = translated_key
            count = 2
            while unique_key in result:
                unique_key = f'{translated_key}（{count}）'
                count += 1
            result[unique_key] = display_value(item, _field=str(key))
        return result
    if isinstance(value, (list, tuple)):
        return [display_value(item, _field=_field) for item in value]
    if value is None:
        return '未提供'
    if isinstance(value, bool):
        return '是' if value else '否'
    if not isinstance(value, str):
        return value
    if _field in _IDENTITY_FIELDS:
        return value
    if not value:
        return '空值'
    if value in LABELS:
        return LABELS[value]
    path = _translated_path(value)
    if path is not None:
        return path
    if _field in {'field', 'std_field', 'source', 'source_type', 'confidence',
                  'issue_type', 'evidence_status', 'case_type', 'evidence_mode',
                  'risk_level', 'correct_risk', 'mode', 'metric_source', 'status'}:
        return label(value)
    return translate_report(value)
