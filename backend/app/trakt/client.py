from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from app.config import settings

API_BASE = settings.trakt_api_base
AUTH_BASE = settings.trakt_auth_base
USER_AGENT = "FN2Trakt/0.1 (+https://github.com/)"
DEFAULT_TIMEOUT = 20.0


class TraktError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        payload: Any = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload
        self.retry_after = retry_after


class TraktAuthError(TraktError):
    pass


class TraktRateLimitError(TraktError):
    pass


class TraktClient:
    """Minimal synchronous Trakt API client.

    One instance per request is cheap (httpx.Client keeps no pool between
    constructions), so callers simply create it where needed.
    """

    _post_gate = threading.Lock()
    _last_post_at = 0.0

    def __init__(self, client_id: str, client_secret: str | None = None):
        if not client_id:
            raise TraktError("缺少 Trakt Client ID")
        self.client_id = client_id
        self.client_secret = client_secret
        self._client = httpx.Client(
            base_url=API_BASE, timeout=DEFAULT_TIMEOUT, trust_env=settings.trakt_trust_env
        )
        self._auth = httpx.Client(
            base_url=AUTH_BASE, timeout=DEFAULT_TIMEOUT, trust_env=settings.trakt_trust_env
        )

    # ------------------------------------------------------------------ http
    def close(self) -> None:
        self._client.close()
        self._auth.close()

    def __enter__(self) -> "TraktClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _post_throttle(self) -> None:
        # Trakt allows roughly one POST per second per application.
        with TraktClient._post_gate:
            wait = 1.05 - (time.monotonic() - TraktClient._last_post_at)
            if wait > 0:
                time.sleep(wait)
            TraktClient._last_post_at = time.monotonic()

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: dict | None = None,
        params: dict | None = None,
        throttled: bool = True,
    ) -> Any:
        if method.upper() == "POST" and throttled:
            self._post_throttle()
        http = self._auth if path.startswith("/oauth/") else self._client
        try:
            response = http.request(
                method,
                path,
                headers=self._headers(token),
                json=json,
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise TraktError("请求 Trakt 超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise TraktError(f"连接 Trakt 失败: {exc}") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise TraktRateLimitError(
                "Trakt 请求过于频繁，请稍后再试",
                status_code=429,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code == 401:
            raise TraktAuthError("Trakt 授权已失效，请重新绑定账号", status_code=401)
        if response.status_code == 403:
            raise TraktAuthError("Trakt 拒绝了该请求（权限不足）", status_code=403)
        if response.status_code >= 400:
            payload: Any
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:500]
            message = f"Trakt 返回 {response.status_code}"
            if isinstance(payload, dict) and payload.get("error"):
                message = str(payload["error"])
            elif isinstance(payload, str) and payload:
                message = payload
            raise TraktError(message, status_code=response.status_code, payload=payload)

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    # ------------------------------------------------------------------ oauth
    def device_code(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/oauth/device/code",
            json={"client_id": self.client_id},
            throttled=False,
        )

    def device_token(self, device_code: str) -> tuple[int, dict[str, Any] | str | None]:
        """Returns (http_status, payload). 400 means the user has not approved yet."""
        self._post_throttle()
        body: dict[str, Any] = {"code": device_code, "client_id": self.client_id}
        if self.client_secret:
            body["client_secret"] = self.client_secret
        try:
            response = self._auth.post(
                "/oauth/device/token",
                headers=self._headers(),
                json=body,
            )
        except httpx.HTTPError as exc:
            raise TraktError(f"轮询 Trakt 授权状态失败: {exc}") from exc
        payload: Any = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:500]
        return response.status_code, payload

    def refresh(self, refresh_token: str, redirect_uri: str = "urn:ietf:wg:oauth:2.0:oob") -> dict[str, Any]:
        body: dict[str, Any] = {
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "grant_type": "refresh_token",
        }
        if self.client_secret:
            body["client_secret"] = self.client_secret
        return self._request("POST", "/oauth/token", json=body)

    # ------------------------------------------------------------------ user
    def me(self, token: str) -> dict[str, Any]:
        return self._request("GET", "/users/me", token=token)

    def search(self, query: str, media_type: str, limit: int = 10) -> list[dict[str, Any]]:
        if media_type not in {"movie", "show"}:
            raise TraktError(f"不支持的搜索类型: {media_type}")
        result = self._request(
            "GET",
            f"/search/{media_type}",
            params={"query": query, "limit": limit, "extended": "full"},
        )
        return result or []

    def search_by_id(self, media_type: str, id_type: str, value: str | int) -> list[dict[str, Any]]:
        if media_type not in {"movie", "show"} or id_type not in {"tmdb", "imdb", "trakt", "tvdb"}:
            raise TraktError("不支持的 ID 查找参数")
        return (
            self._request(
                "GET",
                f"/search/{id_type}/{value}",
                params={"type": media_type, "extended": "full"},
            )
            or []
        )

    def add_history(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "/sync/history", token=token, json=payload)
        return result or {}

    def history_page(
        self, token: str, page: int = 1, limit: int = 100
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Return (items, page_count, item_count) for one Trakt history page.

        Trakt exposes pagination through response headers instead of the JSON
        body, so this bypasses ``_request`` and keeps the same error mapping.
        """
        try:
            response = self._client.get(
                "/sync/history",
                headers=self._headers(token),
                params={"page": page, "limit": limit, "extended": "full"},
            )
        except httpx.TimeoutException as exc:
            raise TraktError("请求 Trakt 历史超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise TraktError(f"连接 Trakt 失败: {exc}") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise TraktRateLimitError(
                "Trakt 请求过于频繁，请稍后再试",
                status_code=429,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status_code == 401:
            raise TraktAuthError("Trakt 授权已失效，请重新绑定账号", status_code=401)
        if response.status_code == 403:
            raise TraktAuthError("Trakt 拒绝了该请求（权限不足）", status_code=403)
        if response.status_code >= 400:
            try:
                payload: Any = response.json()
            except ValueError:
                payload = response.text[:500]
            message = f"Trakt 返回 {response.status_code}"
            if isinstance(payload, dict) and payload.get("error"):
                message = str(payload["error"])
            raise TraktError(message, status_code=response.status_code, payload=payload)

        items = response.json() if response.content else []
        if not isinstance(items, list):
            items = []
        try:
            page_count = int(response.headers.get("X-Pagination-Page-Count") or 1)
        except ValueError:
            page_count = 1
        try:
            item_count = int(response.headers.get("X-Pagination-Item-Count") or len(items))
        except ValueError:
            item_count = len(items)
        return items, page_count, item_count
