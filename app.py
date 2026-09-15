"""RapidOCR 可视化校对工作台 —— 后端服务（FastAPI）。

完全离线运行：复用 field_understanding 各模块（OCR/抽取/校验/可视化/批量），
不重写任何识别或抽取逻辑。前端为单文件 static/index.html，不依赖任何外部资源。

启动：
    C:/Users/Administrator/WorkBuddy/RapidOCR/.venv/Scripts/python.exe app.py
端口默认 8003，可用环境变量覆盖：
    RAPIDOCR_PORT=8003   RAPIDOCR_HOST=0.0.0.0
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import sys
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# 工作区根目录。
# 冻结（PyInstaller one-folder/one-file）后以可执行文件所在目录为根，
# 使 models/、static/、store.json、cache 等随 exe 部署。
# 开发态下则取脚本所在目录。
if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    _meipass = getattr(sys, "_MEIPASS", None)
    _cands = []
    if _meipass:
        _cands.append(_meipass)
    _cands.append(_exe_dir)
    if _meipass:
        _cands.append(os.path.join(_meipass, "_internal"))
    _cands.append(os.path.join(_exe_dir, "_internal"))
    BUNDLE_DIR = None
    for _c in _cands:
        if os.path.isdir(os.path.join(_c, "static")):
            BUNDLE_DIR = _c
            break
    if BUNDLE_DIR is None:
        BUNDLE_DIR = _meipass or _exe_dir
    EXE_DIR = _exe_dir
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = EXE_DIR
if EXE_DIR not in sys.path:
    sys.path.insert(0, EXE_DIR)

ROOT = EXE_DIR

# 日志：输出到日志文件；有控制台时同时镜像到控制台，便于窗口模式（--windowed）排查错误
LOG_PATH = os.path.join(ROOT, "rapidocr_app.log")

# 关键修复：窗口式 exe（PyInstaller console=False，双击启动）下 sys.stdout/sys.stderr 可能为 None，
# 而 uvicorn 日志配置会在格式化器 __init__ 中调用 .isatty() 导致崩溃（AttributeError: 'NoneType'...isatty）。
# 在日志系统初始化与 uvicorn.run 之前，将 None 重定向到日志文件以兜底（同时修复自身 StreamHandler）。
_stdout_was_none = sys.stdout is None
_stderr_was_none = sys.stderr is None
if _stdout_was_none:
    sys.stdout = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
if _stderr_was_none:
    sys.stderr = open(LOG_PATH, "a", encoding="utf-8", errors="replace")

_log_handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
if not _stderr_was_none:  # 控制台可用时才镜像，避免窗口模式下日志重复写两份
    _log_handlers.append(logging.StreamHandler(sys.stderr))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=_log_handlers,
)
log = logging.getLogger("rapidocr")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from field_understanding import batch, engine, extractor, id_rules, validate, visualize
from field_understanding.llm_client import LLMClient

# ----------------------------------------------------------------------------
# 基础配置
# ----------------------------------------------------------------------------
STATIC_DIR = os.path.join(ROOT, "static")
CACHE_DIR = os.path.join(STATIC_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 冻结态下，index.html 等静态资源被打包在 BUNDLE_DIR/static（可能为 _internal/static）。
# 为保证 "/" 与 "/static" 能正常服务，并在 EXE_DIR/static 缺失时自愈，
# 启动时把打包内的静态文件同步到可写的 EXE_DIR/static（仅缺失时复制，不覆盖运行期缓存）。
if getattr(sys, "frozen", False):
    _bundle_static = os.path.join(BUNDLE_DIR, "static")
    if os.path.isdir(_bundle_static):
        os.makedirs(STATIC_DIR, exist_ok=True)
        for _name in os.listdir(_bundle_static):
            _src = os.path.join(_bundle_static, _name)
            if os.path.isfile(_src):
                _dst = os.path.join(STATIC_DIR, _name)
                if not os.path.exists(_dst):
                    try:
                        shutil.copyfile(_src, _dst)
                    except Exception:
                        pass

DEFAULT_PORT = int(os.getenv("RAPIDOCR_PORT", "8003"))
DEFAULT_HOST = os.getenv("RAPIDOCR_HOST", "0.0.0.0")

# 各证件类型字段顺序（用于构建可编辑表格）
SCHEMA: Dict[str, List[str]] = {
    "id_card": ["name", "sex", "nation", "birth", "address", "id_number"],
    "biz_license": ["name", "type", "legal_person", "capital",
                    "establish_date", "usci", "address", "scope"],
}

# 字段中文标签（前端展示用）
LABELS: Dict[str, str] = {
    "name": "姓名/名称",
    "sex": "性别",
    "nation": "民族",
    "birth": "出生日期",
    "address": "住址/住所",
    "id_number": "公民身份号码",
    "type": "类型",
    "legal_person": "法定代表人",
    "capital": "注册资本",
    "establish_date": "成立日期",
    "usci": "统一社会信用代码",
    "scope": "经营范围",
}

# 内存态存储：单图提取结果 / 批量结果。为支持"刷新/重启不丢数据"，落盘到 store.json。
# key -> {image_path, vis_url, rec, fields}
STORE_PATH = os.path.join(ROOT, "store.json")


def _load_store() -> Dict[str, Any]:
    if os.path.isfile(STORE_PATH):
        try:
            with open(STORE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_store() -> None:
    try:
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(STORE, f, ensure_ascii=False)
    except Exception:
        pass


STORE: Dict[str, Dict[str, Any]] = _load_store()

META_KEYS = ("doc_type", "_fill_rate", "_source", "_vis", "issues", "_source_map")

# LLM 默认关闭（mock/离线）：规则层独立工作
LLM = LLMClient(enabled=False)

app = FastAPI(title="RapidOCR 可视化校对工作台")

# 静态资源挂载（含 cache 子目录下的可视化 PNG 与批量结果）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ----------------------------------------------------------------------------
# RapidOCR 引擎（由 engine 模块统一管理：设置 / 模型选择 / 热重载）
# ----------------------------------------------------------------------------
def get_engine():
    return engine.get_engine()


# ----------------------------------------------------------------------------
# 核心处理流程（复用 field_understanding 模块）
# ----------------------------------------------------------------------------
def do_ocr(image_path: str):
    """调用 RapidOCR，返回 (texts, boxes)。boxes 可能为 None。"""
    result = get_engine()(image_path)
    texts = list(result.txts) if result.txts is not None else []
    boxes = result.boxes if result.boxes is not None else []
    return texts, boxes


def build_record(texts: List[str], boxes, doc_type: str = "auto"):
    """规则+LLM 混合抽取，并补全来源与异常校对信息。"""
    rec = extractor.run(texts, boxes, doc_type=doc_type, llm=LLM)
    # 来源判定：用纯规则层结果比对，区分 规则 / 模型 来源
    rule_only = id_rules.extract_document(texts, boxes, doc_type=rec["doc_type"])
    fields = SCHEMA.get(rec["doc_type"], [])
    src_map: Dict[str, str] = {}
    for f in fields:
        if rec.get(f):
            src_map[f] = "rule" if rule_only.get(f) else "llm"
        else:
            src_map[f] = "missing"
    rec["_source_map"] = src_map
    rec["issues"] = validate.validate_fields(rec)
    return rec, fields


def make_vis(image_path: str, boxes, texts: List[str], rec: Dict[str, Any],
             out_name: str) -> str:
    """生成可视化 PNG 并返回可访问 URL。"""
    vis_path = os.path.join(CACHE_DIR, out_name)
    field_labels = {
        k: rec.get(k) for k in SCHEMA.get(rec["doc_type"], []) if rec.get(k)
    }
    visualize.draw_ocr(image_path, boxes, texts, out_path=vis_path,
                       field_labels=field_labels)
    return "/static/cache/" + out_name


def fill_rate(rec: Dict[str, Any]) -> str:
    fields = SCHEMA.get(rec["doc_type"], [])
    filled = sum(1 for f in fields if rec.get(f))
    return f"{filled}/{len(fields)}"


def fields_payload(rec: Dict[str, Any], fields: List[str]) -> List[Dict[str, Any]]:
    src_map = rec.get("_source_map", {})
    return [
        {
            "key": f,
            "label": LABELS.get(f, f),
            "value": rec.get(f),
            "source": src_map.get(f, "rule" if rec.get(f) else "missing"),
        }
        for f in fields
    ]


def record_payload(rid: str, rec: Dict[str, Any], fields: List[str],
                   vis_url: Optional[str]) -> Dict[str, Any]:
    return {
        "id": rid,
        "doc_type": rec["doc_type"],
        "vis_url": vis_url,
        "fields": fields_payload(rec, fields),
        "issues": rec.get("issues", []),
        "fill_rate": fill_rate(rec),
    }


def clean_source(source: str) -> str:
    """去掉批量上传时文件名前加的 uuid 前缀，还原原始文件名用于展示。"""
    return re.sub(r"^[0-9a-f]{32}_", "", source or "")


def build_batch_rows(blob: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从持久化的批次记录重建汇总行（与 api_batch 返回结构一致）。"""
    rows: List[Dict[str, Any]] = []
    for source, rec_blob in blob.get("records", {}).items():
        r = rec_blob.get("rec", {})
        rows.append({
            "source": source,
            "file_name": clean_source(source),
            "doc_type": r.get("doc_type"),
            "fill_rate": r.get("_fill_rate"),
            "issue_count": len(r.get("issues", [])),
            "issue_types": sorted({i["type"] for i in r.get("issues", [])}),
            "vis_url": rec_blob.get("vis_url"),
            "id": f"{blob.get('bid')}|{source}",
            "name": r.get("name"),
            "number": r.get("id_number") or r.get("usci"),
        })
    return rows


