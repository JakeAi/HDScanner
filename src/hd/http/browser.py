"""Send through the private headed-browser service, preserving raw API outcomes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from hd.http.transport import RawResponse, TransportError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class BrowserTransport:
    """No retries here: HDClient owns pacing, request budgets and cooldowns."""

    def __init__(self, service_url: str, token_file: str,
                 timeout_seconds: float = 120, max_bytes: int = 10 * 1024 * 1024) -> None:
        self._url = service_url.rstrip("/") + "/request"
        self._token_file = Path(token_file)
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> RawResponse:
        try:
            token = self._token_file.read_text().strip()
        except OSError as exc:
            raise TransportError("Browser service token file is unavailable") from exc
        if len(token) < 32:
            raise TransportError("Browser service token is missing or invalid")
        request = Request(self._url, method="POST", data=json.dumps({
            "url": url, "payload": payload, "headers": headers,
        }).encode(), headers={"Content-Type": "application/json",
                            "Authorization": f"Bearer {token}"})
        # Internal service traffic must never pass through an environment proxy.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes * 6 + 8193)
        except HTTPError as exc:
            raise TransportError(f"Browser service returned HTTP {exc.code}") from None
        except (URLError, OSError, TimeoutError) as exc:
            raise TransportError("Browser service could not complete the request") from exc
        if len(raw) > self._max_bytes * 6 + 8192:
            raise TransportError("Browser service response exceeds size limit")
        try:
            result = json.loads(raw)
            status, body, response_headers = result["status"], result["body"], result["headers"]
            if (type(status) is not int or not 100 <= status <= 599
                or not isinstance(body, str) or not isinstance(response_headers, dict)
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in response_headers.items())):
                raise ValueError("Invalid response")
        except (ValueError, KeyError, TypeError) as exc:
            raise TransportError("Browser service returned an invalid response") from exc
        if len(body.encode()) > self._max_bytes:
            raise TransportError("Browser API response exceeds size limit")
        return RawResponse(status=status, body=body, headers=response_headers)

    async def post_json(self, url: str, payload: dict[str, Any],
                        headers: dict[str, str]) -> RawResponse:
        return await asyncio.to_thread(self._post, url, payload, headers)

    async def close(self) -> None:
        """The shared service closes its browser after an idle period."""
