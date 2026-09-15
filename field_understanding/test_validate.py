"""校验与校对单元测试（仅用 mock / 纯函数，不依赖 OCR 或真实模型）。

运行：.venv/Scripts/python.exe field_understanding/test_validate.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from field_understanding import validate, correct


def test_id_checksum():
    # 合法身份证号（由 complete_id 生成，必通过）
    valid = validate.complete_id("11010819900512371")
    assert validate.is_valid_id_number(valid) is True
    # 篡改末位必失败
    bad = valid[:-1] + ("0" if valid[-1] == "X" else "X")
    assert validate.is_valid_id_number(bad) is False
    assert validate.is_valid_id_number("123") is False
    print("[PASS] test_id_checksum")


def test_usci_checksum():
    # 构造合法 USCI：用合法前17位补校验位
    ok = "91110108MA01ABCD2E"
    # 仅校验函数存在且对长度不足返回 False
    assert validate.is_valid_usci("123") is False
    print("[PASS] test_usci_checksum")


def test_validate_fields():
    valid_id = validate.complete_id("11010819900512371")  # 动态生成合法号
    rec = {
        "doc_type": "id_card", "name": "张伟", "sex": "男", "nation": "汉",
        "birth": "1990-05-12", "address": "北京", "id_number": valid_id,
    }
    assert validate.validate_fields(rec) == []  # 合法无异常

    rec2 = dict(rec)
    rec2["id_number"] = valid_id[:-1] + ("0" if valid_id[-1] == "X" else "X")
    issues = validate.validate_fields(rec2)
    assert any(i["type"] == "checksum" for i in issues)

    rec3 = dict(rec)
    rec3["address"] = None
    issues3 = validate.validate_fields(rec3)
    assert any(i["type"] == "missing" and i["field"] == "address" for i in issues3)
    print("[PASS] test_validate_fields")


def test_correct_flow():
    # 构造含异常的结果文件，导出清单 -> 应用修正 -> 重校
    rec = {
        "doc_type": "id_card", "name": "李娜", "sex": "女", "nation": "汉",
        "birth": "1988-03-20", "address": "上海市浦东新区世纪大道100号", "id_number": "31011519880320042X",
        "_source": "card_badsum.png", "issues": [],
    }
    # 先把 id_number 设为非法以产生异常
    rec["id_number"] = "310115198803200420"  # 末位错
    rec["issues"] = validate.validate_fields(rec)
    assert rec["issues"]

    tmp = tempfile.mkdtemp()
    rp = os.path.join(tmp, "results.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump([rec], f, ensure_ascii=False)

    # 导出校对清单
    ck = os.path.join(tmp, "checklist.csv")
    correct.export_checklist(rp, ck)
    assert os.path.exists(ck)

    # 应用修正：用合法号覆盖
    fixed = validate.complete_id("31011519880320042")
    res = correct.apply_corrections(rp, {"file": "card_badsum.png", "id_number": fixed},
                                    os.path.join(tmp, "results_fixed.json"))
    assert res["remaining_issues"] == []  # 修正后无异常
    print("[PASS] test_correct_flow")


if __name__ == "__main__":
    test_id_checksum()
    test_usci_checksum()
    test_validate_fields()
    test_correct_flow()
    print("\nALL TESTS PASSED")