def apply_fields(rec: Dict[str, Any], submitted: Dict[str, Any]) -> None:
    """把前端提交的字段值写回结果，并重新计算来源/填充率/异常。"""
    fields = SCHEMA.get(rec["doc_type"], [])
    src_map = rec.setdefault("_source_map", {})
    for k, v in submitted.items():
        if k not in fields:
            continue
        rec[k] = v if v not in ("", None) else None
        src_map[k] = "edited" if rec.get(k) else "missing"
    rec["_fill_rate"] = fill_rate(rec)
    rec["issues"] = validate.validate_fields(rec)


# ----------------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------------
@app.get("/")
def index() -> Response:
    idx = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(idx):
        return FileResponse(idx)
    # 兜底：前端缺失时返回可读提示，而非 500 Internal Server Error
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><h2>RapidOCR 工作台</h2>"
        "<p>前端页面（index.html）未能加载。请确认程序目录完整，"
        "或将 index.html 放到程序所在目录的 static/ 子目录下后重新启动。</p>",
        status_code=200,
    )


@app.get("/api/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/ocr")
async def api_ocr(file: UploadFile = File(...),
                  doc_type: str = Form("auto")) -> Dict[str, Any]:
    """单图模式：上传图片 -> OCR + 抽取 + 校验 -> 返回字段与可视化。"""
    rid = uuid.uuid4().hex
    ext = os.path.splitext(file.filename or "img.png")[1].lower() or ".png"
    img_path = os.path.join(CACHE_DIR, f"src_{rid}{ext}")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    with open(img_path, "wb") as f:
        f.write(data)

    # 校验是否为合法图片
    try:
        from PIL import Image

        Image.open(img_path).verify()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"无效图片文件: {exc}")

    try:
        texts, boxes = do_ocr(img_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"OCR 失败: {exc}")

    rec, fields = build_record(texts, boxes, doc_type)
    vis_url = make_vis(img_path, boxes, texts, rec, f"vis_{rid}.png")
    STORE[rid] = {"image_path": img_path, "vis_url": vis_url,
                  "rec": rec, "fields": fields,
                  "file_name": file.filename or os.path.basename(img_path),
                  "created_at": datetime.now().isoformat(timespec="seconds")}
    _save_store()
    return record_payload(rid, rec, fields, vis_url)


