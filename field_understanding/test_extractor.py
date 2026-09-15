"""字段抽取单元测试（仅用 mock，不依赖 OCR/真实模型）。

运行：.venv/Scripts/python.exe field_understanding/test_extractor.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from field_understanding import run, validate
from field_understanding.llm_client import LLMClient


class FakeLLM(LLMClient):
    """mock：enabled=True 但用本地规则数据模拟 LLM 返回，验证合并逻辑。"""

    def __init__(self, fill: dict):
        super().__init__(enabled=True)
        self.enabled = True  # mock 强制开启，绕过 base_url 检查
        self._fill = fill

    def extract(self, ocr_text, schema_hint, existing):
        # 只返回缺失字段的值
        return {k: v for k, v in self._fill.items() if existing.get(k) in (None, "")}


def test_id_card_rule():
    texts = [
        "居民身份证",
        "姓名张伟",
        "性别男民族汉",
        "出生1990年5月12日",
        "住址北京市海淀区中关村南大街5号院3号楼",
        "公民身份号码11010819900512371X",
    ]
    out = run(texts, boxes=None, doc_type="id_card", llm=None)
    assert out["doc_type"] == "id_card"
    assert out["name"] == "张伟"
    assert out["sex"] == "男"
    assert out["nation"] == "汉"
    assert out["birth"] == "1990-05-12"
    assert out["id_number"] == "11010819900512371X"
    assert out["address"] == "北京市海淀区中关村南大街5号院3号楼"
    assert out["_fill_rate"] == "6/6"
    print("[PASS] test_id_card_rule")


def test_biz_license_rule():
    texts = [
        "营业执照",
        "名称 北京示例科技有限公司",
        "类型 有限责任公司",
        "法定代表人 李娜",
        "注册资本 1000万元",
        "成立日期 2018年3月20日",
        "统一社会信用代码 91110108MA01ABCD2E",
        "住所 北京市朝阳区建国路88号",
        "经营范围 技术开发、技术咨询。",
    ]
    out = run(texts, boxes=None, doc_type="biz_license", llm=None)
    assert out["doc_type"] == "biz_license"
    assert out["usci"] == "91110108MA01ABCD2E"
    assert out["name"] == "北京示例科技有限公司"
    assert out["legal_person"] == "李娜"
    assert out["establish_date"] == "2018年3月20日"
    print("[PASS] test_biz_license_rule")


def test_hybrid_merge():
    # 规则漏掉 name，由 LLM（mock）补全
    texts = ["性别男民族汉", "公民身份号码11010819900512371X", "出生1990年5月12日"]
    llm = FakeLLM(fill={"name": "张伟", "address": "北京市海淀区"})
    out = run(texts, boxes=None, doc_type="id_card", llm=llm)
    assert out["name"] == "张伟"           # 规则缺失 -> LLM 补全
    assert out["id_number"] == "11010819900512371X"  # 规则命中，不被覆盖
    assert out["address"] == "北京市海淀区"
    print("[PASS] test_hybrid_merge")


def test_llm_disabled_fallback():
    llm = LLMClient(enabled=False)  # 离线默认：不调用
    texts = ["姓名王芳", "公民身份号码320583199003071234"]
    out = run(texts, boxes=None, doc_type="id_card", llm=llm)
    assert out["name"] == "王芳"
    assert out["id_number"] == "320583199003071234"
    print("[PASS] test_llm_disabled_fallback")


def test_id_card_name_not_gender():
    """回归：OCR 把“姓名”与“性别”粘连时，绝不能把性别/标签误当姓名。

    场景1：token「姓名男」——姓名标签直接粘到性别值，旧逻辑会得出 name='男'。
    场景2：下一 token 是「性别男民族汉」——旧逻辑回退到 texts[i+1]，同样误判。
    修复后 name 应为 None（留待 LLM/人工补全），且 sex 仍正确抽取。
    """
    texts = [
        "居民身份证",
        "姓名男",                 # 姓名标签粘连到性别值
        "性别男民族汉",           # 回退候选 token 也非姓名
        "出生1990年5月12日",
        "住址北京市海淀区中关村南大街5号院3号楼",
        "公民身份号码11010819900512371X",
    ]
    out = run(texts, boxes=None, doc_type="id_card", llm=None)
    assert out["name"] is None, f"性别不应被误识别为姓名，实际得到 {out['name']!r}"
    assert out["sex"] == "男"                       # 性别仍应正确
    assert out["id_number"] == "11010819900512371X"
    # 附带：姓名与后续字段粘连时，应能截取前方真实姓名
    glued = ["居民身份证", "姓名张伟性别男民族汉", "出生1990年5月12日",
             "住址北京市海淀区", "公民身份号码11010819900512371X"]
    out2 = run(glued, boxes=None, doc_type="id_card", llm=None)
    assert out2["name"] == "张伟", f"粘连姓名应截出张伟，实际得到 {out2['name']!r}"
    print("[PASS] test_id_card_name_not_gender")


def test_validate_name_as_gender():
    """回归：姓名被识别成性别/标签时，校验层必须触发「识别异常」。"""
    rec = {"doc_type": "id_card", "name": "性别男", "sex": "男", "nation": "汉",
           "birth": "1976-03-20", "address": "湖南省邵阳县", "id_number": "430523197603204314"}
    issues = validate.validate_fields(rec)
    name_issues = [i for i in issues if i["field"] == "name"]
    assert name_issues, "姓名被识别成性别应触发识别异常"
    assert any("性别" in i["msg"] for i in name_issues)
    # 正常姓名不误报
    ok = validate.validate_fields(dict(rec, name="蒋飞成"))
    assert not [i for i in ok if i["field"] == "name"], "正常姓名不应报姓名异常"
    # 标签当姓名也应触发
    label = validate.validate_fields(dict(rec, name="联系电话"))
    assert [i for i in label if i["field"] == "name"], "标签被当姓名应触发识别异常"
    print("[PASS] test_validate_name_as_gender")


if __name__ == "__main__":
    test_id_card_rule()
    test_biz_license_rule()
    test_hybrid_merge()
    test_llm_disabled_fallback()
    test_id_card_name_not_gender()
    test_validate_name_as_gender()
    print("\nALL TESTS PASSED")
