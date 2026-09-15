"""批量操作：目录/通配批量 OCR + 字段抽取 + 异常校对，产出结果文件与报告。

输出到 out_dir：
  results.json      逐张结构化结果（含 issues）
  results.csv       扁平化字段表
  report.html       单文件可视化校对报告（表格 + 异常高亮）
  vis_<name>.png    逐张检测框可视化
"""
from __future__ import annotations

import csv
import glob
import json
import os
from typing import Any, Callable, List, Optional

from . import id_rules
from .extractor import run
from .llm_client import LLMClient
from .validate import validate_fields
from .visualize import draw_ocr

IMG_EXTS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff")


def _collect(paths: List[str]) -> List[str]:
    imgs: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            for ext in IMG_EXTS:
                imgs += glob.glob(os.path.join(p, "**", ext), recursive=True)
        else:
            imgs.append(p)
    return sorted(set(imgs))


def _emit(progress: Optional[Callable[..., None]], done: int, total: int,
          current: str) -> None:
    """上报批量进度（progress 为 None 时静默跳过，不改变既有行为）。"""
    if progress is None:
        return
    try:
        progress(done, total, current)
    except Exception:  # 进度回调异常不得中断识别主流程
        pass


def run_batch(
    inputs: List[str],
    out_dir: str,
    llm: Optional[LLMClient] = None,
    doc_type: str = "auto",
    visualize: bool = True,
    progress: Optional[Callable[..., None]] = None,
) -> dict:
    """批量识别。progress(done, total, current_name) 可选回调，用于前端实时进度条。"""
    os.makedirs(out_dir, exist_ok=True)
    imgs = _collect(inputs)
    records: List[dict] = []
    _total = len(imgs)

    engine = None  # 延迟初始化 RapidOCR（仅在有图片时）
    for _idx, img in enumerate(imgs, 1):
        # 进入本张前上报：done=已完成数，current=正在处理的图片
        _emit(progress, _idx - 1, _total, os.path.basename(img))
        if engine is None:
            from rapidocr import RapidOCR

            engine = RapidOCR()
        res = engine(img)
        texts = list(res.txts) if res.txts is not None else []
        boxes = res.boxes
        out = run(texts, boxes, doc_type=doc_type, llm=llm)
        out["_source"] = os.path.basename(img)
        out["issues"] = validate_fields(out)

        if visualize and boxes is not None:
            vis = os.path.join(out_dir, "vis_" + os.path.splitext(os.path.basename(img))[0] + ".png")
            draw_ocr(img, boxes, texts, out_path=vis,
                     field_labels={k: out[k] for k in out if k not in ("_source", "issues", "_fill_rate", "doc_type")})
            out["_vis"] = os.path.basename(vis)
        records.append(out)
    _emit(progress, _total, _total, "")  # 全部处理完，收尾上报

    # JSON
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    # CSV（扁平）
    flat_fields = ["_source", "doc_type", "name", "sex", "nation", "birth", "address",
                   "id_number", "type", "legal_person", "capital", "establish_date", "usci", "scope", "_fill_rate"]
    with open(os.path.join(out_dir, "results.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=flat_fields, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in flat_fields})

    _write_html(records, os.path.join(out_dir, "report.html"))
    summary = {
        "total": len(records),
        "with_issues": sum(1 for r in records if r["issues"]),
        "out_dir": out_dir,
    }
    return summary


def _write_html(records: List[dict], path: str) -> None:
    rows = []
    for r in records:
        issue_txt = "<br>".join(f"[{i['severity']}] {i['msg']}" for i in r["issues"]) or "无"
        cls = "" if not r["issues"] else ("bad" if any(i["severity"] == "high" for i in r["issues"]) else "warn")
        vis = r.get("_vis")
        vis_cell = f'<img src="{vis}" height="120">' if vis else ""
        rows.append(
            f'<tr class="{cls}"><td>{r.get("_source","")}</td>'
            f"<td>{r.get('name','')}</td><td>{r.get('id_number','') or r.get('usci','')}</td>"
            f"<td>{r.get('_fill_rate','')}</td><td>{issue_txt}</td><td>{vis_cell}</td></tr>"
        )
    html = f"""<!doctype html><html lang=zh><head><meta charset=utf-8>
<title>RapidOCR 批量抽取与校对报告</title>
<style>
body{{font-family:system-ui;margin:24px;color:#222}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #ccc;padding:6px 8px;vertical-align:top}}
th{{background:#f2f2f2}}
tr.bad{{background:#ffecec}} tr.warn{{background:#fff6e0}}
h2{{margin-top:32px}}
</style></head><body>
<h1>RapidOCR 批量抽取与校对报告</h1>
<p>共 {len(records)} 张，异常 {sum(1 for r in records if r['issues'])} 张。</p>
<table><thead><tr><th>文件</th><th>姓名</th><th>证件号</th><th>填充率</th><th>异常校对</th><th>可视化</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
