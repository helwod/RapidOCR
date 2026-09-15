"""异常校对：字段校验、身份证/统一社会信用代码校验位、跨字段一致性。

返回 issue 列表，每条含 field / severity / type / msg / suggest，
供可视化、批量报告与人工校对消费。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# 身份证（GB 11643-1999）校验
_ID_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CHECK = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]

# 统一社会信用代码（GB 32100-2015）校验
_USCI_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCI_WEIGHTS = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28]


def _normalize_id_number(s: str) -> str:
    """规范化身份证号：全角字符转半角、乘号/全角X/罗马数字Ⅹ 统一为 X、去空格。"""
    if not s:
        return s
    out = []
    for ch in s:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        out.append(ch)
    s = "".join(out)
    s = s.replace("×", "X").replace("Ｘ", "X").replace("ｘ", "x")
    s = s.replace("Ⅹ", "X").replace("ⅹ", "x")
    return s.replace(" ", "").replace("\u3000", "")


def is_valid_id_number(id_number: str) -> bool:
    if not id_number:
        return False
    id_number = _normalize_id_number(id_number)
    if len(id_number) != 18:
        return False
    try:
        s = sum(int(id_number[i]) * _ID_WEIGHTS[i] for i in range(17))
    except ValueError:
        return False
    return _ID_CHECK[s % 11] == id_number[17].upper()


def is_valid_usci(usci: str) -> bool:
    if not usci or len(usci) != 18:
        return False
    try:
        total = sum(_USCI_CHARS.index(c) * _USCI_WEIGHTS[i] for i, c in enumerate(usci[:17]))
    except ValueError:
        return False
    c = 31 - (total % 31)
    if c == 31:
        c = 0
    return _USCI_CHARS[c] == usci[17]


def complete_id(base17: str) -> str:
    """根据前 17 位补全校验位，返回合法 18 位身份证号（用于生成测试样本）。"""
    base17 = _normalize_id_number(base17)
    s = sum(int(base17[i]) * _ID_WEIGHTS[i] for i in range(17))
    return base17 + _ID_CHECK[s % 11]


def _missing(out: Dict[str, Any], fields: List[str]) -> List[Dict[str, Any]]:
    issues = []
    for f in fields:
        if not out.get(f):
            issues.append({"field": f, "severity": "high", "type": "missing",
                           "msg": f"缺失字段：{f}", "suggest": None})
    return issues


# 姓名绝不应包含的标签/性别关键字（与 id_rules 的排除词保持一致）
_NAME_BAD = re.compile(
    r"(性别|男|女|民族|出生|住址|公民身份号码|姓名"
    r"|居民|身份证|联系电话|电话|手机|单位|职务|编号|证书|培训|学校|学院|公司|部门)"
)


def _name_issues(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """姓名合理性校验（仅身份证）：姓名被识别成性别/标签，或非常规长度/非汉字时告警。"""
    issues: List[Dict[str, Any]] = []
    name = out.get("name")
    if not name:
        return issues  # 缺失已由 _missing 覆盖
    if _NAME_BAD.search(name):
        issues.append({"field": "name", "severity": "high", "type": "invalid",
                       "msg": f"姓名疑似被识别为性别或字段标签（{name}），请人工校正", "suggest": None})
    elif not (2 <= len(name) <= 4 and all("一" <= c <= "鿿" for c in name)):
        issues.append({"field": "name", "severity": "medium", "type": "invalid",
                       "msg": f"姓名非常规（{name}），请人工确认", "suggest": None})
    return issues


def validate_fields(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """对单个抽取结果做异常校对，返回 issue 列表（空表示无异常）。"""
    issues: List[Dict[str, Any]] = []
    if out.get("doc_type") == "id_card":
        issues += _missing(out, ["name", "sex", "nation", "birth", "address", "id_number"])
        issues += _name_issues(out)
        idn = out.get("id_number")
        if idn and is_valid_id_number(idn):
            ymd = idn[6:14]
            if out.get("birth") and out["birth"].replace("-", "") != ymd:
                issues.append({"field": "birth", "severity": "medium", "type": "inconsistent",
                               "msg": f"出生日期 {out['birth']} 与证件号内嵌 {ymd} 不一致", "suggest": ymd})
            parity = "男" if int(idn[16]) % 2 == 1 else "女"
            if out.get("sex") and out["sex"] != parity:
                issues.append({"field": "sex", "severity": "medium", "type": "inconsistent",
                               "msg": f"性别 {out['sex']} 与证件号顺序码奇偶({parity}) 不一致", "suggest": parity})
        elif idn:
            issues.append({"field": "id_number", "severity": "high", "type": "checksum",
                           "msg": "身份证号校验位错误", "suggest": complete_id(idn[:17])})
    elif out.get("doc_type") == "biz_license":
        issues += _missing(out, ["name", "legal_person", "usci", "establish_date"])
        usci = out.get("usci")
        if usci and not is_valid_usci(usci):
            issues.append({"field": "usci", "severity": "high", "type": "checksum",
                           "msg": "统一社会信用代码校验位错误", "suggest": None})
    return issues
