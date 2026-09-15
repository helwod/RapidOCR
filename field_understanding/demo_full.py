"""演示：可视化 + 批量 + 异常校对 三合一。

生成 3 张合成身份证（1 合法 / 1 校验位错 / 1 缺住址），放入 batch_in/，
运行批量抽取+校对，输出 batch_out/{results.json,results.csv,report.html,vis_*.png}，
并打印每张的异常清单。
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from field_understanding import batch, validate

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(WS, "batch_in")
OUT = os.path.join(WS, "batch_out")


def _font(sz=30):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", sz)
    except Exception:
        return ImageFont.load_default()


def make_card(path, name, sex, nation, birth, address, id_tail, seq17):
    from field_understanding.validate import complete_id
    # id_tail: 用合法校验位生成完整号；seq17 为前17位
    if id_tail is None:
        id_tail = complete_id(seq17)
    W, H = 856, 540
    img = Image.new("RGB", (W, H), (233, 240, 250))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "居民身份证", fill=(180, 30, 30), font=_font(34))
    lines = [
        (f"姓名 {name}", 110),
        (f"性别 {sex} 民族 {nation}", 165),
        (f"出生 {birth}", 220),
    ]
    if address is not None:
        lines.append((f"住址 {address}", 275))
    lines.append((f"公民身份号码 {id_tail}", 360))
    for text, y in lines:
        d.text((40, y), text, fill=(20, 20, 20), font=_font(30))
    img.save(path)


def main():
    os.makedirs(IN, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    # 1) 合法
    make_card(os.path.join(IN, "card_valid.png"), "张伟", "男", "汉",
              "1990年5月12日", "北京市海淀区中关村南大街5号院3号楼", None, "11010819900512371")
    # 2) 校验位错误（生成合法号后篡改末位，确保触发校验异常）
    from field_understanding.validate import complete_id
    good = complete_id("31011519880320042")
    bad = good[:-1] + ("0" if good[-1] == "X" else "X")
    make_card(os.path.join(IN, "card_badsum.png"), "李娜", "女", "汉",
              "1988年3月20日", "上海市浦东新区世纪大道100号", bad, "31011519880320042")
    # 3) 缺住址
    make_card(os.path.join(IN, "card_noaddr.png"), "王芳", "女", "回",
              "1995年11月8日", None, None, "11010819951108302")

    summary = batch.run_batch([IN], OUT, llm=None, doc_type="id_card", visualize=True)
    print("[batch] 汇总:", summary)

    import json
    with open(os.path.join(OUT, "results.json"), "r", encoding="utf-8") as f:
        records = json.load(f)
    for r in records:
        print(f"\n=== {r['_source']}  填充率 {r['_fill_rate']} ===")
        if r["issues"]:
            for i in r["issues"]:
                print(f"  [{i['severity']}] {i['type']}: {i['msg']}" + (f"  建议={i['suggest']}" if i.get('suggest') else ""))
        else:
            print("  无异常")


if __name__ == "__main__":
    main()
