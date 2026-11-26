# -*- coding: utf-8 -*-
"""可选 DeepSeek 适配器（OpenAI-compatible HTTP）。

默认不依赖 LLM：没有 DEEPSEEK_API_KEY 时自动回退规则。
LLM 只做两件事：
    1) 从 brief 补充理解（软字段；硬字段仍走规则 + 引擎校验）
    2) 润色提案话术（必须通过数字守卫与合规守卫）

配置（优先级：显式参数 > 环境变量 > 根目录 .env）：
    DEEPSEEK_API_KEY    必填（只有调用 LLM 时需要）
    DEEPSEEK_MODEL      可选，默认 deepseek-chat
    DEEPSEEK_BASE_URL   可选，默认 https://api.deepseek.com

本地开发直接把 Key 放在项目根目录的 .env（已 gitignore）：
    DEEPSEEK_API_KEY=sk-...
这样不用每次设置环境变量，又不会把 Key 提交进仓库。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class NullLLM:
    """无 LLM 模式：接口存在，但永远返回 None，调用方回退规则。"""

    available = False

    def __init__(self, reason: str = "LLM 未启用") -> None:
        self.reason = reason
        self.last_error: Optional[str] = None

    def extract_brief(self, text: str, schema: Dict[str, Any], prompt: str) -> Optional[Dict[str, Any]]:
        return None

    def polish_narrative(self, markdown: str, payload: Dict[str, Any], prompt: str) -> Optional[str]:
        return None

    def describe(self) -> Dict[str, Any]:
        return {"provider": "none", "available": False, "reason": self.reason}


class DeepSeekLLM:
    """DeepSeek 的最小适配器；懒加载 httpx，不拖慢离线启动。"""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Any = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or _dotenv_key()
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._client = client
        self.last_error: Optional[str] = None
        self.available = False
        self.reason = ""
        if not self.api_key:
            self.reason = "未配置 DEEPSEEK_API_KEY"
            return
        try:
            import httpx  # noqa: F401
        except Exception as exc:  # pragma: no cover - httpx 已在 requirements
            self.reason = f"httpx 不可用：{type(exc).__name__}"
            return
        self.available = True
        self.reason = "ok"

    # ------------------------------------------------------------------ #
    def extract_brief(self, text: str, schema: Dict[str, Any], prompt: str) -> Optional[Dict[str, Any]]:
        if not self.available or not text.strip():
            return None
        system = (
            f"{prompt}\n\n"
            "必须只输出一个 JSON 对象，不要 Markdown 代码块，不要解释。\n"
            f"JSON Schema：{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
        )
        content = self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            max_tokens=2000,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        if not content:
            return None
        data = _parse_json(content)
        return data if isinstance(data, dict) else None

    def polish_narrative(self, markdown: str, payload: Dict[str, Any], prompt: str) -> Optional[str]:
        if not self.available:
            return None
        context = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        user = (
            "下面是确定性引擎生成的分析结果（JSON）和当前提案草稿。"
            "请在不新增数字、不改变结论的前提下润色为更自然的中文提案话术。\n\n"
            f"<analysis>{context}</analysis>\n\n<draft>\n{markdown}\n</draft>"
        )
        content = self._chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ],
            max_tokens=4000,
            temperature=0.2,
        )
        return content.strip() if content else None

    # ------------------------------------------------------------------ #
    def _chat(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.available:
            return None
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                client = self._get_client()
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    self.last_error = "DeepSeek 返回空 choices"
                    return None
                message = choices[0].get("message") or {}
                content = message.get("content")
                if not isinstance(content, str) or not content.strip():
                    self.last_error = "DeepSeek 返回空 content"
                    return None
                self.last_error = None
                return content
            except Exception as exc:  # pragma: no cover - 外部服务异常
                last_exc = exc
                self.last_error = f"{type(exc).__name__}: {exc}"
                # 连接/SSL 瞬断时重置连接池并短暂重试，避免首次握手偶发 EOF
                if attempt < 2 and type(exc).__name__ in ("ConnectError", "ReadError", "RemoteProtocolError", "WriteError", "PoolTimeout"):
                    try:
                        if self._client is not None:
                            self._client.close()
                    except Exception:
                        pass
                    self._client = None
                    import time
                    time.sleep(0.35 * (attempt + 1))
                    continue
                return None
        if last_exc:
            self.last_error = f"{type(last_exc).__name__}: {last_exc}"
        return None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def describe(self) -> Dict[str, Any]:
        out = {
            "provider": "deepseek",
            "model": self.model,
            "base_url": self.base_url,
            "available": self.available,
            "reason": self.reason,
        }
        if self.last_error:
            out["last_error"] = self.last_error
        return out


def _parse_json(content: str) -> Optional[Dict[str, Any]]:
    text = content.strip()
    # 容错：模型偶尔仍会包 ```json ... ```
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 再尝试截取第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _dotenv_key(name: str = "DEEPSEEK_API_KEY") -> Optional[str]:
    """读取项目根目录 .env（已 gitignore）；缺失/格式不对时静默回退。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != name:
                    continue
                value = value.strip().strip('"').strip("'")
                return value or None
    except OSError:
        return None
    return None


def build_llm(mode: str = "auto", model: Optional[str] = None) -> Any:
    """auto → 有 Key 就用 DeepSeek，否则 NullLLM；off → 强制规则。"""
    mode = (mode or "auto").lower()
    if mode in ("off", "none", "false", "0"):
        return NullLLM("LLM 已关闭")
    return DeepSeekLLM(model=model)


__all__ = ["NullLLM", "DeepSeekLLM", "build_llm", "DEFAULT_MODEL", "DEFAULT_BASE_URL"]
