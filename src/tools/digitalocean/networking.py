"""
Phase 2 — Domain record tools.
"""

from __future__ import annotations

from typing import Any

from .client import (
    _build_body,
    _build_query,
    _do_get,
    _do_post,
    _require_token,
    _safe_call_error,
)


def register_networking_tools(mcp) -> None:
    """Attach domain-record tools to the FastMCP instance."""

    @mcp.tool(
        name="do_list_domain_records",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def do_list_domain_records(params: dict) -> dict:
        """List DNS records for a domain managed by DigitalOcean.

        Args:
            params: {
                domain: str (required) - e.g. "revaid.link"
                type: Optional[str] - filter by record type (A, AAAA, CNAME, MX, TXT, ...)
                name: Optional[str] - filter by record name
                page: Optional[int]
                per_page: Optional[int]
            }

        Returns:
            {domain_records: [...], meta: {...}, links: {...}}
        """
        try:
            token = _require_token()
            data: dict[str, Any] = params or {}
            domain = data.get("domain")
            if not domain:
                return {
                    "error": True,
                    "status_code": 400,
                    "message": "'domain' is required",
                    "request_id": None,
                    "do_error_id": None,
                }
            query = _build_query(
                data,
                allowed=["type", "name", "page", "per_page"],
            )
            return await _do_get(f"/domains/{domain}/records", token, params=query)
        except Exception as exc:
            return _safe_call_error("do_list_domain_records", exc)

    @mcp.tool(
        name="do_create_domain_record",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def do_create_domain_record(params: dict) -> dict:
        """Create a DNS record on a DigitalOcean-managed domain.

        Args:
            params: {
                domain: str (required) - e.g. "revaid.link"
                type: str (required) - A, AAAA, CNAME, MX, TXT, NS, SRV, CAA
                name: str (required) - hostname (use "@" for root)
                data: str (required) - record value
                ttl: Optional[int] - seconds, default 1800, min 30
                priority: Optional[int] - MX/SRV
                port: Optional[int] - SRV
                weight: Optional[int] - SRV
                flags: Optional[int] - CAA
                tag: Optional[str] - CAA
            }

        Returns:
            {domain_record: {...}}
        """
        try:
            token = _require_token()
            data: dict[str, Any] = params or {}
            domain = data.get("domain")
            if not domain:
                return {
                    "error": True,
                    "status_code": 400,
                    "message": "'domain' is required",
                    "request_id": None,
                    "do_error_id": None,
                }
            for required in ("type", "name", "data"):
                if required not in data or data[required] in (None, ""):
                    return {
                        "error": True,
                        "status_code": 400,
                        "message": f"'{required}' is required",
                        "request_id": None,
                        "do_error_id": None,
                    }
            body = _build_body(
                data,
                fields=[
                    "type",
                    "name",
                    "data",
                    "ttl",
                    "priority",
                    "port",
                    "weight",
                    "flags",
                    "tag",
                ],
            )
            return await _do_post(
                f"/domains/{domain}/records", token, json_body=body
            )
        except Exception as exc:
            return _safe_call_error("do_create_domain_record", exc)
