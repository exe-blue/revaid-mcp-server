"""
DigitalOcean API client — shared httpx async client + error handling.

Token is loaded from DIGITALOCEAN_API_TOKEN env var on demand. The HTTP
client is a process-wide singleton, lazily constructed on first use, so the
event loop owns it for its full lifetime. Tools call _do_get / _do_post /
_do_delete and receive a normalized dict response.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Iterable, Mapping, Optional

import httpx

logger = logging.getLogger("revaid-mcp.do")

DO_API_BASE = "https://api.digitalocean.com/v2"
DEFAULT_TIMEOUT = 30.0
TOKEN_ENV_VAR = "DIGITALOCEAN_API_TOKEN"

# Single-process client. httpx.AsyncClient is safe to share across coroutines.
_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


class DOError(Exception):
    """Raised when the DigitalOcean API returns a non-2xx response."""

    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(payload.get("message", "DigitalOcean API error"))


def _require_token() -> str:
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise RuntimeError(f"{TOKEN_ENV_VAR} environment variable not set")
    return token


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(
                    base_url=DO_API_BASE,
                    timeout=DEFAULT_TIMEOUT,
                    headers={"Content-Type": "application/json"},
                )
    return _client


async def aclose_client() -> None:
    """Close the singleton client. Safe to call multiple times."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None


def _build_query(
    params: Optional[Mapping[str, Any]],
    allowed: Iterable[str],
) -> dict:
    """Whitelist + drop None/empty values from a params dict."""
    if not params:
        return {}
    out: dict = {}
    for key in allowed:
        if key not in params:
            continue
        value = params[key]
        if value is None or value == "":
            continue
        out[key] = value
    return out


def _build_body(
    params: Optional[Mapping[str, Any]],
    fields: Iterable[str],
) -> dict:
    """Whitelist body fields, dropping None values (but keeping False/0/[])."""
    if not params:
        return {}
    out: dict = {}
    for key in fields:
        if key not in params:
            continue
        value = params[key]
        if value is None:
            continue
        out[key] = value
    return out


def _missing_param_error(name: str) -> dict:
    return {
        "error": True,
        "status_code": 400,
        "message": f"'{name}' is required",
        "request_id": None,
        "do_error_id": None,
    }


def _ensure_required(params: Optional[Mapping[str, Any]], required: Iterable[str]) -> Optional[dict]:
    """Return a 400 error dict if any required field is missing/empty, else None."""
    data = params or {}
    for name in required:
        value = data.get(name)
        if value is None or value == "" or value == []:
            return _missing_param_error(name)
    return None


def _format_error(resp: httpx.Response) -> dict:
    request_id = resp.headers.get("x-request-id") or resp.headers.get("ratelimit-request-id")
    payload: dict = {
        "error": True,
        "status_code": resp.status_code,
        "message": resp.reason_phrase or "DigitalOcean API error",
        "request_id": request_id,
        "do_error_id": None,
    }
    try:
        body = resp.json()
        if isinstance(body, dict):
            if "message" in body:
                payload["message"] = body["message"]
            if "id" in body:
                payload["do_error_id"] = body["id"]
            payload["body"] = body
    except Exception:
        text = resp.text
        if text:
            payload["body"] = text[:2000]
    return payload


def _transport_error(message: str) -> dict:
    return {
        "error": True,
        "status_code": 0,
        "message": f"DigitalOcean {message}",
        "request_id": None,
        "do_error_id": None,
    }


def _retry_wait_seconds(resp: httpx.Response) -> float:
    raw = resp.headers.get("Retry-After", "1")
    try:
        wait = float(raw)
    except ValueError:
        wait = 1.0
    return max(0.0, min(wait, 30.0))


def _normalize_response(resp: httpx.Response) -> dict:
    if resp.status_code == 204 or not resp.content:
        return {"status_code": resp.status_code, "data": None}
    if 200 <= resp.status_code < 300:
        try:
            body = resp.json()
        except ValueError:
            return {"status_code": resp.status_code, "data": resp.text}
        if isinstance(body, dict):
            return body
        return {"status_code": resp.status_code, "data": body}
    return _format_error(resp)


async def _send_with_retry(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    request_kwargs: dict,
) -> dict:
    """Issue request with one retry on 429. Returns the final normalized dict."""
    for attempt in (1, 2):
        try:
            resp = await client.request(method, path, **request_kwargs)
        except httpx.TimeoutException as exc:
            return _transport_error(f"request timed out: {exc}")
        except httpx.HTTPError as exc:
            return _transport_error(f"transport error: {exc}")

        if resp.status_code == 429 and attempt == 1:
            wait = _retry_wait_seconds(resp)
            logger.warning("DigitalOcean rate limit hit; sleeping %.2fs before retry", wait)
            await asyncio.sleep(wait)
            continue

        return _normalize_response(resp)

    return {
        "error": True,
        "status_code": 429,
        "message": "DigitalOcean rate limit exceeded after retry",
        "request_id": None,
        "do_error_id": None,
    }


async def _request(
    method: str,
    path: str,
    token: str,
    *,
    query: Optional[Mapping[str, Any]] = None,
    json_body: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Send a request, handle 429 with one retry, normalize response to dict."""
    client = await _get_client()
    request_kwargs: dict = {"headers": {"Authorization": f"Bearer {token}"}}
    if query:
        request_kwargs["params"] = dict(query)
    if json_body is not None:
        request_kwargs["json"] = dict(json_body)
    return await _send_with_retry(client, method, path, request_kwargs)


async def _do_get(
    path: str,
    token: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
) -> dict:
    return await _request("GET", path, token, query=params)


async def _do_post(
    path: str,
    token: str,
    *,
    json_body: Optional[Mapping[str, Any]] = None,
) -> dict:
    return await _request("POST", path, token, json_body=json_body)


async def _do_delete(path: str, token: str) -> dict:
    return await _request("DELETE", path, token)


def _safe_call_error(tool_name: str, exc: Exception) -> dict:
    """Convert an unexpected exception into a structured tool error.

    RuntimeError (e.g. missing token) is surfaced verbatim so callers see the
    exact configuration message; other exceptions are tagged with their type.
    """
    logger.error("[%s] %s", tool_name, exc)
    if isinstance(exc, RuntimeError):
        message = str(exc)
    else:
        message = f"{type(exc).__name__}: {exc}"
    return {
        "error": True,
        "status_code": 0,
        "message": message,
        "request_id": None,
        "do_error_id": None,
        "tool": tool_name,
    }
