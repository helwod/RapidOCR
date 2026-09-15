"""RapidOCR 引擎管理：设置、模型目录、模型下载、模型选择、热重载。

完全离线友好：
- 识别阶段不依赖外网；首个模型在应用启动后由后台线程自动下载（也可在设置页手动下载，
  或离线环境手动把 onnx 放到 models/<engine>/<ocr_version>/<task>/ 下直接使用）。
- 默认选用 PP-OCRv6 中文模型（det/rec 用 PP-OCRv6 small，cls 用 PP-OCRv4 mobile）。
- 模型选择：从本地已下载的 onnx 模型中挑选 det/rec/cls 组合，生成 runtime 配置并重建 RapidOCR。
- 模型下载：从 RapidOCR 官方 ModelScope 仓库拉取指定 onnx 模型到本地 models/ 目录，并做 SHA256 校验。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import urllib.request
from typing import Any, Dict, List, Optional

# 项目根目录。
# 开发态：取 field_understanding 的上级目录（项目根）。
# 冻结态（PyInstaller 单目录）：取 exe 所在目录，与 app.py 的 EXE_DIR 保持一致，
# 使 models/、settings.json 等下载产物落在用户可见的 exe 同级目录，而非 _internal。
def _resolve_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _resolve_root()
MODELS_DIR = os.path.join(ROOT, "models")
SETTINGS_PATH = os.path.join(ROOT, "settings.json")
RUNTIME_CFG = os.path.join(MODELS_DIR, "runtime_config.yaml")
os.makedirs(MODELS_DIR, exist_ok=True)

from omegaconf import OmegaConf  # rapidocr 依赖，必存在

from rapidocr import RapidOCR
import rapidocr as _ro_pkg

_ro_pkg_dir = os.path.dirname(_ro_pkg.__file__)
DEFAULT_CFG = os.path.join(_ro_pkg_dir, "config.yaml")
DEFAULT_MODELS_YAML = os.path.join(_ro_pkg_dir, "default_models.yaml")

# 仅暴露已安装的 onnxruntime 引擎模型（其余引擎未安装，列出来也用不了）
SUPPORTED_ENGINES = ("onnxruntime",)

# 由模型名前缀推导 lang_type（识别字典按此选择）
LANG_MAP = {
    "ch": "ch", "multi": "ch", "en": "en", "korean": "korean", "japan": "japan",
    "ka": "ka", "latin": "latin", "cyrillic": "cyrillic", "devanagari": "devanagari",
    "arabic": "arabic", "chinese": "chinese_cht", "ta": "ta", "te": "te",
    "th": "th", "el": "el", "eslav": "eslav",
}
_MODEL_TYPES = ("tiny", "medium", "mobile", "server", "small")

# 模型库远程仓库（ModelScope）页面，供前端"远程查看"链接跳转
MODEL_REPO_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR"

_TASK_DESC = {
    "det": "文本检测：定位图像中文字区域，输出文本框包围框。",
    "rec": "文本识别：将检测到的文字区域图像转为字符序列。",
    "cls": "方向分类：判断文本行朝向，纠正 180° 旋转，提升识别准确率。",
}
_LANG_DESC = {
    "ch": "中文", "en": "英文", "korean": "韩文", "japan": "日文", "ka": "卡纳达文",
    "latin": "拉丁字母", "cyrillic": "西里尔字母", "devanagari": "梵文", "arabic": "阿拉伯文",
    "chinese_cht": "繁体中文", "ta": "泰米尔文", "te": "泰卢固文", "th": "泰文",
    "el": "希腊文", "eslav": "东欧斯拉夫文", "multi": "多语种（中+英+常用）",
}
_VERSION_DESC = {
    "PP-OCRv4": "PP-OCRv4：成熟稳定，社区资源最丰富，中英文效果均衡。",
    "PP-OCRv5": "PP-OCRv5：多语种覆盖更广、鲁棒性更强，新增 server 大模型。",
    "PP-OCRv6": "PP-OCRv6：最新一代，结构更优，模型体积小、推理快、精度高（本工具默认）。",
}
_TYPE_DESC = {
    "tiny": "tiny：体积最小、速度最快，精度略低。",
    "small": "small：体积与精度均衡，推荐日常使用。",
    "medium": "medium：精度更高，体积与算力需求更大。",
    "mobile": "mobile：面向移动/端侧优化的轻量模型。",
    "server": "server：服务端大模型，精度最高，算力需求大。",
}
_TYPE_SHORT = {
    "tiny": "tiny·最小",
    "small": "small·均衡",
    "medium": "medium·高精度",
    "mobile": "mobile·端侧",
    "server": "server·大模型",
}

# 各模型真实文件大小（字节），一次性从 ModelScope 抓取后固化，离线可读。
# 本地已下载模型优先用磁盘真实大小覆盖此值。
MODEL_SIZES = {
    'ch_PP-OCRv4_det_mobile': 4745517,
    'ch_PP-OCRv4_det_server': 113352104,
    'en_PP-OCRv3_det_mobile': 2421707,
    'multi_PP-OCRv3_det_mobile': 2421639,
    'arabic_PP-OCRv4_rec_mobile': 7685206,
    'ch_PP-OCRv4_rec_mobile': 10857958,
    'ch_PP-OCRv4_rec_server': 90530732,
    'ch_doc_PP-OCRv4_rec_server': 94927308,
    'chinese_cht_PP-OCRv3_rec_mobile': 11152536,
    'cyrillic_PP-OCRv3_rec_mobile': 8972413,
    'devanagari_PP-OCRv4_rec_mobile': 7688213,
    'en_PP-OCRv4_rec_mobile': 7653044,
    'japan_PP-OCRv4_rec_mobile': 9753335,
    'ka_PP-OCRv4_rec_mobile': 7681381,
    'korean_PP-OCRv4_rec_mobile': 24067780,
    'latin_PP-OCRv3_rec_mobile': 8978191,
    'ta_PP-OCRv4_rec_mobile': 22330612,
    'te_PP-OCRv4_rec_mobile': 22341821,
    'ch_ppocr_mobile_v2.0_cls_mobile': 585532,
    'ch_PP-OCRv5_det_mobile': 4819576,
    'ch_PP-OCRv5_det_server': 88118768,
    'ch_PP-OCRv5_rec_mobile': 16631306,
    'ch_PP-OCRv5_rec_server': 84577022,
    'korean_PP-OCRv5_rec_mobile': 13488748,
    'latin_PP-OCRv5_rec_mobile': 7904513,
    'eslav_PP-OCRv5_rec_mobile': 7911802,
    'en_PP-OCRv5_rec_mobile': 7872351,
    'th_PP-OCRv5_rec_mobile': 7915294,
    'el_PP-OCRv5_rec_mobile': 7832350,
    'arabic_PP-OCRv5_rec_mobile': 8023828,
    'cyrillic_PP-OCRv5_rec_mobile': 8074092,
    'devanagari_PP-OCRv5_rec_mobile': 7940361,
    'ta_PP-OCRv5_rec_mobile': 7909926,
    'te_PP-OCRv5_rec_mobile': 7923102,
    'ch_PP-LCNet_x0_25_textline_ori_cls_mobile': 1018508,
    'ch_PP-LCNet_x1_0_textline_ori_cls_server': 6776876,
    'multi_PP-OCRv6_det_tiny': 1829618,
    'multi_PP-OCRv6_det_small': 9929594,
    'multi_PP-OCRv6_det_medium': 62119454,
    'multi_PP-OCRv6_rec_tiny': 4489813,
    'multi_PP-OCRv6_rec_small': 21234383,
    'multi_PP-OCRv6_rec_medium': 76629984,
}

# 各版本一句话说明，展示在模型库版本分组下方
VERSION_NOTE = {
    "PP-OCRv4": "第4代：成熟稳定，社区资源最丰富，中英文效果均衡，模型体积适中。",
    "PP-OCRv5": "第5代：多语种覆盖更广、鲁棒性更强，新增 server 大模型，精度更高。",
    "PP-OCRv6": "第6代（默认）：结构优化，模型体积小、推理快、精度高，推荐新项目使用。",
}


def describe_model(c: Dict[str, Any]) -> str:
    """生成模型的中文说明（任务 + 版本 + 语种 + 档位）。"""
    parts = [
        _TASK_DESC.get(c["task"], ""),
        _VERSION_DESC.get(c["ocr_version"], ""),
        f"语种：{_LANG_DESC.get(c['lang_type'], c['lang_type'])}。",
        _TYPE_DESC.get(c["model_type"], ""),
    ]
    return "".join(p for p in parts if p)


def _parse_name(name: str):
    """从模型名推导 (lang_type, model_type)。"""
    first = name.split("_")[0]
    lang = LANG_MAP.get(first, "ch")
    mt = "small"
    low = name.lower()
    for cand in _MODEL_TYPES:
        if low.endswith(cand):
            mt = cand
            break
    return lang, mt


def load_catalog() -> List[Dict[str, Any]]:
    """解析 default_models.yaml，生成可用模型目录（仅 onnxruntime）。"""
    raw = OmegaConf.load(DEFAULT_MODELS_YAML)
    catalog: List[Dict[str, Any]] = []
    for eng in SUPPORTED_ENGINES:
        if eng not in raw:
            continue
        for ocrv, tasks in raw[eng].items():
            for task, models in tasks.items():  # det / rec / cls
                for mname, info in models.items():
                    url = info.get("model_dir")
                    if not url:
                        continue
                    lang, mt = _parse_name(mname)
                    cid = f"{eng}/{ocrv}/{task}/{mname}"
                    lp = os.path.join(MODELS_DIR, eng, ocrv, task, mname + ".onnx")
                    size = os.path.getsize(lp) if os.path.isfile(lp) else MODEL_SIZES.get(mname)
                    entry = {
                        "id": cid,
                        "engine": eng,
                        "ocr_version": ocrv,
                        "task": task,
                        "name": mname,
                        "url": url,
                        "sha256": info.get("SHA256"),
                        "lang_type": lang,
                        "model_type": mt,
                        "lang_label": _LANG_DESC.get(lang, lang),
                        "type_label": _TYPE_SHORT.get(mt, mt),
                        "size": size,
                        "repo_url": MODEL_REPO_URL,
                    }
                    entry["desc"] = describe_model(entry)
                    catalog.append(entry)
    return catalog


CATALOG = load_catalog()
CATALOG_BY_ID = {c["id"]: c for c in CATALOG}


def local_path(cid: str) -> str:
    c = CATALOG_BY_ID[cid]
    return os.path.join(MODELS_DIR, c["engine"], c["ocr_version"], c["task"], c["name"] + ".onnx")


def is_local(cid: str) -> bool:
    return os.path.isfile(local_path(cid))


# --------------------------------------------------------------------------
# 设置（持久化到 settings.json）
# --------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "inference": {
        "use_det": True, "use_cls": True, "use_rec": True,
        "text_score": 0.5,
        "intra_op_num_threads": -1, "inter_op_num_threads": -1,
    },
    "selected": {"det": None, "rec": None, "cls": None},
}


def load_settings() -> Dict[str, Any]:
    if os.path.isfile(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                s = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            for k in DEFAULT_SETTINGS:
                if isinstance(DEFAULT_SETTINGS[k], dict):
                    merged[k] = {**DEFAULT_SETTINGS[k], **(s.get(k) or {})}
                else:
                    merged[k] = s.get(k, DEFAULT_SETTINGS[k])
            return merged
        except Exception:
            pass
    return {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_SETTINGS.items()}


def save_settings(s: Dict[str, Any]) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


settings = load_settings()


# --------------------------------------------------------------------------
# 引擎实例（延迟初始化 + 缓存 + 线程安全）
# --------------------------------------------------------------------------
_engine = None
_engine_error: Optional[str] = None
_engine_lock = threading.Lock()


def build_runtime_config() -> str:
    """基于默认 config.yaml 覆盖所选模型与推理参数，写出 runtime_config.yaml。"""
    base = OmegaConf.load(DEFAULT_CFG)
    inf = settings["inference"]
    sel = settings["selected"]

    base.Global.text_score = float(inf.get("text_score", 0.5))
    base.Global.use_det = bool(inf.get("use_det", True))
    base.Global.use_cls = bool(inf.get("use_cls", True))
    base.Global.use_rec = bool(inf.get("use_rec", True))

    if "onnxruntime" in base.EngineConfig:
        ec = base.EngineConfig.onnxruntime
        if "intra_op_num_threads" in ec:
            ec.intra_op_num_threads = int(inf.get("intra_op_num_threads", -1))
        if "inter_op_num_threads" in ec:
            ec.inter_op_num_threads = int(inf.get("inter_op_num_threads", -1))

    for task, key in (("det", "Det"), ("rec", "Rec"), ("cls", "Cls")):
        node = getattr(base, key)
        cid = sel.get(task)
        if cid and is_local(cid):
            c = CATALOG_BY_ID[cid]
            node.model_path = local_path(cid)
            node.lang_type = c["lang_type"]
            node.ocr_version = c["ocr_version"]
            node.model_type = c["model_type"]
            node.task_type = task
            node.engine_type = c["engine"]
        else:
            node.model_path = None  # 回退到包内默认捆绑模型

    OmegaConf.save(config=base, f=RUNTIME_CFG)
    return RUNTIME_CFG


def get_engine(force_reload: bool = False) -> Any:
    global _engine, _engine_error
    with _engine_lock:
        if _engine is not None and not force_reload:
            return _engine
        cfg = build_runtime_config()
        _engine = RapidOCR(config_path=cfg)
        _engine_error = None
        return _engine


def reload_engine() -> Any:
    global _engine
    _engine = None
    return get_engine(force_reload=True)


def engine_status() -> Dict[str, Any]:
    """返回当前引擎状态（不一定已初始化）。"""
    ready = _engine is not None and _engine_error is None
    sel = settings["selected"]
    resolved = {}
    for task in ("det", "rec", "cls"):
        cid = sel.get(task)
        if cid and is_local(cid):
            resolved[task] = CATALOG_BY_ID[cid]["name"]
        else:
            resolved[task] = "默认捆绑模型"
    return {
        "ready": ready,
        "error": _engine_error,
        "selected": sel,
        "resolved": resolved,
        "inference": settings["inference"],
    }


# --------------------------------------------------------------------------
# 模型下载
# --------------------------------------------------------------------------
def download_model(cid: str, progress_cb=None) -> Dict[str, Any]:
    """下载指定模型到本地 models/ 目录，并校验 SHA256。"""
    if cid not in CATALOG_BY_ID:
        return {"id": cid, "ok": False, "error": "未知模型 id"}
    c = CATALOG_BY_ID[cid]
    dest = local_path(cid)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(c["url"], headers={"User-Agent": "RapidOCR-UI/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            got = 0
            sha = hashlib.sha256()
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    got += len(chunk)
                    if progress_cb:
                        progress_cb(got, total)
        digest = sha.hexdigest()
        sha_ok = (c["sha256"] is None) or (digest.lower() == c["sha256"].lower())
        shutil.move(tmp, dest)
        return {
            "id": cid, "ok": True, "size": got, "sha_ok": sha_ok,
            "sha_expected": c["sha256"], "sha_actual": digest,
            "name": c["name"],
        }
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return {"id": cid, "ok": False, "error": str(e), "name": c["name"]}


# --------------------------------------------------------------------------
# 预设组合（onnxruntime / 中文默认 / 内部一致）
# --------------------------------------------------------------------------
PRESETS = [
    {
        "id": "ppocrv6_zh",
        "name": "PP-OCRv6 中文（默认）",
        "selected": {
            "det": "onnxruntime/PP-OCRv6/det/multi_PP-OCRv6_det_small",
            "rec": "onnxruntime/PP-OCRv6/rec/multi_PP-OCRv6_rec_small",
            "cls": "onnxruntime/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile",
        },
    },
    {
        "id": "ppocrv4_zh",
        "name": "PP-OCRv4 中文",
        "selected": {
            "det": "onnxruntime/PP-OCRv4/det/ch_PP-OCRv4_det_mobile",
            "rec": "onnxruntime/PP-OCRv4/rec/ch_PP-OCRv4_rec_mobile",
            "cls": "onnxruntime/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile",
        },
    },
    {
        "id": "ppocrv5_zh",
        "name": "PP-OCRv5 中文",
        "selected": {
            "det": "onnxruntime/PP-OCRv5/det/ch_PP-OCRv5_det_mobile",
            "rec": "onnxruntime/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile",
            "cls": "onnxruntime/PP-OCRv5/cls/ch_PP-LCNet_x0_25_textline_ori_cls_mobile",
        },
    },
    {
        "id": "ppocrv4_en",
        "name": "PP-OCRv4 英文",
        "selected": {
            "det": "onnxruntime/PP-OCRv4/det/en_PP-OCRv3_det_mobile",
            "rec": "onnxruntime/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile",
            "cls": "onnxruntime/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile",
        },
    },
]
PRESET_BY_ID = {p["id"]: p for p in PRESETS}

def bootstrap_models() -> None:
    """启动期模型引导：若所需模型在本地/包内均不存在，则自动下载到运行期 models/ 目录。

    仅下载当前选定（或默认 PP-OCRv6 中文预设）的 det/rec/cls 模型；已存在则跳过。
    离线环境可手动把 onnx 放到 MODELS_DIR 下对应路径，或设 RAPIDOCR_NO_DOWNLOAD=1 关闭。
    """
    import logging
    _log = logging.getLogger("rapidocr.engine")
    sels = settings.get("selected", {})
    needed = {}
    for _task in ("det", "rec", "cls"):
        _cid = sels.get(_task) or PRESET_BY_ID["ppocrv6_zh"]["selected"][_task]
        needed[_task] = _cid
    _changed = False
    for _task, _cid in needed.items():
        if is_local(_cid):
            if sels.get(_task) != _cid:
                sels[_task] = _cid
                _changed = True
            continue
        try:
            _res = download_model(_cid)
            if _res.get("ok"):
                sels[_task] = _cid
                _changed = True
                _log.info("启动下载模型成功：%s（%d 字节）", _cid, _res.get("size", 0))
            else:
                _log.warning("启动下载模型失败：%s -> %s", _cid, _res.get("error"))
        except Exception as _e:
            _log.warning("启动下载模型异常：%s -> %s", _cid, _e)
    if _changed:
        try:
            save_settings(settings)
            reload_engine()
        except Exception as _e:
            _log.warning("模型就绪后引擎重载失败（将于首次识别时重试）：%s", _e)

