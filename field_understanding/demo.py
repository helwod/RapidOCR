"""演示：合成一张身份证正面图 -> RapidOCR 识别 -> 规则+LLM 混合字段抽取。

运行：.venv/Scripts/python.exe field_understanding/demo.py
默认 LLM 关闭（mock），纯规则离线抽取；如需 LLM 补全，设置环境变量后启用。
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# 让本文件可直接作为脚本运行（无需 pip install -e）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from field_understanding import run, LLMClient  # noqa: E402

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(WS, "demo_idcard.png")


def make_idcard(path: str) -> str:
    W, H = 856, 540
    img = Image.new("RGB", (W, H), (233, 240, 250))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 30)
        font_big = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 34)
    except Exception:
        font = font_big = ImageFont.load_default()
    d.text((40, 30), "居民身份证", fill=(180, 30, 30), font=font_big)
    lines = [
        ("姓名 张伟", 110),
        ("性别 男 民族 汉", 165),
        ("出生 1990 年 5 月 12 日", 220),
        ("住址 北京市海淀区中关村南大街5号院3号楼", 275),
        ("公民身份号码 11010819900512371X", 360),
    ]
    for text, y in lines:
        d.text((40, y), text, fill=(20, 20, 20), font=font)
    img.save(path)
    return path


def main() -> None:
    img_path = make_idcard(IMG)
    print(f"[demo] 合成证件图: {img_path}")

    from rapidocr import RapidOCR

    engine = RapidOCR()
    result = engine(img_path)
    texts = list(result.txts) if result.txts is not None else []
    boxes = result.boxes
    print(f"[demo] OCR 识别 {len(texts)} 行文本:")
    for t in texts:
        print("   -", t)

    llm = LLMClient(enabled=False)  # 默认 mock；指向 airllm 时改 enabled=True + base_url
    out = run(texts, boxes, doc_type="auto", llm=llm)
    print("\n[demo] 字段抽取结果 (JSON):")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
