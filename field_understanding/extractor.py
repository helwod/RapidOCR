"""混合编排：OCR -> 规则层 -> LLM 补全 -> 合并结构化结果。

规则层确定性字段优先；LLM 仅补全规则缺失项，且端点不可用或 disabled 时自动跳过。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import id_rules
from .llm_client import LLMClient

SCHEMA_HINT = {
    "id_card": "name,sex,nation,birth,address,id_number",
    "biz_license": "name,type,legal_person,capital,establish_date,usci,address,scope",
}


def run(
    texts: List[str],
    boxes=None,
    doc_type: str = "auto",
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    rule_out = id_rules.extract_document(texts, boxes, doc_type)

    # 统计缺失字段
    missing = [k for k, v in rule_out.items() if v in (None, "") and k != "doc_type"]
    if missing and llm is not None and llm.enabled:
        ocr_text = "\n".join(texts)
        hint = SCHEMA_HINT.get(rule_out["doc_type"], ",".join(missing))
        llm_out = llm.extract(ocr_text, hint, rule_out)
        for k in missing:
            if k in llm_out and llm_out[k]:
                rule_out[k] = llm_out[k]

    # 元信息：填充率
    filled = sum(1 for k, v in rule_out.items() if v not in (None, "") and k != "doc_type")
    total = sum(1 for k in rule_out if k != "doc_type")
    rule_out["_fill_rate"] = f"{filled}/{total}"
    return rule_out
