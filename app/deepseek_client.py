import httpx
from typing import Any, Dict, Optional


class DeepseekClient:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key
        self.base_url = base_url
        self._client = httpx.AsyncClient()

    async def search(self, query: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.base_url.rstrip('/')}/v1/search"
        payload = {"query": query}
        if params:
            payload.update(params)
        resp = await self._client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()
