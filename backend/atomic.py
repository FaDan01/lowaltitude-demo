"""有限的中文主张边界检查；保留原文，不用正则补造未知事实。"""
import re


_ASSERTIONS = {
    'registration_status': r'(?:实名)?登记',
    'altitude': r'高度|真高|海拔|距地|高达\s*[0-9０-９]+\s*米',
    'region_type': r'适飞空域|管控区域|管制空域',
    'flight_permission': r'飞行申请|已报备|提出申请',
    'approval_no': r'获批|已批准|取得批准|获得批复',
    'risk_level': r'风险(?:等级)?[：:为\s]*(?:LOW|MEDIUM|HIGH|CRITICAL|低|中|高|极高)',
    'overall_assessment': r'无(?:安全)?风险|安全无虞|不构成违规|未发现违规|正常放行',
}


def assertion_fields(text):
    """只识别显式关键词，用于防止一个字段覆盖整段复合判断。"""
    return {field for field, pattern in _ASSERTIONS.items() if re.search(pattern, text)}


def split_clauses(text):
    """拆分标点及明确连接词；每个返回值仍是输入的连续子串。"""
    parts = re.split(r'[。；;\n，,]|(?:而且|并且|且|并|但|同时)(?=(?:已|未|没有|最高|飞行|真高|高度|无|风险|该))', text)
    return [part.strip() for part in parts if part.strip()]
