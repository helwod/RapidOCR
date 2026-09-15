"""可插拔的大模型客户端（OpenAI 兼容接口）。

默认 disabled + mock：离线环境下直接返回空，规则层独立工作。
启用后指向本地 airllm / vLLM 等 OpenAI 兼容端点即可，不依赖公网。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


class LLMClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "qwen2.5-7b",
        api_key: str = "EMPTY",
        enabled: bool = False,
    ) -> None:
        self.base_url = base_url or os.getenv("RAPIDOCR_LLM_BASE_URL")
        self.model = model or os.getenv("RAPIDOCR_LLM_MODEL", "qwen2.5-7b")
        self.api_key = api_key or os.getenv("RAPIDOCR_LLM_API_KEY", "EMPTY")
        self.enabled = enabled and bool(self.base_url)

    def extract(
        self,
        ocr_text: str,
        schema_hint: str,
        existing: Dict[str, Any],
    ) -> Dict[str, Any]:
        """对规则层已抽取、仍缺失或低置信的字段，调用 LLM 补全。

        - disabled（默认）或端点不可达：返回 {}，由规则层兜底。
        - 返回 dict：{字段名: 值}，仅填充有把握的字段。
        """
        if not self.enabled:
            return {}
        prompt = (
            "你是文档字段抽取助手。下面是 OCR 得到的文本，以及规则已识别的字段。\n"
            "请只补充规则未识别出的字段，输出 JSON（不要解释）。\n"
            f"目标字段：{schema_hint}\n"
            f"规则已识别：{json.dumps(existing, ensure_ascii=False)}\n"
            f"OCR 全文：\n{ocr_text}\n"
        )
        try:
            import requests

            resp = requests.post(
                f"{self.base_url.rstrip('/')}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:  # 任意失败都降级到规则层
            print(f"[LLM] 调用失败，降级规则层: {exc}")
            return {}
