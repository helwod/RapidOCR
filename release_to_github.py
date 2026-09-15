# -*- coding: utf-8 -*-
"""发布到 GitHub Releases：创建 Release 并上传 exe 压缩包。

凭据取自本机 Git Credential Manager（与 push 用的同一凭据），不在输出中打印。
用法：.venv/Scripts/python.exe release_to_github.py [tag]
"""
import hashlib
import json
import os
import subprocess
import sys

import requests

OWNER, REPO = "helwod", "RapidOCR"
TAG = sys.argv[1] if len(sys.argv) > 1 else "v1.0.0"
ZIP_PATH = os.path.join("release", "RapidOCR-Desktop-v1.0.0-win64.zip")
ASSET_NAME = "RapidOCR-Desktop-v1.0.0-win64.zip"


def get_token() -> str:
    """从 Git Credential Manager 取本机缓存的 GitHub 凭据。"""
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=False,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    sys.exit("未能从 git credential 取到 GitHub 凭据")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not os.path.isfile(ZIP_PATH):
        sys.exit("未找到压缩包：%s" % ZIP_PATH)

    token = get_token()
    auth = {"Authorization": "token %s" % token, "Accept": "application/vnd.github+json"}
    api = "https://api.github.com/repos/%s/%s/releases" % (OWNER, REPO)

    size_mb = os.path.getsize(ZIP_PATH) / 1024 / 1024
    digest = sha256(ZIP_PATH)
    print("zip : %.1f MB  sha256=%s" % (size_mb, digest))

    body = """## RapidOCR 身份证识别工作台 %s

**离线身份证识别桌面工具**：拖一张身份证图片，自动抽取「姓名 / 性别 / 民族 / 出生 / 住址 / 公民身份号码」，并做异常校验与可视化对照。识别全程离线，数据不出本机。

### 下载
下载下方 `{asset}`，**解压到任意目录（建议路径不含空格）**，双击 `RapidOCR桌面工具.exe` 即可。

- 压缩包**已内置 OCR 模型**（约 31MB），解压即用，**首次启动无需联网**
- 环境要求：Windows 10/11 x64；若缺运行库请先装 微软 Visual C++ 2019 可再发行组件（vc_redist.x64）

### 主要功能
- **身份证字段抽取**：六字段结构化输出，字段来源可追溯（规则 / LLM / 人工编辑）
- **识别异常校验**：MOD 11-2 校验位、出生日期与身份证内嵌日期一致性、性别与顺序码奇偶、姓名合法性、关键字段缺失
- **未知类型闸门**：非身份证图片判为未知并留空字段，**绝不编造身份证号**
- **可视化对照**：原图与检测标注并排，底部条带展示抽取结果
- **批量识别**：「浏览…」调 Windows 原生文件夹窗口选目录，带**实时进度**（已处理 x/N + 当前文件名），结果可筛选「仅看识别异常」
- **人工校对留痕**：字段可编辑重校验，记录持久化并支持导出 CSV
- **控制台窗口**：打开 exe 默认启动、自动开浏览器；启动/停止按钮按状态互斥置灰；可最小化常驻长时间运行

### 文件完整性校验
```
SHA256: {digest}
```

完整说明见仓库 [README](https://github.com/helwod/RapidOCR#readme)。
""".replace("{asset}", ASSET_NAME).replace("{digest}", digest)

    # 已存在同名 Release 则复用，否则创建
    rid = None
    r = requests.get("%s/tags/%s" % (api, TAG), headers=auth, timeout=60)
    if r.status_code == 200:
        rid = r.json()["id"]
        print("reuse existing release id=%s" % rid)
    else:
        payload = {"tag_name": TAG, "name": "RapidOCR 身份证识别工作台 %s" % TAG,
                   "body": body, "draft": False, "prerelease": False}
        r = requests.post(api, headers=auth, data=json.dumps(payload), timeout=60)
        if r.status_code not in (200, 201):
            sys.exit("创建 Release 失败 %s: %s" % (r.status_code, r.text[:400]))
        rid = r.json()["id"]
        print("release created id=%s" % rid)

    # 同名资产先删除，便于重复执行
    assets = requests.get("%s/%s/assets" % (api, rid), headers=auth, timeout=60).json()
    for a in assets:
        if a["name"] == ASSET_NAME:
            print("remove old asset id=%s" % a["id"])
            requests.delete("%s/assets/%s" % (api, a["id"]), headers=auth, timeout=60)

    print("uploading %.1f MB ..." % size_mb)
    up = "https://uploads.github.com/repos/%s/%s/releases/%s/assets" % (OWNER, REPO, rid)
    headers = {"Authorization": "token %s" % token,
               "Accept": "application/vnd.github+json",
               "Content-Type": "application/zip"}
    with open(ZIP_PATH, "rb") as f:
        r = requests.post(up, headers=headers, params={"name": ASSET_NAME},
                          data=f, timeout=1800)
    if r.status_code not in (200, 201):
        sys.exit("上传资产失败 %s: %s" % (r.status_code, r.text[:400]))

    print("UPLOAD OK")
    print("release: https://github.com/%s/%s/releases/tag/%s" % (OWNER, REPO, TAG))
    print("asset  : %s (%.1f MB)" % (r.json()["name"],
                                     r.json()["size"] / 1024 / 1024))


if __name__ == "__main__":
    main()
