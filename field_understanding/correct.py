"""异常校对（人工修正）：导出校对清单、应用修正、回写结果。

流程：validate -> 导出 issues 为校对清单(csv/json) -> 人工填写修正值 ->
apply_corrections 合并回 results，重新校验直至无 high 级异常。
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List

from .validate import validate_fields


def export_checklist(results_path: str, out_path: str) -> str:
    """从 results.json 导出校对清单（仅含异常项），供人工填写 correct 列。"""
    with open(results_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    rows = []
    for r in records:
        for i in r.get("issues", []):
            rows.append({
                "file": r.get("_source", ""),
                "field": i["field"],
                "severity": i["severity"],
                "type": i["type"],
                "msg": i["msg"],
                "suggest": i.get("suggest") or "",
                "correct": "",  # 人工填写
            })
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "field", "severity", "type", "msg", "suggest", "correct"])
        w.writeheader()
        w.writerows(rows)
    return out_path


def apply_corrections(results_path: str, corrections: Dict[str, str], out_path: str) -> Dict[str, Any]:
    """将 {field: value} 修正应用到某条记录的字段上，并重新校验。

    corrections 键为字段名；'file' 用于定位（可选，单条时忽略）。
    返回更新后的 record 与剩余 issues。
    """
    with open(results_path, "r", encoding="utf-8") as f:
        records = json.load(f)
    target = None
    for r in records:
        if r.get("_source") == corrections.get("file") or len(records) == 1:
            target = r
            break
    if target is None:
        target = records[0]
    for k, v in corrections.items():
        if k in ("file",):
            continue
        if v not in (None, ""):
            target[k] = v
    target["issues"] = validate_fields(target)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return {"record": target, "remaining_issues": target["issues"]}
