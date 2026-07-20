import httpx
import json
from typing import Any, AsyncGenerator, Dict, Optional


class DeepseekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key
        self.base_url = base_url
        # Chat completion can take noticeably longer than default httpx timeouts.
        timeout = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=30.0)
        self._client = httpx.AsyncClient(timeout=timeout)

    def _auth_headers(self, api_key: Optional[str] = None) -> Dict[str, str]:
        key = api_key or self.api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def search(self, query: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = self._auth_headers()
        url = f"{self.base_url.rstrip('/')}/v1/search"
        payload = {"query": query}
        if params:
            payload.update(params)
        resp = await self._client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def chat_complete(
        self,
        messages: list,
        model: str = "deepseek-v4-pro",
        max_tokens: int = 256,
        temperature: float = 0.9,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers = self._auth_headers(api_key)
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        resp = await self._client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def chat_complete_stream(
        self,
        messages: list,
        model: str = "deepseek-v4-pro",
        max_tokens: int = 1024,
        temperature: float = 0.9,
        api_key: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from DeepSeek chat completions (SSE).

        Yields content strings token-by-token. Handles [DONE] marker,
        JSON decode errors, and connection drops gracefully.
        """
        headers = self._auth_headers(api_key)
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with self._client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
