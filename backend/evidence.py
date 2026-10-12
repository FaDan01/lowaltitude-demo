"""从原始字段派生证据与事件；不读标准答案，供Pipeline及确定性审计使用。"""
from collections import defaultdict
from backend.models import AuditPackage, Evidence
from backend.paths import read_rules


def canonical(field):
    """只按外置别名映射同义字段；未知字段原样保留。"""
    for standard, aliases in read_rules('fields')['aliases'].items():
        if field in aliases:
            return standard
    return field


def evidence_value(value):
    """区分空值EMPTY和未采集UNKNOWN，绝不转为False或0。"""
    if value is None or value == '':
        return 'EMPTY'
    return value


def project_case(case, existing=False):
    """白名单投影：事实风险、预期审计、案例类型及标题均不进入运行包。"""
    required = case.get('required_evidence') or case['ground_truth'].get('required_evidence', [])
    names = [r if isinstance(r, str) else r.get('field', r.get('item', r.get('name', 'UNKNOWN')))
             for r in required]
    constructed = case['ground_truth_source'] == 'constructed'
    evidence = []
    raw = case['raw_evidence']
    sources = raw.get('sources', {}) if isinstance(raw, dict) else {}
    for source, obj in sources.items():
        rows = obj if isinstance(obj, list) else [obj]
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            prefix = f'raw_evidence.sources.{source}' + (f'[{index}]' if isinstance(obj, list) else '')
            for field, value in row.items():
                if field in ('note', 'detail', 'source_type', 'seq'):
                    continue
                raw_field = field
                if field == 'value' or field == 'status':
                    field = {'airspace_query': 'region_type', 'permission_query': 'flight_permission',
                             'payload_query': 'payload_evidence'}.get(source, source)
                evidence.append(Evidence(evidence_id=f'S:{source}:{index}:{field}', field=canonical(field),
                    value=evidence_value(value), source=source,
                    source_type='constructed' if constructed else 'unknown',
                    confidence='high' if constructed else 'unknown', path=f'{prefix}.{raw_field}',
                    timestamp=row.get('ts'), constructed=constructed))
        if source in ('notam', 'rid_trajectory'):
            evidence.append(Evidence(evidence_id=f'S:{source}', field=canonical(source), value=obj,
                source=source, source_type='constructed' if constructed else 'unknown',
                confidence='high' if constructed else 'unknown', path=f'raw_evidence.sources.{source}',
                constructed=constructed))
    # 保留公开引文索引；结构化sources已覆盖的索引不重复引入，避免聚合值冒充独立传感器。
    if not sources:
        for item in case.get('evidence_index', []):
            evidence.append(Evidence(evidence_id=item['evidence_id'], field=canonical(item.get('std_field') or item['field']),
                value=evidence_value(item.get('value')), source=item['source'],
                source_type=item.get('source_type', 'unknown'), confidence=item.get('confidence', 'unknown'),
                path=f"evidence_index.{item['evidence_id']}", timestamp=item.get('timestamp'),
                constructed=constructed))
    grouped = group_evidence(evidence)
    event = {field: 'UNKNOWN' for field in read_rules('fields')['event_fields']}
    event['event_id'] = case['case_id']
    event['text_records'] = raw.get('narrative', '') if isinstance(raw, dict) else raw
    for field in event:
        found = grouped.get(canonical(field))
        if found:
            event[field] = found[-1].value
    times = grouped.get('flight_time', [])
    # 未提供事件时间时不从标题、case_id或专家答案发明时间。
    explicit_time = case['context'].get('event_time') if isinstance(case['context'], dict) else None
    event['event_time'] = explicit_time if explicit_time else (times[0].value if times else 'UNKNOWN')
    if 'altitude' in grouped:
        numeric = [e.value for e in grouped['altitude'] if type(e.value) in (int, float)]
        event['altitude'] = max(numeric) if numeric else 'UNKNOWN'
    event['trajectory'] = sources.get('rid_trajectory', 'UNKNOWN')
    return AuditPackage(case_id=case['case_id'], raw_evidence=raw, context=case['context'],
        required_evidence=names, evidence=evidence, event=event,
        missing_fields=[k for k, v in event.items() if v == 'UNKNOWN'],
        empty_fields=[k for k, v in event.items() if v == 'EMPTY'],
        existing_ai_output=case['ai_output']['original_output'] if existing else None,
        is_constructed=constructed)


def group_evidence(evidence):
    """按标准字段索引证据，保留每个独立来源。"""
    grouped = defaultdict(list)
    for item in evidence:
        grouped[item.field].append(item)
    return grouped


def require_event_identity(package):
    """严格拒绝最小标识缺失，其他内容字段缺失留给审计。"""
    if not package.case_id or package.event['event_time'] in ('UNKNOWN', 'EMPTY', None, ''):
        raise ValueError('event_id/event_time缺失：需要显式事件时间，不推断或填充')