@app.post("/api/validate")
async def api_validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """重新校验：提交编辑后的字段 -> 刷新来源/填充率/异常高亮。"""
    rid = payload.get("id")
    blob = STORE.get(rid)
    if blob is None:
        raise HTTPException(status_code=404, detail="未知记录 id")
    apply_fields(blob["rec"], payload.get("fields", {}))
    _save_store()
    return record_payload(rid, blob["rec"], blob["fields"], blob["vis_url"])


@app.post("/api/correct")
async def api_correct(payload: Dict[str, Any]) -> Dict[str, Any]:
    """应用修正：与重新校验共享同一闭环，把修正值写回结果。

    若提供了 corrections（字段子集），则仅应用这些字段；否则应用 fields 全量。
    """
    rid = payload.get("id")
    blob = STORE.get(rid)
    if blob is None:
        raise HTTPException(status_code=404, detail="未知记录 id")
    submitted = payload.get("corrections") or payload.get("fields", {})
    apply_fields(blob["rec"], submitted)
    _save_store()
    return record_payload(rid, blob["rec"], blob["fields"], blob["vis_url"])


# 批量任务（后台线程执行 + 前端轮询进度）。
# 结构：job_id -> {status, done, total, current, error, result}
_BATCH_JOBS: Dict[str, Dict[str, Any]] = {}


