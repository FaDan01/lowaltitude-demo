"""从审计结果生成补证和核对建议；不改动输入、标签或门控结论。"""
from collections import OrderedDict

from backend.audit.checks import usable
from backend.evidence import canonical
from backend.models import AuditPackage, AuditResult


_LABELS = {
    'altitude': '高度', 'speed': '速度', 'location': '位置',
    'flight_time': '飞行时间', 'drone_identity': '无人机身份', 'aircraft_id': '航空器标识',
    'registration_status': '登记状态', 'flight_permission': '飞行申请状态',
    'approval_no': '正式批复记录', 'region_type': '区域属性',
    'valid_from': '批复有效期开始', 'valid_to': '批复有效期结束',
    'effective_from': '通告生效时间', 'effective_to': '通告失效时间',
    'flight_trajectory': '飞行轨迹', 'trajectory': '飞行轨迹',
    'notam_window': '航行通告有效期', 'geofence_violation': '电子围栏状态',
    'firmware_status': '固件状态', 'aircraft_class': '航空器类别',
    'target_type': '目标类型', 'payload_evidence': '载荷证据',
    'image_disposition': '图像处置', 'approach_path': '进近航线',
    'flight_schedule_overlap': '航班时间重叠', 'required_evidence_spec': '证据要件规范',
    'risk_rule_spec': '风险分级规则', 'rule_applicability': '业务规则适用性',
    'claim_dependencies': '主张依赖关系', 'unmapped': '未映射主张',
}


def _label(field):
    return _LABELS.get(field, '待确认字段')


def _request(field):
    """只建议与待核验字段有关的原始数据或正式记录。"""
    if field in ('altitude', 'speed', 'location', 'flight_time', 'flight_trajectory', 'trajectory'):
        detail = '；高度记录还需说明单位、高度基准和轨迹峰值计算范围' if field == 'altitude' else ''
        return f'补充同一架无人机、同一事件时段的原始采集记录，保留主体标识、采集时间和数据来源{detail}。'
    if field == 'drone_identity':
        return '补充带主体标识和采集时间的运行识别记录，并与登记或设备记录核对，不用其他无人机记录替代。'
    if field == 'registration_status':
        return '补充主管部门或登记平台的查询记录，核对无人机标识与查询时间；未查询到信息不能直接标为未登记。'
    if field == 'flight_permission':
        return '补充同一主体、本次飞行的正式申请记录；如候选声称获批，还需另核正式批复，区分申请、备案与获批。'
    if field in ('approval_no', 'valid_from', 'valid_to'):
        return '补充同一主体、本次飞行的正式批复，核对批复编号、批准空域范围和有效期；申请回执或备案记录不能替代获批证明。'
    if field in ('region_type', 'notam_window', 'effective_from', 'effective_to'):
        return '补充适用于事件位置和时间的官方空域公告或航行通告，保留水平范围、垂直范围、有效期和发布来源。'
    if field in ('approach_path', 'flight_schedule_overlap'):
        return '补充对应机场、事件时段的正式航线或航班记录，并与同一无人机的原始轨迹核对。'
    if field == 'firmware_status':
        return '补充该设备的厂商版本、维修或变更记录，核对设备标识和记录时间；不从高度异常直接推断固件被修改。'
    if field == 'geofence_violation':
        return '补充事件时有效的电子围栏配置和同一无人机的原始轨迹，核对边界、坐标口径与采集时间。'
    if field == 'aircraft_class':
        return '补充该机型的厂商技术资料或正式登记记录，核对机型、重量及分类适用条件。'
    if field in ('payload_evidence', 'target_type', 'image_disposition'):
        return '补充与本次事件关联的原始图像、设备日志或正式核查记录，保留时间和主体标识；不从文字猜测未记录的内容。'
    return '先确认该字段的定义及可接受来源，再补充与本次事件关联的原始采集数据或正式记录；不得凭候选输出推填观测值。'


