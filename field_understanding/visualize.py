"""可视化操作：在图像上绘制 OCR 检测框 + 识别文本，并叠加字段标注。

纯 PIL 实现，离线可用；输出 PNG 供人工核对。
"""
from __future__ import annotations

from typing import Any, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _font(size: int = 18):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    except Exception:
        return ImageFont.load_default()


def _draw_boxes(draw, boxes, texts, font) -> None:
    """在图上绘制检测框 + 识别文本（仅作用于传入的 draw 对象）。"""
    for i, box in enumerate(boxes):
        pts = [(int(p[0]), int(p[1])) for p in np.array(box).reshape(-1, 2)]
        draw.polygon(pts, outline=(220, 30, 30), width=2)
        if texts and i < len(texts):
            tl = pts[0]
            ty = tl[1] - 20
            if ty < 0:  # 框贴顶时，文字改画在框内顶部，避免越界
                ty = tl[1] + 2
            draw.text((tl[0], ty), texts[i], fill=(220, 30, 30), font=font)


def _draw_legend_strip(draw, lines, font, x0, y0, max_w) -> None:
    """在画布底部条带绘制字段摘要：浅底(白)深字 + 灰边，绝不遮挡图片内容。"""
    if not lines:
        return
    pad = 6
    lh = 22
    w = min(max(draw.textlength(s, font=font) for s in lines) + 2 * pad, max_w)
    h = lh * len(lines) + 2 * pad
    draw.rectangle([x0, y0, x0 + w, y0 + h], fill=(255, 255, 255), outline=(150, 150, 150))
    for j, s in enumerate(lines):
        draw.text((x0 + pad, y0 + pad + j * lh), s, fill=(30, 30, 30), font=font)


def _center_text(draw, text, cx, y, font, fill) -> None:
    w = draw.textlength(text, font=font)
    draw.text((cx - w / 2, y), text, fill=fill, font=font)


def draw_ocr(
    image_path: str,
    boxes,
    texts: Optional[List[str]] = None,
    out_path: Optional[str] = None,
    field_labels: Optional[dict] = None,
    compare: bool = True,
) -> Image.Image:
    """生成可视化图。

    compare=True（默认）：输出「左侧原图 | 右侧标注图」并排对比。
      - 左侧原图完全干净，不叠加任何内容，便于人工核对原始文字；
      - 右侧标注图仅含检测框 + 识别文本；
      - 字段摘要独立绘制在两张图下方的浅色条带，不覆盖任何图片；
      - 顶部标题条区分「原图」与「OCR 标注」。
    compare=False：单图模式，标注与字段摘要同样置于底部条带，不遮挡原图文字。

    boxes: RapidOCR 返回的 numpy 数组 [N,4,2]；texts: 对应文本列表。
    """
    img = Image.open(image_path).convert("RGB")
    font = _font(18)

    # 字段摘要行（用于底部条带）
    label_lines = [f"{k}: {v}" for k, v in (field_labels or {}).items() if v]
    pad = 6
    lh = 22
    strip_h = (lh * len(label_lines) + 2 * pad) if label_lines else 0

    if compare:
        annotated = img.copy()
        adraw = ImageDraw.Draw(annotated)
        _draw_boxes(adraw, boxes, texts, font)

        title_h = 32
        gap = 14
        canvas = Image.new("RGB",
                           (img.width * 2 + gap, img.height + title_h + strip_h),
                           (245, 245, 245))
        cd = ImageDraw.Draw(canvas)
        tfont = _font(16)
        _center_text(cd, "原图", img.width // 2, 6, tfont, (40, 40, 40))
        _center_text(cd, "OCR 标注（红框=检测框，红字=识别文本）",
                     img.width + gap + img.width // 2, 6, tfont, (200, 30, 30))
        canvas.paste(img, (0, title_h))
        canvas.paste(annotated, (img.width + gap, title_h))
        if label_lines:
            _draw_legend_strip(cd, label_lines, font, 10, title_h + img.height + pad,
                               img.width * 2 + gap - 20)
        img = canvas
    else:
        base = img
        canvas = Image.new("RGB", (base.width, base.height + strip_h), (245, 245, 245))
        canvas.paste(base, (0, 0))
        draw = ImageDraw.Draw(canvas)
        _draw_boxes(draw, boxes, texts, font)
        if label_lines:
            _draw_legend_strip(draw, label_lines, font, 10, base.height + pad,
                               base.width - 20)
        img = canvas

    if out_path:
        img.save(out_path)
    return img
