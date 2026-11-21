# -*- coding: utf-8 -*-
"""可选 DeepSeek 适配器的形状测试（不联网、不依赖真实 API Key）。

用假 HTTP client 验证：
- 有 Key 时 available=True；
- extract_brief 走 OpenAI-compatible /chat/completions + response_format=json_object；
- polish_narrative 不带 response_format，走普通 chat；
- llm=off 时回退 NullLLM。
"""
from __future__ import annotations

import json as jsonlib

from agent.llm import DeepSeekLLM, NullLLM, build_llm


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json):  # noqa: A002 - 对齐 httpx 参数名
        self.calls.append({"url": url, "headers": headers, "json": json})
        if (json.get("response_format") or {}).get("type") == "json_object":
            content = '```json\n' + jsonlib.dumps({
                "hard_fields": {"venue": "lego_shanghai"},
                "objective": "precision",
                "audience_notes": ["亲子家庭"],
                "constraints": [],
            }, ensure_ascii=False) + "\n```"
        else:
            content = "# 润色后的提案\n\n预算 200 万，目标 Reach 80.3%（模型估算）。"
        return _FakeResponse({"choices": [{"message": {"content": content}}]})


def test_build_llm_off():
    llm = build_llm("off")
    assert isinstance(llm, NullLLM)
    assert llm.available is False


def test_deepseek_adapter_shapes():
    client = _FakeClient()
    llm = DeepSeekLLM(api_key="test-key", model="deepseek-chat", client=client)
    assert llm.available is True

    data = llm.extract_brief(
        "乐高，200万，精准触达亲子家庭",
        {"type": "object", "properties": {"objective": {"type": "string"}}},
        "extract json only",
    )
    assert data["objective"] == "precision"
    assert data["hard_fields"]["venue"] == "lego_shanghai"

    text = llm.polish_narrative(
        "# 草稿",
        {"budget_wan": 200, "reach_pct": 0.803},
        "polish",
    )
    assert "润色后的提案" in text

    calls = client.calls
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert calls[0]["json"]["temperature"] == 0.0
    assert "response_format" not in calls[1]["json"]
    assert calls[1]["json"]["temperature"] == 0.2


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("agent.llm._dotenv_key", lambda: None)
    llm = DeepSeekLLM()
    assert llm.available is False
    assert "DEEPSEEK_API_KEY" in llm.reason