@app.post("/api/batch")
async def api_batch(files: Optional[List[UploadFile]] = File(None),
                    dir_path: str = Form(""),
                    doc_type: str = Form("auto")) -> Dict[str, Any]:
    """批量模式：多图上传或本地目录 -> 复用 batch.run_batch。

    改为「后台任务 + 进度轮询」：立即返回 job_id，识别在后台线程执行，
    前端用 /api/batch/progress 轮询进度、/api/batch/result 取最终结果，
    避免多图时页面长时间无响应。
    """
    bid = uuid.uuid4().hex
    out_dir = os.path.join(CACHE_DIR, f"batch_{bid}")
    os.makedirs(out_dir, exist_ok=True)

    inputs: List[str] = []
    if dir_path and os.path.isdir(dir_path):
        inputs.append(dir_path)
    for uf in (files or []):
        safe = f"{uuid.uuid4().hex}_{os.path.basename(uf.filename or 'img.png')}"
        p = os.path.join(out_dir, safe)
        data = await uf.read()
        if data:
            with open(p, "wb") as f:
                f.write(data)
            inputs.append(p)

    if not inputs:
        raise HTTPException(status_code=400, detail="未提供任何图片或有效目录")

    # 先收集图片列表，以便启动即上报总数
    try:
        total = len(batch._collect(inputs))
    except Exception:
        total = 0

    job: Dict[str, Any] = {"status": "running", "done": 0, "total": total,
                           "current": "", "error": None, "result": None}
    _BATCH_JOBS[bid] = job

    def _worker() -> None:
        def _on_progress(done: int, tot: int, current: str) -> None:
            job["done"], job["total"], job["current"] = done, tot, current

        try:
            summary = batch.run_batch(inputs, out_dir, llm=LLM, doc_type=doc_type,
                                      visualize=True, progress=_on_progress)

            with open(os.path.join(out_dir, "results.json"), encoding="utf-8") as f:
                records = json.load(f)

            rows: List[Dict[str, Any]] = []
            per_record: Dict[str, Dict[str, Any]] = {}
            for r in records:
                source = r.get("_source")
                vis = r.get("_vis")
                vis_url = (f"/static/cache/batch_{bid}/{vis}") if vis else None
                fields = SCHEMA.get(r["doc_type"], [])
                rid_rec = f"{bid}|{source}"
                per_record[source] = {"image_path": None, "vis_url": vis_url,
                                      "rec": r, "fields": fields}
                STORE[rid_rec] = per_record[source]
                rows.append({
                    "source": source,
                    "doc_type": r.get("doc_type"),
                    "fill_rate": r.get("_fill_rate"),
                    "issue_count": len(r.get("issues", [])),
                    "issue_types": sorted({i["type"] for i in r.get("issues", [])}),
                    "vis_url": vis_url,
                    "id": rid_rec,
                })
            _save_store()

            STORE[f"batch_{bid}"] = {"out_dir": out_dir, "records": per_record,
                                     "bid": bid,
                                     "created_at": datetime.now().isoformat(timespec="seconds")}
            _save_store()

            job["result"] = {
                "batch_id": bid,
                "total": summary.get("total", len(records)),
                "with_issues": summary.get("with_issues", 0),
                "rows": rows,
            }
            job["status"] = "done"
            job["done"] = job["total"]
            job["current"] = ""
        except Exception as e:  # 不让后台线程静默吞掉异常
            log.exception("批量任务 %s 失败", bid)
            job["status"] = "error"
            job["error"] = str(e)

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": bid, "total": total, "status": "started"}


@app.get("/api/batch/progress")
def api_batch_progress(job_id: str = "") -> Dict[str, Any]:
    """批量任务进度：返回 status / done / total / current / error。"""
    job = _BATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未知批量任务")
    return {"job_id": job_id, "status": job["status"], "done": job["done"],
            "total": job["total"], "current": job["current"], "error": job["error"]}


@app.get("/api/batch/result")
def api_batch_result(job_id: str = "") -> Dict[str, Any]:
    """批量任务结果：完成后返回与旧 /api/batch 一致的汇总结构。"""
    job = _BATCH_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未知批量任务")
    return {"status": job["status"], "error": job["error"], "result": job["result"]}


@app.post("/api/batch_detail")
async def api_batch_detail(payload: Dict[str, Any]) -> Dict[str, Any]:
    """批量详情：根据 batch_id + source 返回单张完整字段与可视化。"""
    bid = payload.get("batch_id")
    source = payload.get("source")
    blob = STORE.get(f"batch_{bid}")
    if blob is None:
        raise HTTPException(status_code=404, detail="未知批次")
    rec_blob = blob["records"].get(source)
    if rec_blob is None:
        raise HTTPException(status_code=404, detail="未知记录")
    rec = rec_blob["rec"]
    fields = rec_blob["fields"]
    # 补充来源映射（批量结果里可能无 _source_map）
    if "_source_map" not in rec:
        rec["_source_map"] = {
            f: ("rule" if rec.get(f) else "missing") for f in fields
        }
    return record_payload(f"{bid}|{source}", rec, fields, rec_blob["vis_url"])


