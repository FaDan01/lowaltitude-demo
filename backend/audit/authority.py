"""有限中文处置语境兜底；不把关键词命中冒充通用语义或权限判定。"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorityFinding:
    decision: str
    start: int
    end: int
    text: str
    reason: str

    @property
    def trace(self):
        return f'原文字符[{self.start}:{self.end}]“{self.text}”：{self.reason}'


def _compact(text):
    """仅移除空白，位置映射仍指向原文；不翻译、改词或解码隐藏指令。"""
    positions = [index for index, char in enumerate(text) if not char.isspace()]
    return ''.join(text[index] for index in positions), positions


def _quotes(text):
    """识别成对引号的位置；引号本身不能证明是在转述历史。"""
    pairs = {'“': '”', '‘': '’', '「': '」', '『': '』', '"': '"', "'": "'"}
    stack, spans = [], []
    for index, char in enumerate(text):
        if stack and char == stack[-1][1]:
            opening, _, _ = stack.pop()
            spans.append((opening, index + 1))
        elif char in pairs:
            stack.append((index, pairs[char], char))
    return spans


def inspect_authority(text, gate_rules):
    """返回处置词的有限语境判定和原文范围；歧义必须保留人工核对。

    明确拟定/建议处罚及直接犯罪定性可阻断，明确历史引述和单层否定不
    标为越权。条件、双重否定、裸关键词及不能可靠关联的语境转人工。
    不证明否定/引述的内容为真，也不核定真实主体是否具有执法权限。
    """
    if not text:
        return []
    policy = gate_rules.get('authority_text')
    if not policy:
        # 旧版本外置规则仍可使用，其有限匹配方式明确留在追溯中。
        return [AuthorityFinding('BLOCK', match.start(), match.end(), match.group(),
                '旧版本关键词正则命中；未区分历史、否定或处置语境')
                for pattern in gate_rules.get('authority_patterns', [])
                for match in re.finditer(pattern, text)]
    patterns = {name: re.compile(value) for name, value in policy['patterns'].items()}
    compact, positions = _compact(text)
    quote_spans = _quotes(compact)
    findings = []
    window = policy['context_window_chars']
    for match in patterns['term'].finditer(compact):
        start, end = match.span()
        left_start = max(0, start - window)
        for boundary in patterns['sentence_boundary'].finditer(compact, left_start, start):
            left_start = boundary.end()
        right_end = min(len(compact), end + window)
        boundary = patterns['sentence_boundary'].search(compact, end, right_end)
        if boundary:
            right_end = boundary.start()
        left, right = compact[left_start:start], compact[end:right_end]
        local_start = 0
        for reset in patterns['scope_reset'].finditer(left):
            local_start = reset.end()
        local = left[local_start:]
        enclosing = next(((opening, closing) for opening, closing in quote_spans
                          if opening < start and end < closing), None)
        quote_prefix = compact[left_start:enclosing[0]] if enclosing else ''
        prefix_local = patterns['scope_reset'].split(quote_prefix)[-1]
        quoted_recommendation = bool(enclosing and patterns['recommendation'].search(prefix_local)
            and not patterns['negation'].search(prefix_local))
        double_negative = patterns['double_negative'].search(local)
        suffix = right.lstrip('”’」』"\'')
        ambiguous = patterns['ambiguity'].search(local) or patterns['uncertain_suffix'].match(suffix)
        negated = patterns['negation'].search(local)
        # 无推荐语境的安全/界面警告属于普通提示，不是行政警告决定。
        warning_only = (match.group() == '警告' and patterns['technical_warning'].search(local))
        quoted_report = bool(enclosing and patterns['reported_quote'].search(quote_prefix))
        historical = patterns['historical'].search(local)
        reported = patterns['reported_quote'].search(left)
        recommended = patterns['recommendation'].search(local)
        directive = patterns['directive'].search(local)
        if double_negative:
            decision, reason = 'MANUAL_REVIEW', '双重否定的处置语义未可靠解析，需核对权限与原文'
        elif ambiguous and not quoted_recommendation:
            decision, reason = 'MANUAL_REVIEW', '条件、可能性或待核查处置语义，未确认越权也不能自动采用'
        elif negated:
            decision, reason = 'CONTEXT_ONLY', '明确否定处置/定性；不以被否定的关键词认定越权'
        elif warning_only:
            decision, reason = 'CONTEXT_ONLY', '明确系统或设备提示，未识别为行政处置警告'
        elif quoted_recommendation:
            decision, reason = 'BLOCK', '候选明确建议引用的处置；引号包装不解除权限门控'
        elif quoted_report:
            decision, reason = 'CONTEXT_ONLY', '明确报道/原文引述；不把引述内容当候选新处置建议'
        elif historical:
            decision, reason = 'CONTEXT_ONLY', '明确既有处置的历史叙述；不当作候选新处置建议'
        elif reported:
            decision, reason = 'MANUAL_REVIEW', '报道和处置建议语境混合，不能确定建议归属'
        elif recommended or directive or match.group() in ('判处', '构成犯罪'):
            decision, reason = 'BLOCK', '候选明确拟定/建议处罚、立案或犯罪定性，阻断普通采用'
        else:
            decision, reason = 'MANUAL_REVIEW', '含处置关键词但主体、语境或权限不明确，需人工核对'
        original_start, original_end = positions[start], positions[end - 1] + 1
        findings.append(AuthorityFinding(decision, original_start, original_end,
                                         text[original_start:original_end], reason))
    return findings
