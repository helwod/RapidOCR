# RapidOCR 安装部署与使用说明

> 基于 https://github.com/RapidAI/RapidOCR/tree/main
> 本工作区（C:\Users\Administrator\WorkBuddy\RapidOCR）已实测通过：Python API、CLI 均跑通，模型本地打包、可离线运行。

## 1. 项目简介

RapidOCR 是完全开源、免费的 OCR 工具箱，基于 PaddleOCR 模型转换为 ONNX 格式，支持多平台、多语言与快速离线部署。

- 默认支持：中文、英文（其他语言见官方 Model List）
- 核心优势：极致速度、低资源消耗、跨平台（Python / C++ / Java / C#）
- 本仓库仅含 Python 组件；其他语言组件已迁移至独立仓库
- 许可：源码 Apache-2.0；模型源自 PaddleOCR，同许可再分发

## 2. 环境要求

| 项 | 要求 |
| --- | --- |
| Python | >= 3.8（本工作区实测 3.13.14） |
| 操作系统 | Windows / Linux / macOS |
| 推理引擎 | onnxruntime（CPU 即可；可选 GPU / TensorRT / OpenVINO 等） |
| 网络 | 首次安装需联网拉包；模型已随包本地打包，**识别阶段可完全离线** |

## 3. 安装（已在本工作区验证）

本工作区已建立隔离虚拟环境 `.venv`，实测版本：`rapidocr 3.9.2` + `onnxruntime 1.29.0`。

通用安装命令：

```bash
pip install rapidocr onnxruntime
```

如需 GPU / TensorRT / OpenVINO 加速，替换为对应包，例如：

```bash
pip install rapidocr onnxruntime-gpu      # NVIDIA GPU
pip install rapidocr openvino             # Intel OpenVINO
```

本工作区复现步骤（可忽略，已就绪）：

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install rapidocr onnxruntime
```

## 4. 三种使用方式

### 4.1 Python API（推荐，最灵活）

```python
from rapidocr import RapidOCR

engine = RapidOCR()                      # 首次加载本地模型，秒级
result = engine("test_ocr.png")          # 支持 本地路径 / URL / numpy 数组

print(result.txts)                       # 识别文本列表
print(result.boxes)                      # 检测框坐标
print(result.scores)                     # 置信度
result.vis("vis_result.jpg")             # 可视化（离线环境可注释此行）
```

实测输出（本工作区 `test_ocr.png`）：

```
TXTS:   ('RapidOCR 中文识别测试 Hello 2026', '完全离线部署OCR 工具箱')
SCORES: [0.994, 0.986]
```

`engine()` 返回 `RapidOCROutput` 数据类，可直接访问 `.boxes` / `.txts` / `.scores` 做二次开发。

### 4.2 命令行 CLI

```bash
rapidocr -img "test_ocr.png" --vis_res
```

| 参数 | 说明 |
| --- | --- |
| `-img` | 图片路径或 URL |
| `--vis_res` | 生成可视化结果图 |

### 4.3 Web API 服务（FastAPI + uvicorn）

```bash
pip install rapidocr_api
rapidocr_api -ip 0.0.0.0 -p 9003 -workers 2   # 默认演示端口 9003
```

- 接口文档：http://localhost:9003/docs
- OCR 接口：POST http://localhost:9003/ocr

```bash
curl -F image_file=@1.png http://localhost:9003/ocr
```

可选模型路径（环境变量）：`det_model_path` / `rec_model_path` / `cls_model_path`

### 4.4 Web UI（可视化界面）

```bash
pip install rapidocr_web
rapidocr_web -ip 0.0.0.0 -p 9003
```

浏览器打开（注意是 `http` 非 `https`）：

```
http://localhost:9003/
```

## 5. 模型说明（离线关键）

- 模型文件随 `rapidocr` 包本地打包，位于：
  `.venv/Lib/site-packages/rapidocr/models/`
  （实测含 `PP-OCRv6_det_small.onnx`、`PP-OCRv6_rec_small.onnx`、`ch_ppocr_mobile_v2.0_cls_mobile.onnx`）
- 首次运行无需联网下载，满足**气隙 / 离线部署**需求
- 如需自定义模型：基于 PaddleOCR 微调后替换上述 ONNX 文件，或通过环境变量指定路径

## 6. Docker 部署

仓库提供 7 种推理引擎的开发/部署镜像（onnxruntime-cpu、onnxruntime-gpu、tensorrt、paddle、openvino、pytorch、mnn），通过 `make` + `docker-compose.yaml` 统一管理，模型以命名卷 `rapidocr-models` 持久化。

```bash
make build-onnxruntime-cpu     # 构建（CPU）
make test-onnxruntime-cpu      # 测试
make shell-tensorrt            # 进入 TensorRT 开发容器
```

GPU 配置与排错见仓库 `docker/README.md`。

## 7. 结果结构（二次开发）

| 字段 | 含义 |
| --- | --- |
| `result.boxes` | 检测框坐标（numpy 数组，shape: [N,4,2]） |
| `result.txts` | 识别文本（tuple / list，长度 N） |
| `result.scores` | 置信度（长度 N） |

## 8. 本工作区验证结果

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 虚拟环境 | 就绪 | `.venv`（Python 3.13.14） |
| pip 安装 | 成功 | rapidocr 3.9.2 + onnxruntime 1.29.0 |
| Python API | 成功 | 双行文本识别，置信度 0.994 / 0.986 |
| CLI | 成功 | `rapidocr -img ... --vis_res` |
| 离线能力 | 确认 | 模型本地打包，识别阶段无外网请求 |
| 可视化 | 成功 | 产出 `vis_result.jpg` |

## 9. 常见问题

| 问题 | 处理 |
| --- | --- |
| 首次运行卡在下载 | 当前版本模型已本地打包，正常秒级加载；老版本会首次联网下载，需保障网络 |
| `result.vis()` 报错字体 | 离线环境可视化会自动下载字体，可注释该行仅取文本 |
| 需要更高精度 | 用 `PP-OCRv4_server` 系列模型替换 small 模型，或换 GPU / TensorRT |
| 中文识别不准 | 确保使用默认中文模型；custom 场景用 PaddleOCR 微调后替换 ONNX |
| 多进程部署 | API 服务用 `-workers` 调整进程数，配合 GPU 提升吞吐 |

## 10. 相关资源

- 官方文档：https://rapidai.github.io/RapidOCRDocs/
- 在线 Demo：HuggingFace / 魔搭 ModelScope 均提供 RapidOCRv3
- 源码与 LICENSE：https://github.com/RapidAI/RapidOCR
