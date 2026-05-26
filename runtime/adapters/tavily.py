from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from runtime.adapters.external_search_provider_execution import (
    ExternalSearchProviderExecutionConfig,
    NormalizedExternalSearchProviderRequest,
)


TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"


class TavilyProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class TavilySearchProvider:
    api_key: str | None
    endpoint: str = TAVILY_SEARCH_ENDPOINT
    provider_id: str = "tavily"
    provider_type: str = "tavily"

    def execute(
        self,
        request: NormalizedExternalSearchProviderRequest,
        *,
        config: ExternalSearchProviderExecutionConfig,
    ) -> dict[str, Any]:
        key = _safe_string(self.api_key)
        if key is None:
            raise TavilyProviderError("missing_tavily_api_key")

        payload = {
            "query": request.query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": request.max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_image_descriptions": False,
            "include_favicon": False,
            "auto_parameters": False,
            "include_usage": True,
        }
        data = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        timeout = max(1, config.timeout_ms / 1000) if config.timeout_ms else 10
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise TavilyProviderError(f"tavily_http_{error.code}") from error
        except urllib.error.URLError as error:
            raise TavilyProviderError("tavily_url_error") from error

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TavilyProviderError("invalid_tavily_response_json") from error
        if not isinstance(decoded, dict):
            raise TavilyProviderError("invalid_tavily_response_shape")
        return decoded


def _safe_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "TAVILY_SEARCH_ENDPOINT",
    "TavilyProviderError",
    "TavilySearchProvider",
]
