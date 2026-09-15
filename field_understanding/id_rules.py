"""规则层：基于正则 + 坐标关系的确定性字段抽取（完全离线）。

支持两类证件：
- id_card      中华人民共和国居民身份证（正面）
- biz_license  营业执照
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ---- 通用正则（注意：Python re 的 \b 把中文当单词字符，故用 ASCII 环视避免误判）----
ID18_RE = re.compile(r"(?<![0-9])(\d{17}[0-9Xx])(?![0-9])")
USCI_RE = re.compile(r"(?<![A-Za-z0-9])([0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10})(?![A-Za-z0-9])")
DATE_RE = re.compile(r"(\d{4})[\s年.\-](\d{1,2})[\s月.\-](\d{1,2})[\s日号]?")
SEX_RE = re.compile(r"(男|女)")
NATION_RE = re.compile(r"民族[\s:：]?([一-龥]{1,6})")
# 姓名纯化：剥离标签前缀，并排除“性别/男/女/民族/…”等绝不可能是姓名的内容
NAME_LABEL_RE = re.compile(r"^(姓名|性别|民族|出生|住址|公民身份号码)[\s:：]?")
EXCLUDE_NAME_RE = re.compile(
    r"(男|女|性别|民族|出生|住址|公民身份号码|姓名"
    r"|居民|身份证|中华|共和国|人民|签发|机关|有效|期限|公安部|照片"
    r"|联系电话|电话|手机|单位|职务|编号|证书|培训|学校|学院|公司|部门)"
)


def _y_center(box) -> float:
    ys = [p[1] for p in box]
    return sum(ys) / len(ys)


def _ordered(lines: List[Tuple[float, str]]) -> List[str]:
    return [t for _, t in sorted(lines, key=lambda x: x[0])]


def _normalize_text(s: str) -> str:
    """全角字符转半角、身份证末位 X 常见误识别（乘号/全角X/罗马数字Ⅹ）统一为 X。"""
    if not s:
        return s
    out = []
    for ch in s:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        out.append(ch)
    s = "".join(out)
    return s.replace("×", "X").replace("Ｘ", "X").replace("ｘ", "x").replace("Ⅹ", "X").replace("ⅹ", "x")


def _extract_name_candidate(raw: str) -> Optional[str]:
    """从原始 token 中纯化出姓名候选。

    OCR 常把“姓名”标签与相邻内容粘连（如“姓名男”“姓名性别 男”），
    或把姓名行与性别/民族行合并（如“姓名张伟性别男”）。
    本函数先剥离标签前缀，再仅取紧贴在最前方、且不含标签关键字的中文姓名片段，
    避免把“男/女/性别/民族”等误当姓名；若整串都含标签关键字则返回 None，
    交由后续 LLM/人工补全。
    """
    cand = raw.replace("姓名", "").strip(" :：")
    cand = NAME_LABEL_RE.sub("", cand).strip(" :：")
    if not cand:
        return None
    # 在首个标签关键字处截断，仅保留前方片段，避免贪心吞掉“性别/民族”等汉字
    stop = EXCLUDE_NAME_RE.search(cand)
    prefix = cand[: stop.start()] if stop else cand
    # 取前方的中文姓名片段（1-4 字，可含·）
    m = re.match(r"[一-龥·]{1,4}", prefix)
    if m:
        return m.group(0)
    # 整串不含任何标签关键字 → 原值兜底（含字母/数字等噪声情形）
    if not EXCLUDE_NAME_RE.search(cand):
        return cand
    return None


def extract_id_card(texts: List[str], boxes=None) -> Dict[str, Any]:
    """身份证正面字段抽取。texts 为识别文本列表；boxes 可选（用于住址多行拼接）。"""
    out: Dict[str, Any] = {
        "doc_type": "id_card",
        "name": None,
        "sex": None,
        "nation": None,
        "birth": None,
        "address": None,
        "id_number": None,
    }
    merged = _normalize_text("\n".join(texts).replace(" ", ""))

    # 1) 公民身份号码：18 位，最确定
    m = ID18_RE.search(merged)
    if m:
        out["id_number"] = m.group(0)

    # 2) 性别 / 民族（常同行：性别 男 民族 汉）
    for t in texts:
        s = SEX_RE.search(t)
        if s and out["sex"] is None:
            out["sex"] = s.group(1)
        n = NATION_RE.search(t)
        if n and out["nation"] is None:
            out["nation"] = n.group(1)

    # 3) 出生日期
    for t in texts:
        d = DATE_RE.search(t.replace(" ", ""))
        if d and "出生" in t:
            out["birth"] = f"{int(d.group(1)):04d}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"
            break
    if out["birth"] is None:  # 退化：任何合法日期且靠近出生行
        for t in texts:
            if "出生" in t:
                d = DATE_RE.search(t.replace(" ", ""))
                if d:
                    out["birth"] = f"{int(d.group(1)):04d}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"

    # 4) 姓名：定位“姓名”标签，优先取标签自身/同一 token 及下一 token 的姓名；
    #    OCR 偶尔把姓名值排在“姓名”标签之前（阅读顺序异常），故也回看前一 token。
    for i, t in enumerate(texts):
        if "姓名" in t:
            for cand_tok in (
                t,
                texts[i + 1] if i + 1 < len(texts) else None,
                texts[i - 1] if i - 1 >= 0 else None,
            ):
                if cand_tok is None:
                    continue
                cand = _extract_name_candidate(cand_tok)
                if cand:
                    out["name"] = cand
                    break
            break

    # 5) 住址：坐标在“住址”与“公民身份号码”之间的多行文本
    if boxes is not None and len(boxes) == len(texts):
        rows = [( _y_center(boxes[i]), texts[i]) for i in range(len(texts))]
        rows.sort(key=lambda x: x[0])
        addr_lines: List[str] = []
        capture = False
        for y, t in rows:
            if "住址" in t:
                capture = True
                t = re.sub(r"^住址[\s:：]?", "", t).strip()
                if t:
                    addr_lines.append(t)
                continue
            if "公民身份号码" in t or (out["id_number"] and out["id_number"] in t):
                capture = False
                continue
            if capture:
                addr_lines.append(t)
        if addr_lines:
            out["address"] = "".join(addr_lines)
    else:  # 无坐标时退化为：住址行去前缀
        for t in texts:
            if "住址" in t:
                out["address"] = re.sub(r"^住址[\s:：]?", "", t).strip()
                break
    return out


def extract_business_license(texts: List[str], boxes=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "doc_type": "biz_license",
        "name": None,
        "type": None,
        "legal_person": None,
        "capital": None,
        "establish_date": None,
        "usci": None,
        "address": None,
        "scope": None,
    }
    merged = _normalize_text("\n".join(texts).replace(" ", ""))
    m = USCI_RE.search(merged)
    if m:
        out["usci"] = m.group(0)
    for t in texts:
        if "名称" in t:
            out["name"] = re.sub(r"^名称[\s:：]?", "", t).strip()
        elif "类型" in t:
            out["type"] = re.sub(r"^类型[\s:：]?", "", t).strip()
        elif "法定代表人" in t:
            out["legal_person"] = re.sub(r"^法定代表人[\s:：]?", "", t).strip()
        elif "注册资本" in t:
            out["capital"] = re.sub(r"^注册资本[\s:：]?", "", t).strip()
        elif "成立日期" in t:
            d = DATE_RE.search(t.replace(" ", ""))
            out["establish_date"] = d.group(0).replace(" ", "") if d else re.sub(r"^成立日期[\s:：]?", "", t).strip()
        elif "住所" in t:
            out["address"] = re.sub(r"^住所[\s:：]?", "", t).strip()
        elif "经营范围" in t:
            out["scope"] = re.sub(r"^经营范围[\s:：]?", "", t).strip()
    return out


def extract_document(texts: List[str], boxes=None, doc_type: str = "auto") -> Dict[str, Any]:
    """自动判别证件类型并抽取；doc_type 可强制指定 id_card / biz_license。

    注意：18 位身份证号也能命中 USCI 正则，故自动判别以关键词为准，
    仅当关键词缺失时才退回到 USCI 是否存在。
    """
    merged = "\n".join(texts)
    if doc_type == "auto":
        id_kw = (
            ("居民身份证" in merged)
            or ("公民身份号码" in merged)
            or ("姓名" in merged and "性别" in merged)
        )
        biz_kw = (
            ("营业执照" in merged)
            or ("统一社会信用代码" in merged)
            or ("法定代表人" in merged)
            or ("经营范围" in merged)
        )
        if id_kw and not biz_kw:
            doc_type = "id_card"
        elif biz_kw and not id_kw:
            doc_type = "biz_license"
        else:
            # 无明确关键词证据：仅在存在强特征（USCI / 18 位身份证号）时才定类型。
            # 否则判为 unknown —— 避免对培训证书、随机图片等非证件图硬抽字段，
            # 产生「联系电话当姓名」「1234 当姓名」这类垃圾值。
            if USCI_RE.search(merged.replace(" ", "")):
                doc_type = "biz_license"
            elif ID18_RE.search(merged.replace(" ", "")):
                doc_type = "id_card"
            else:
                return {
                    "doc_type": "unknown",
                    "name": None,
                    "sex": None,
                    "nation": None,
                    "birth": None,
                    "address": None,
                    "id_number": None,
                }
    if doc_type == "biz_license":
        return extract_business_license(texts, boxes)
    if doc_type == "unknown":
        return {
            "doc_type": "unknown",
            "name": None,
            "sex": None,
            "nation": None,
            "birth": None,
            "address": None,
            "id_number": None,
        }
    return extract_id_card(texts, boxes)
