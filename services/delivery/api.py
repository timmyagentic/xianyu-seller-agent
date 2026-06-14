import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp

from .content import replace_delivery_params


class ApiDeliveryError(Exception):
    """Raised when an external API delivery source cannot provide content."""


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    text: str


RequestFunc = Callable[..., Awaitable[ApiResponse]]


class ApiDeliveryClient:
    def __init__(
        self,
        *,
        request: RequestFunc | None = None,
        max_retries: int = 4,
        retry_delay_seconds: float = 0.1,
    ):
        self.request = request or self._aiohttp_request
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    async def fetch_content(self, api_config: str | dict[str, Any], values: dict[str, object]) -> str:
        config = self._load_config(api_config)
        url = config.get("url")
        if not url:
            raise ApiDeliveryError("api_config.url is required")
        method = str(config.get("method", "GET")).upper()
        if method not in {"GET", "POST"}:
            raise ApiDeliveryError(f"unsupported api method: {method}")

        headers = self._load_mapping(config.get("headers", {}))
        params = self._replace_dynamic_values(self._load_mapping(config.get("params", {})), values)
        timeout = int(config.get("timeout", 10))

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=timeout,
                )
                if response.status_code == 200:
                    return self._extract_content(response.text)
                if response.status_code >= 500 or response.status_code == 408:
                    last_error = ApiDeliveryError(f"API returned {response.status_code}: {response.text[:200]}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.retry_delay_seconds)
                        continue
                raise ApiDeliveryError(f"API returned {response.status_code}: {response.text[:200]}")
            except (aiohttp.ClientError, asyncio.TimeoutError, ApiDeliveryError) as exc:
                last_error = exc
                if isinstance(exc, ApiDeliveryError) and "API returned 4" in str(exc):
                    raise
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay_seconds)
                    continue
                break
        raise ApiDeliveryError(str(last_error or "API delivery failed"))

    async def _aiohttp_request(self, *, method: str, url: str, headers: dict, params: dict, timeout: int) -> ApiResponse:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, headers=headers, params=params, timeout=timeout_obj) as response:
                    return ApiResponse(status_code=response.status, text=await response.text())
            async with session.post(url, headers=headers, json=params, timeout=timeout_obj) as response:
                return ApiResponse(status_code=response.status, text=await response.text())

    def _load_config(self, api_config: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(api_config, dict):
            return api_config
        if isinstance(api_config, str) and api_config.strip():
            parsed = json.loads(api_config)
            if isinstance(parsed, dict):
                return parsed
        raise ApiDeliveryError("api_config must be a JSON object")

    def _load_mapping(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _replace_dynamic_values(self, value: Any, values: dict[str, object]) -> Any:
        if isinstance(value, dict):
            return {key: self._replace_dynamic_values(inner, values) for key, inner in value.items()}
        if isinstance(value, list):
            return [self._replace_dynamic_values(inner, values) for inner in value]
        if isinstance(value, str):
            return replace_delivery_params(value, values)
        return value

    def _extract_content(self, response_text: str) -> str:
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            return response_text
        if isinstance(parsed, dict):
            for key in ("data", "content", "card"):
                value = parsed.get(key)
                if value is not None:
                    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return json.dumps(parsed, ensure_ascii=False)
        return str(parsed)