def build_remediation(package: AuditPackage, audit: AuditResult) -> list[dict]:
    """返回按字段去重的中文建议；补证后仍需重新审计，不承诺放行。

    仅处理审计涉及的字段，不把所有可选的未知事件字段列为补证任务。
    evidence_ids 始终指向输入中实际存在的证据，规则缺失列为规则确认。
    """
    evidence = {row.evidence_id: row for row in package.evidence}
    groups = {}
    for row in package.evidence:
        groups.setdefault(canonical(row.field), []).append(row)
    requests = OrderedDict()

    def add(field, reason, request, ids=(), priority=0):
        field = canonical(field)
        valid_ids = list(dict.fromkeys(identity for identity in ids if identity in evidence))
        if field not in requests:
            requests[field] = {'field': field, 'reason': reason, 'request': request,
                               'evidence_ids': valid_ids, '_priority': priority}
            return
        current = requests[field]
        if reason not in current['reason']:
            current['reason'] += '；' + reason
        current['evidence_ids'] = list(dict.fromkeys(current['evidence_ids'] + valid_ids))
        if priority > current['_priority']:
            current['request'], current['_priority'] = request, priority
        elif priority == current['_priority'] and request not in current['request']:
            current['request'] += ' ' + request

    missing = list(audit.missing_required)
    # 保留字段别名与未知/空值；零和否定观测都是有效值。
    missing.extend(field for field in package.required_evidence
                   if not any(usable(row.value) for row in groups.get(canonical(field), [])))
    for field in dict.fromkeys(canonical(name) for name in missing):
        if field == 'required_evidence_spec':
            add(field, '缺少经确认的证据要件规范',
                '请业务负责人确认本类任务的必需字段、可接受来源和适用范围，再版本化登记；不以参考答案代替规范。')
        else:
            add(field, f'{_label(field)}缺失、未采集或为空', _request(field),
                [row.evidence_id for row in groups.get(field, [])])

    by_claim = {claim.claim_id: claim for claim in audit.claims}
    for claim in audit.claims:
        field = canonical(claim.field)
        rows = groups.get(field, [])
        if field == 'unmapped':
            add(field, '原文主张尚未映射到可核验字段',
                '核对未映射的原文主张，确认事实、推理或结论类别并完成字段映射；先检查现有证据，再决定是否需要新增采集。')
            continue
        if claim.evidence_status == 'CONTRADICTED':
            add(field, f'{_label(field)}主张存在字段级反证',
                '先逐项核对所列原始证据与候选主张，按已核验记录修正主张；若记录本身可疑，再核查采集时间、主体标识和数据口径。',
                claim.supporting_evidence + claim.contradicting_evidence, priority=2)
        if claim.claim_type != 'fact' and (
            not claim.depends_on or any(identity not in by_claim for identity in claim.depends_on)
        ):
            add('claim_dependencies', '推理或结论的依赖关系不完整',
                '补全原文实际存在的事实主张及依赖关系；若原文未提供推理依据，应保留不确定性并由人工复核，不得补造事实。')
        needs_rule = any(marker in claim.reason for marker in
                         ('NEEDS_SPEC', '规则适用', '业务推理', '规则未实现', '风险分级规则'))
        risk_unverified = field in ('risk_level', 'overall_assessment') and claim.evidence_status != 'SUPPORTED'
        if needs_rule or risk_unverified:
            rule_field = 'risk_rule_spec' if field in ('risk_level', 'overall_assessment') else 'rule_applicability'
            add(rule_field, '结论所需的业务规则或适用条件尚未确认',
                '请业务负责人确认分级条件、适用范围、阈值和规则版本，并复核结论；补齐字段不能替代规则确认，不从参考风险标签生成证据。')
            continue
        if claim.evidence_status in ('UNKNOWN', 'INSUFFICIENT'):
            if '批复记录' in claim.reason and field == 'flight_permission':
                add('approval_no', '申请记录不能证明本次飞行已获批准', _request('approval_no'),
                    [row.evidence_id for row in rows])
            elif field not in ('risk_level', 'overall_assessment'):
                if any(usable(row.value) for row in rows):
                    add(field, f'{_label(field)}已有记录，但主张尚不能可靠比对',
                        '先核对主张的字段映射、比较关系、值域和单位；对照现有原始记录重新核验，只有记录不足时才补充新的数据。',
                        [row.evidence_id for row in rows], priority=1)
                else:
                    add(field, f'{_label(field)}主张尚无有效证据支持', _request(field),
                        [row.evidence_id for row in rows])

    for issue in audit.issues:
        rows = [evidence[identity] for identity in issue.evidence_ids if identity in evidence]
        fields = list(dict.fromkeys(canonical(row.field) for row in rows))
        if issue.issue_type == 'EVIDENCE_CONFLICT' and '证据航空器标识与事件主体不一致' in issue.reason:
            add('aircraft_id', '现有证据的航空器标识与本次事件主体不一致',
                '核对本次事件的航空器标识及各来源绑定的设备，按同一主体重新组织证据；分别保留其他主体的记录，不将不同无人机的数据合并为一次飞行。',
                issue.evidence_ids, priority=3)
        elif issue.issue_type == 'EVIDENCE_CONFLICT':
            for field in fields:
                # 列出同一字段全部现有证据，避免只看其中一个方向。
                add(field, f'{_label(field)}的独立来源存在冲突',
                    '核对所列各来源的主体标识、采集时间、单位和测量口径；保留冲突记录，必要时向原始来源复核，不擅自挑选有利数值。',
                    [row.evidence_id for row in groups[field]], priority=3)
        elif issue.issue_type == 'OMISSION':
            for field in fields:
                add(field, f'候选输出遗漏已提供的{_label(field)}证据',
                    '将所列现有证据纳入候选主张与依赖关系，再重新审计；无需为已有记录重复采集。',
                    [row.evidence_id for row in groups[field]], priority=1)
        elif issue.issue_type == 'TIMELINESS_ERROR':
            add('flight_permission', '现有批复不能覆盖实际事件时间',
                '核对事件时间与批复起止时间，补充覆盖本次飞行的正式有效记录；不能把过期批复推填为有效。',
                issue.evidence_ids, priority=2)
        elif issue.issue_type == 'INSUFFICIENT_EVIDENCE' and any(
            marker in issue.reason for marker in ('高度基准不一致', '高度单位未统一')
        ):
            height_ids = [row.evidence_id for row in rows
                          if canonical(row.field) in ('altitude', 'altitude_datum', 'altitude_unit')]
            add('altitude', '高度记录的测量基准或单位尚未统一，当前数值不能直接比较',
                '核对所列原始高度记录的单位和测量基准；如需换算，应提供经核验的单位换算或基准转换依据，并保留原值及转换过程；口径未确认前不比较峰值或限高。',
                height_ids, priority=4)
        elif issue.issue_type == 'INSUFFICIENT_EVIDENCE' and any(
            marker in issue.reason for marker in ('缺少明确可执行的风险规则', '合成机制规则缺少策略编号',
                '合成机制规则格式不完整', '合成机制规则存在无效', '合成机制规则存在不能',
                '合成机制规则未覆盖', '多个合成机制规则匹配不同风险等级')
        ):
            add('risk_rule_spec', '风险结论缺少明确可执行的规则或规则定义尚有歧义',
                '请业务负责人确认分级条件、适用范围、阈值和规则版本，并复核结论；补齐字段不能替代规则确认，不从参考风险标签生成证据。',
                issue.evidence_ids)
        elif issue.issue_type == 'INSUFFICIENT_EVIDENCE' and '时间格式/时区' in issue.reason:
            add('flight_time', '事件或批复时间的格式及时间口径无法比较',
                '核对原始事件时间与批复起止时间，明确时区及时间格式后再比对；保留原始时间值，不推填缺失日期。',
                [row.evidence_id for row in package.evidence
                 if canonical(row.field) in ('flight_time', 'valid_from', 'valid_to')])
        elif issue.issue_type == 'EXCEEDS_AUTHORITY':
            add('rule_applicability', '候选建议涉及超出当前系统权限的处置',
                '由有权限的人员核对处置程序并修正候选建议，保留人工复核记录；新增证据本身不会赋予系统处置权限。', priority=3)

    # 来源不足单列到对应要件，而不是生成没有字段的泛化“多找资料”。
    for field in dict.fromkeys(canonical(name) for name in package.required_evidence):
        rows = groups.get(field, [])
        if any(usable(row.value) for row in rows) and not any(
            usable(row.value) and row.source_type in ('sensor', 'official_record', 'constructed')
            and row.confidence == 'high' for row in rows
        ):
            add(field, f'{_label(field)}的现有来源等级不足', _request(field),
                [row.evidence_id for row in rows], priority=2)

    return [{key: value for key, value in row.items() if key != '_priority'} for row in requests.values()]
