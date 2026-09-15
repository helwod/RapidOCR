"""识别记录质量审计：扫描 store.json 全部证件记录，做跨字段一致性校验。

校验项：
- 身份证号：18 位格式 + ISO 7064 mod11-2 校验位
- 性别：与身份证第 17 位奇偶一致（奇=男，偶=女）
- 出生：与身份证内嵌 YYYYMMDD 一致
- 民族：命中 56 个法定民族之一
- 姓名：2-4 个汉字，且不含有标签/性别关键字（性别男、男、女、民族…）

运行：.venv/Scripts/python.exe field_understanding/audit_records.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "store.json")

NATIONS = set(
    "汉族蒙古族回族藏族维吾尔族苗族彝族壮族布依族朝鲜族满族侗族瑶族白族土家族哈尼族"
    "哈萨克族傣族黎族傈僳族佤族畲族高山族拉祜族水族东乡族纳西族景颇族柯尔克孜族土族"
    "达斡尔族仫佬族羌族布朗族撒拉族毛南族仡佬族锡伯族阿昌族普米族塔吉克族怒族乌孜别克族"
    "俄罗斯族鄂温克族德昂族保安族裕固族京族塔塔尔族独龙族鄂伦春族赫哲族门巴族珞巴族基诺族"
    "穿青人其他".split()
)
# 单字简写也合法（OCR 常只输出「汉」「蒙」「回」等）
NATION_PREFIX = {n[0] for n in NATIONS} | {"汉"}

WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
CHECK = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"]
LABEL_IN_NAME = ("性别", "男", "女", "民族", "出生", "住址", "公民身份号码", "居民", "身份证")


def id_checksum_ok(num: str) -> bool:
    if not (isinstance(num, str) and len(num) == 18):
        return False
    if not num[:17].isdigit():
        return False
    s = sum(int(num[i]) * WEIGHTS[i] for i in range(17))
    return CHECK[s % 11] == num[17].upper()


def collect_records(store: dict):
    recs = []
    root = store if isinstance(store, dict) else {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("doc_type") == "id_card" and "id_number" in o:
                recs.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(root)
    return recs


def audit(rec: dict):
    issues = []

    num = rec.get("id_number")
    if not (isinstance(num, str) and len(num) == 18 and num[:17].isdigit()
            and (num[17].isdigit() or num[17] in "Xx")):
        issues.append(f"身份证号格式非法: {num!r}")
    else:
        if not id_checksum_ok(num):
            issues.append(f"身份证号校验位错误: {num}")
        # 性别一致性
        sex = rec.get("sex")
        parity = "男" if int(num[16]) % 2 == 1 else "女"
        if sex and sex != parity:
            issues.append(f"性别({sex})与号码第17位({parity})不一致")
        # 出生一致性
        birth = rec.get("birth")
        embedded = f"{num[6:10]}-{num[10:12]}-{num[12:14]}"
        if birth and birth != embedded:
            issues.append(f"出生({birth})与号码内嵌日期({embedded})不一致")

    nation = rec.get("nation")
    if nation and nation not in NATIONS and nation not in NATION_PREFIX:
        issues.append(f"民族非法或未识别: {nation!r}")

    name = rec.get("name")
    if not name:
        issues.append("姓名为空")
    else:
        if any(k in name for k in LABEL_IN_NAME):
            issues.append(f"姓名含标签/性别关键字: {name!r}")
        elif not (2 <= len(name) <= 4 and all("一" <= c <= "鿿" for c in name)):
            issues.append(f"姓名非常规(长度/非汉字): {name!r}")

    if not rec.get("address"):
        issues.append("住址为空")

    return issues


def main():
    store = json.load(open(STORE, "r", encoding="utf-8"))
    recs = collect_records(store)
    print(f"共扫描 id_card 记录: {len(recs)}")

    bad = []
    for r in recs:
        iss = audit(r)
        if iss:
            bad.append((r, iss))

    print(f"存在异常的记录: {len(bad)} / {len(recs)}\n")

    # 按身份证号去重，定位「真实人」层面问题
    by_id = defaultdict(list)
    for r, iss in bad:
        by_id[r.get("id_number")].append((r, iss))

    for idx, (num, items) in enumerate(by_id.items(), 1):
        print(f"=== 异常人 {idx}  身份证 {num}  (出现 {len(items)} 次) ===")
        # 取一条展示姓名/性别/民族/出生
        r0 = items[0][0]
        print(f"  姓名={r0.get('name')!r} 性别={r0.get('sex')!r} 民族={r0.get('nation')!r} 出生={r0.get('birth')!r}")
        # 汇总该人所有异常类型
        all_iss = []
        for _, iss in items:
            all_iss.extend(iss)
        for line in dict.fromkeys(all_iss):
            print(f"    - {line}")
    print()
    # 各类异常计数
    counter = Counter()
    for _, iss in bad:
        for line in iss:
            counter[line.split(":")[0]] += 1
    print("异常类型分布:")
    for k, v in counter.most_common():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    sys.exit(main())
