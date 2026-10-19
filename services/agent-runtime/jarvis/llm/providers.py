"""Provider adapters.

Each provider is an independent adapter with its own request/response contract.
Nothing here assumes OpenAI-shaped payloads except the OpenAI-compatible adapter.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "openai",
            "label": "OpenAI",
            "kind": "cloud",
            "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
            "requires_key": True,
            "docs": "https://platform.openai.com/docs/api-reference",
        },
        {
            "id": "anthropic",
            "label": "Anthropic",
            "kind": "cloud",
            "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-latest"],
            "requires_key": True,
            "docs": "https://docs.anthropic.com",
        },
        {
            "id": "gemini",
            "label": "Google Gemini",
            "kind": "cloud",
            "models": ["gemini-2.0-flash", "gemini-2.5-flash"],
            "requires_key": True,
            "docs": "https://ai.google.dev/gemini-api/docs",
        },
        {
            "id": "ollama",
            "label": "Ollama (local)",
            "kind": "local",
            "models": ["llama3.1:8b", "qwen2.5:7b"],
            "requires_key": False,
            "docs": "https://ollama.com",
        },
        {
            "id": "local-rules",
            "label": "Motor deterministico local (sem LLM)",
            "kind": "local",
            "models": ["jarvis-rules-v1"],
            "requires_key": False,
            "docs": "internal",
        },
        {
            "id": "mock",
            "label": "Provider simulado (somente testes)",
            "kind": "test",
            "models": ["mock-1"],
            "requires_key": False,
            "docs": "internal",
        },
    ]


class BaseProvider:
    id = "base"
    kind = "cloud"

    def __init__(self, api_key: str = "", base_url: str = "", timeout: float = 60.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def complete(self, model: str, system: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    id = "openai"
    kind = "cloud"

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", **kw: Any):
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    async def complete(self, model: str, system: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        if not self.api_key:
            raise ProviderError("Credencial OpenAI ausente")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": kwargs.get("temperature", 0.3),
        }
        if kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if resp.status_code >= 400:
            raise ProviderError(f"OpenAI HTTP {resp.status_code}: {resp.text[:300]}", retryable=resp.status_code in {429, 500, 502, 503}, status=resp.status_code)
        data = resp.json()
        usage = data.get("usage") or {}
        return ChatResult(
            text=data["choices"][0]["message"]["content"],
            provider=self.id,
            model=model,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )


class AnthropicProvider(BaseProvider):
    id = "anthropic"
    kind = "cloud"

    def __init__(self, api_key: str = "", base_url: str = "https://api.anthropic.com/v1", **kw: Any):
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    async def complete(self, model: str, system: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        if not self.api_key:
            raise ProviderError("Credencial Anthropic ausente")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "system": system,
                    "max_tokens": kwargs.get("max_tokens", 2048),
                    "temperature": kwargs.get("temperature", 0.3),
                    "messages": messages,
                },
            )
        if resp.status_code >= 400:
            raise ProviderError(f"Anthropic HTTP {resp.status_code}: {resp.text[:300]}", retryable=resp.status_code in {429, 500, 502, 503}, status=resp.status_code)
        data = resp.json()
        usage = data.get("usage") or {}
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return ChatResult(
            text="\n".join(parts),
            provider=self.id,
            model=model,
            prompt_tokens=int(usage.get("input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
            raw=data,
        )


class GeminiProvider(BaseProvider):
    id = "gemini"
    kind = "cloud"

    def __init__(self, api_key: str = "", base_url: str = "https://generativelanguage.googleapis.com/v1beta", **kw: Any):
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    async def complete(self, model: str, system: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        if not self.api_key:
            raise ProviderError("Credencial Gemini ausente")
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/models/{model}:generateContent",
                params={"key": self.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": contents,
                    "generationConfig": {"temperature": kwargs.get("temperature", 0.3)},
                },
            )
        if resp.status_code >= 400:
            raise ProviderError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}", retryable=resp.status_code in {429, 500, 502, 503}, status=resp.status_code)
        data = resp.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        usage = data.get("usageMetadata") or {}
        return ChatResult(
            text=text,
            provider=self.id,
            model=model,
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            raw=data,
        )


class OllamaProvider(BaseProvider):
    id = "ollama"
    kind = "local"

    def __init__(self, api_key: str = "", base_url: str = "http://127.0.0.1:11434", **kw: Any):
        super().__init__(api_key=api_key, base_url=base_url, **kw)

    async def complete(self, model: str, system: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        async with httpx.AsyncClient(timeout=max(self.timeout, 120)) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [{"role": "system", "content": system}, *messages],
                    "options": {"temperature": kwargs.get("temperature", 0.3)},
                },
            )
        if resp.status_code >= 400:
            raise ProviderError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}", retryable=True, status=resp.status_code)
        data = resp.json()
        return ChatResult(
            text=(data.get("message") or {}).get("content", ""),
            provider=self.id,
            model=model,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            raw=data,
        )


class MockProvider(BaseProvider):
    """Deterministic provider used only by automated tests.

    It is never selected in normal operation and every response is tagged so the
    UI cannot mistake it for a real model.
    """
    id = "mock"
    kind = "test"

    async def complete(self, model: str, system: str, messages: list[dict[str, str]], **kwargs: Any) -> ChatResult:
        last = messages[-1]["content"] if messages else ""
        if kwargs.get("json_mode"):
            text = json.dumps(
                {
                    "summary": "Resposta simulada de teste",
                    "steps": [{"title": "Etapa simulada", "tool": "noop", "description": last[:120]}],
                    "disclaimer": "MOCK_PROVIDER: sem chamada externa",
                },
                ensure_ascii=False,
            )
        else:
            text = f"[MOCK] resposta deterministica para: {last[:160]}"
        return ChatResult(text=text, provider=self.id, model=model, prompt_tokens=10, completion_tokens=20, raw={"mock": True})


def build_provider(provider_id: str, api_key: str = "", base_url: str = "", timeout: float = 60.0) -> BaseProvider:
    mapping = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "ollama": OllamaProvider,
        "mock": MockProvider,
    }
    cls = mapping.get(provider_id)
    if not cls:
        raise ProviderError(f"Provider desconhecido: {provider_id}")
    if cls is MockProvider:
        return MockProvider()
    return cls(api_key=api_key, base_url=base_url or "", timeout=timeout)


def extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
