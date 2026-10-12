"""统一定位仓库与规则目录；输入环境变量，输出路径，供全部模块调用。"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_rules(name):
    """读取唯一规则目录中的版本化JSON。"""
    folder = Path(os.getenv("LOWALTITUDE_RULES_DIR", str(ROOT / "rules")))
    value = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    if not value.get("version"):
        raise ValueError(f"规则缺少version: {name}")
    return value


def save_json(path, value):
    """保存UTF-8派生JSON，不涉及原始数据。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