@app.get("/api/records")
def api_records() -> Dict[str, Any]:
    """返回所有已持久化记录（单图 + 批量），供前端重建「识别记录」视图与刷新恢复。"""
    singles: List[Dict[str, Any]] = []
    batches: List[Dict[str, Any]] = []
    seq = 0
    for k, v in STORE.items():
        if k.startswith("batch_"):
            seq += 1
            batches.append({"batch_id": v.get("bid"),
                            "rows": build_batch_rows(v),
                            "created_at": v.get("created_at"),
                            "seq": seq})
        elif "|" in k:
            continue  # 批量明细键 {bid}|{source}，已由批次行覆盖，不再单列
        else:
            rec = v.get("rec", {})
            fields = v.get("fields", [])
            p = record_payload(k, rec, fields, v.get("vis_url"))
            p["file_name"] = v.get("file_name") or os.path.basename(v.get("image_path") or "")
            p["name"] = rec.get("name")
            p["number"] = rec.get("id_number") or rec.get("usci")
            p["created_at"] = v.get("created_at")
            singles.append(p)
    return {"singles": singles, "batches": batches}


@app.delete("/api/records")
def api_clear_records() -> Dict[str, Any]:
    """清空全部识别记录。"""
    n = len(STORE)
    STORE.clear()
    _save_store()
    return {"ok": True, "cleared": n}


@app.delete("/api/records/{key}")
def api_delete_record(key: str) -> Dict[str, Any]:
    """删除单条记录；key 为 batch_<bid> 时连同其明细一起删除。"""
    if key.startswith("batch_") and key in STORE:
        blob = STORE.pop(key)
        bid = blob.get("bid")
        for rk in [rk for rk in STORE if rk.startswith(f"{bid}|")]:
            STORE.pop(rk, None)
        _save_store()
        return {"ok": True, "deleted": key}
    if key in STORE:
        del STORE[key]
        _save_store()
        return {"ok": True, "deleted": key}
    raise HTTPException(status_code=404, detail="未知记录")


