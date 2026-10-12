"""核对显式证据主体与高度口径；缺少元信息时不编造来源身份。"""
from backend.models import Issue
from backend.evidence import canonical


def evidence_context_issues(package):
    """读sources的显式元信息，防止不同主体或高度基准混成同一证据包。"""
    raw = package.raw_evidence
    if not isinstance(raw, dict):
        return []
    sources = raw.get('sources', {})
    if not isinstance(sources, dict):
        return []
    aircraft = {}
    altitude_sources = {}
    issues = []
    identity_names = ('aircraft_id', 'uas_id', 'drone_identity')
    identity_values = lambda row: [str(row[name]) for name in identity_names
                                  if row.get(name) not in (None, '', 'UNKNOWN', 'EMPTY')]
    context_ids = identity_values(package.context) if isinstance(package.context, dict) else []
    for source, value in sources.items():
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                continue
            for identity in identity_values(row):
                aircraft.setdefault(identity, set()).add(source)
            if any(canonical(name) == 'altitude' for name in row):
                datum, unit = row.get('altitude_datum'), row.get('altitude_unit')
                altitude_sources.setdefault(source, []).append((datum, unit))
    relevant = lambda names: [e.evidence_id for e in package.evidence if e.source in names]
    if len(aircraft) > 1 or len(set(context_ids)) > 1 or (context_ids and any(identity not in context_ids for identity in aircraft)):
        names = set().union(*aircraft.values()) if aircraft else set()
        issues.append(Issue(issue_type='EVIDENCE_CONFLICT', reason='证据航空器标识与事件主体不一致，不能合并为同一次飞行',
                            evidence_ids=relevant(names)))
    datums = {datum for rows in altitude_sources.values() for datum, _ in rows
              if datum not in (None, '', 'UNKNOWN', 'EMPTY')}
    if len(datums) > 1:
        issues.append(Issue(issue_type='INSUFFICIENT_EVIDENCE',
            reason='高度基准不一致；真高、海拔高度等数值不能直接混合比较，需统一基准及转换依据',
            evidence_ids=relevant(altitude_sources)))
    for source, rows in altitude_sources.items():
        if any(unit not in (None, '', 'UNKNOWN', 'EMPTY', 'm', '米') for _, unit in rows):
            issues.append(Issue(issue_type='INSUFFICIENT_EVIDENCE',
                reason='高度单位未统一为米，尚无经核验的换算依据', evidence_ids=relevant([source])))
    return issues