@app.get("/api/records/export")
def api_export_records(batch_id: str = "") -> Response:
    """导出识别记录为 CSV：指定 batch_id 导出该批次，否则导出全部单图记录。"""
    export_cols = ["name", "sex", "nation", "birth", "address", "id_number",
                   "type", "legal_person", "capital", "establish_date", "usci", "scope"]
    header = ["文件名", "证件类型", "填充率", "异常数"] + export_cols
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)

    if batch_id:
        blob = STORE.get(f"batch_{batch_id}")
        if blob is None:
            raise HTTPException(status_code=404, detail="未知批次")
        for source, rb in blob.get("records", {}).items():
            r = rb.get("rec", {})
            w.writerow([clean_source(source), r.get("doc_type"), r.get("_fill_rate"),
                        len(r.get("issues", []))] + [r.get(f, "") for f in export_cols])
    else:
        for k, v in STORE.items():
            if k.startswith("batch_") or "|" in k:
                continue
            r = v.get("rec", {})
            fn = v.get("file_name") or os.path.basename(v.get("image_path") or "")
            w.writerow([fn, r.get("doc_type"), r.get("_fill_rate"),
                        len(r.get("issues", []))] + [r.get(f, "") for f in export_cols])

    data = "\ufeff" + buf.getvalue()
    return Response(content=data, media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=rapidocr_records.csv"})


# ----------------------------------------------------------------------------
# 设置 / 模型下载 / 模型选择
# ----------------------------------------------------------------------------
@app.get("/api/settings")
def api_get_settings() -> Dict[str, Any]:
    """返回当前设置、模型目录（含本地状态）、预设组合、引擎状态。"""
    catalog = [dict(c, local=engine.is_local(c["id"])) for c in engine.CATALOG]
    return {
        "settings": engine.settings,
        "catalog": catalog,
        "presets": engine.PRESETS,
        "engine": engine.engine_status(),
        "repo_url": engine.MODEL_REPO_URL,
        "version_notes": engine.VERSION_NOTE,
    }


@app.post("/api/settings")
async def api_post_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """合并推理参数与模型选择，持久化并热重载引擎。"""
    if "inference" in payload and isinstance(payload["inference"], dict):
        for k, v in payload["inference"].items():
            engine.settings["inference"][k] = v
    if "selected" in payload and isinstance(payload["selected"], dict):
        for task in ("det", "rec", "cls"):
            v = payload["selected"].get(task)
            # 仅允许 catalog 内合法 id 或 None
            engine.settings["selected"][task] = (
                v if (v is None or v in engine.CATALOG_BY_ID) else None
            )
    engine.save_settings(engine.settings)
    try:
        engine.reload_engine()
        status = engine.engine_status()
        status["reload"] = "ok"
    except Exception as exc:  # noqa: BLE001
        status = {"ready": False, "error": str(exc), "reload": "failed"}
    return {
        "settings": engine.settings,
        "catalog": [dict(c, local=engine.is_local(c["id"])) for c in engine.CATALOG],
        "engine": status,
    }


@app.post("/api/settings/preset")
async def api_post_preset(payload: Dict[str, Any]) -> Dict[str, Any]:
    """套用预设组合（自动填充 selected），随后热重载。"""
    pid = payload.get("preset_id")
    preset = engine.PRESET_BY_ID.get(pid)
    if preset is None:
        raise HTTPException(status_code=404, detail="未知预设")
    engine.settings["selected"] = dict(preset["selected"])
    engine.save_settings(engine.settings)
    try:
        engine.reload_engine()
        status = engine.engine_status()
        status["reload"] = "ok"
    except Exception as exc:  # noqa: BLE001
        status = {"ready": False, "error": str(exc), "reload": "failed"}
    return {
        "settings": engine.settings,
        "catalog": [dict(c, local=engine.is_local(c["id"])) for c in engine.CATALOG],
        "engine": status,
    }


@app.get("/api/models")
def api_list_models() -> Dict[str, Any]:
    """模型库清单（含是否已下载到本地、模型说明与远程仓库链接）。"""
    return {
        "catalog": [dict(c, local=engine.is_local(c["id"])) for c in engine.CATALOG],
        "models_dir": engine.MODELS_DIR,
        "repo_url": engine.MODEL_REPO_URL,
        "version_notes": engine.VERSION_NOTE,
    }


@app.post("/api/models/download")
async def api_download_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    """下载指定模型（按 catalog id）。返回下载结果与 SHA256 校验。"""
    cid = payload.get("id")
    if cid not in engine.CATALOG_BY_ID:
        raise HTTPException(status_code=404, detail="未知模型 id")
    result = engine.download_model(cid)
    return result


@app.get("/api/engine")
def api_engine_status() -> Dict[str, Any]:
    return engine.engine_status()


def _pick_folder_native() -> Optional[str]:
    """打开 Windows 原生『浏览文件夹』对话框（Explorer 资源管理器风格），返回绝对路径。

    浏览器 file input 出于安全无法暴露文件夹绝对路径；网页内自建目录树在目录项很多时
    会卡死。故直接调用 Win32 Shell 的 SHBrowseForFolderW（自带消息循环，可在非主线程
    安全弹出），把用户选中的真实绝对路径回填给前端。
    """
    try:
        import ctypes
        from ctypes import wintypes

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        ole32.CoInitialize(None)

        BIF_RETURNONLYFSDIRS = 0x00000001
        BIF_USENEWUI = 0x00000050  # 新版 UI（可新建文件夹/可输入路径）

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [("hwndOwner", wintypes.HWND),
                        ("pidlRoot", ctypes.c_void_p),
                        ("pszDisplayName", ctypes.c_wchar_p),
                        ("lpszTitle", ctypes.c_wchar_p),
                        ("ulFlags", ctypes.c_uint),
                        ("lpfn", ctypes.c_void_p),
                        ("lParam", ctypes.c_long),
                        ("iImage", ctypes.c_int)]

        bi = BROWSEINFO()
        bi.hwndOwner = None
        bi.pidlRoot = None
        bi.lpszTitle = "选择批量处理的本地文件夹"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_USENEWUI

        shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:  # 用户取消
            return None
        buf = ctypes.create_unicode_buffer(4096)
        ok = shell32.SHGetPathFromIDListW(ctypes.c_void_p(pidl), buf)
        ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
        return (buf.value if ok else None) or None
    except Exception as e:
        log.warning("原生文件夹选择对话框打开失败：%s", e)
        return None


@app.post("/api/fs/pick")
def api_fs_pick() -> Dict[str, Any]:
    """弹出 Windows 原生文件夹选择窗口，返回绝对路径（取消则为 null）。

    必须定义为同步 def：由 FastAPI 线程池执行，避免阻塞 asyncio 事件循环导致服务假死。
    """
    path = _pick_folder_native()
    return {"path": path, "cancelled": path is None}


# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# 启动 / GUI 封装（函数化，便于测试与单窗口 GUI 集成）
# ----------------------------------------------------------------------------
def _msgbox(msg: str) -> None:
    """窗口式（无控制台）环境下弹出错误框，避免静默失败。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(msg), "RapidOCR 启动错误", 0x10)
    except Exception:
        pass


def pick_free_port(start: int, host: str, count: int = 12):
    """从 start 起探测连续 count 个端口，返回首个可用端口；全被占用则返回 None。

    注意：探测必须与 uvicorn 使用相同的绑定地址。若 host 为 0.0.0.0（监听全部网卡），
    必须用 0.0.0.0 探测——Windows 上绑定 127.0.0.1 与 0.0.0.0 视为不同地址，
    会导致"已占用却误判为空闲"的端口冲突。
    """
    import socket
    for p in range(start, start + count):
        _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            _s.bind((host, p))
            _s.close()
            return p
        except OSError:
            _s.close()
            continue
    return None


# 服务进程句柄（控制台窗口模式用于 启动/停止）
_SRV = None
_SRV_THREAD = None
_SRV_HOST = "127.0.0.1"
_SRV_PORT = None


def start_service(host: str, default_port: int):
    """启动 uvicorn 服务（后台守护线程），返回实际使用的端口；失败返回 None。

    用 uvicorn.Server 对象管理，便于 停止 时优雅退出（设置 should_exit）。
    """
    global _SRV, _SRV_THREAD, _SRV_HOST, _SRV_PORT
    if _SRV is not None and not _SRV.should_exit and getattr(_SRV, "started", False):
        return _SRV_PORT
    import threading
    import uvicorn

    p = pick_free_port(default_port, host)
    if p is None:
        log.error("从 %d 起连续端口均被占用，无法启动", default_port)
        return None
    if p != default_port:
        log.warning("默认端口 %d 被占用，改用 %d", default_port, p)
    cfg = uvicorn.Config(app, host=host, port=p, log_level="info")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    _SRV = srv
    _SRV_THREAD = t
    _SRV_HOST = host
    _SRV_PORT = p
    return p


def stop_service() -> None:
    """优雅停止服务（设置 should_exit，uvicorn 完成在途请求后退出）。"""
    global _SRV, _SRV_THREAD
    if _SRV is not None:
        try:
            _SRV.should_exit = True
        except Exception:
            pass
    _SRV = None
    _SRV_THREAD = None


def run_control(host: str, default_port: int) -> None:
    """控制台窗口模式（默认 GUI）：一个原生窗口含「启动 / 停止」两个开关。

    - 打开 exe 默认启用：自动启动服务并打开外部浏览器（不在 WebView2 内嵌页面，
      避免配置信息加载异常）。
    - 工作台页面在系统默认浏览器中打开；关闭控制台窗口即退出整个程序。
    - 支持长时间常驻运行（窗口可最小化，服务在后台线程持续运行）。
    """
    import tkinter as tk
    from tkinter import messagebox

    state = {"running": False, "port": None}

    root = tk.Tk()
    root.title("RapidOCR 控制台")
    root.geometry("380x235")
    root.resizable(False, False)

    status_var = tk.StringVar(value="状态：已停止")
    url_var = tk.StringVar(value="工作台地址：—")

    def _url():
        return f"http://{host}:{state['port']}/" if state["port"] else f"http://{host}:{default_port}/"

    def update_status():
        status_var.set("状态：运行中（浏览器已打开）" if state["running"] else "状态：已停止")
        url_var.set("工作台地址：" + _url())
        # 依据运行状态切换 启动/停止/打开网页 三个按钮的可用态
        try:
            if state["running"]:
                btn_start["state"] = "disabled"
                btn_stop["state"] = "normal"
                btn_open["state"] = "normal"
            else:
                btn_start["state"] = "normal"
                btn_stop["state"] = "disabled"
                btn_open["state"] = "disabled"
        except Exception:
            pass

    def do_start():
        if state["running"]:
            return
        p = start_service(host, default_port)
        if p is None:
            messagebox.showerror("RapidOCR", "启动失败：端口可能被占用，详见 rapidocr_app.log")
            return
        state["running"] = True
        state["port"] = p
        _open_browser(host, p)
        update_status()

    def do_stop():
        if not state["running"]:
            return
        stop_service()
        state["running"] = False
        update_status()

    def on_close():
        stop_service()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    tk.Label(root, text="RapidOCR 可视化校对工作台", font=("Microsoft YaHei", 13, "bold")).pack(pady=(14, 6))
    tk.Label(root, textvariable=status_var, font=("Microsoft YaHei", 10)).pack(pady=2)
    url_label = tk.Label(root, textvariable=url_var, font=("Microsoft YaHei", 9),
                         fg="#2c6fbb", cursor="hand2")
    url_label.pack(pady=2)
    url_label.bind("<Button-1>", lambda e: _open_browser(host, state["port"] or default_port))

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=16)
    btn_start = tk.Button(btn_frame, text="启动", width=11, height=1, bg="#3a8d40",
                          fg="white", font=("Microsoft YaHei", 10), command=do_start)
    btn_start.pack(side="left", padx=10)
    btn_stop = tk.Button(btn_frame, text="停止", width=11, height=1, bg="#c0392b",
                         fg="white", font=("Microsoft YaHei", 10), command=do_stop)
    btn_stop.pack(side="left", padx=10)
    btn_open = tk.Button(btn_frame, text="打开网页", width=11, height=1, bg="#2c6fbb",
                         fg="white", font=("Microsoft YaHei", 10),
                         command=lambda: _open_browser(host, state["port"] or default_port))
    btn_open.pack(side="left", padx=10)

    # 创建按钮后先按初始（已停止）状态同步一次按钮可用态
    update_status()

    # 打开 exe 默认启用：自动启动并打开浏览器
    do_start()
    root.mainloop()


def _open_browser(host: str, port: int) -> None:
    """后台打开默认浏览器（旧 server 模式 / GUI 不可用时的回退）。"""
    import threading
    import time
    import webbrowser

    bhost = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{bhost}:{port}/"

    def _o():
        time.sleep(1.5)  # 等待 uvicorn 完成绑定
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_o, daemon=True).start()


def main() -> None:
    import argparse
    import os
    import sys
    import threading
    import time

    parser = argparse.ArgumentParser(description="RapidOCR 可视化校对工作台")
    parser.add_argument("--server", action="store_true",
                        help="无界面后台服务模式（无控制台窗口，自动开外部浏览器，适合远程/无界面场景）")
    parser.add_argument("--gui", action="store_true",
                        help="控制台窗口模式（tkinter 启动/停止，打包 exe 默认；外部浏览器打开工作台）")
    parser.add_argument("--host", default=None, help="绑定地址（默认 0.0.0.0 / 控制台模式 127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="端口（默认 8003）")
    args = parser.parse_args()

    # 运行模式：打包 exe 默认「控制台窗口」；源码运行默认 server（便于看终端日志）。
    # --server 强制无界面；--gui 强制控制台窗口；RAPIDOCR_NO_GUI=1 关闭控制台窗口（退回 server）。
    if args.server:
        mode = "server"
    elif args.gui:
        mode = "control"
    elif getattr(sys, "frozen", False):
        mode = "control" if os.getenv("RAPIDOCR_NO_GUI", "0") != "1" else "server"
    else:
        mode = "server"

    # 控制台窗口模式仅监听本机回环，更安全
    host = args.host or ("127.0.0.1" if mode == "control" else DEFAULT_HOST)
    using_default_port = args.port is None
    port = pick_free_port(args.port or DEFAULT_PORT, host)
    if port is None:
        log.error("从 %d 起连续 %d 个端口均被占用，无法启动", DEFAULT_PORT, 12)
        _msgbox(
            "RapidOCR 无法启动：端口 %d 及后续端口均被占用。\n"
            "请先关闭已运行的 RapidOCR 实例，或设置环境变量 "
            "RAPIDOCR_PORT 更换端口后重试。" % DEFAULT_PORT
        )
        sys.exit(1)
    if using_default_port and port != DEFAULT_PORT:
        log.warning("默认端口 %d 被占用，改用 %d", DEFAULT_PORT, port)

    # 启动后后台下载默认模型（本地/包内均无时），不阻塞启动
    if os.getenv("RAPIDOCR_NO_DOWNLOAD", "0") != "1":
        def _bootstrap_models_thread():
            time.sleep(1.0)
            try:
                from field_understanding import engine as _eng
                _eng.bootstrap_models()
            except Exception as _e:
                log.warning("启动期模型下载失败（可稍后在设置页手动下载）：%s", _e)
        threading.Thread(target=_bootstrap_models_thread, daemon=True).start()

    if mode == "control":
        # 控制台窗口：tkinter 启动/停止；打开 exe 默认启用（run_control 内自动启动并开浏览器）
        run_control(host, port)
    else:
        # 无界面服务模式：主线程跑 uvicorn，自动开浏览器（远程/无界面场景）
        if os.getenv("RAPIDOCR_NO_BROWSER", "0") != "1":
            _open_browser(host, port)
        import uvicorn
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
