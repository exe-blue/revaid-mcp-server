"""
Phase 2 — Domain record tools.
"""

from __future__ import annotations

import re

from .client import (
    _build_body,
    _build_query,
    _do_get,
    _do_post,
    _ensure_required,
    _invalid_param_error,
    _require_token,
    _safe_call_error,
)


_LIST_QUERY = ("type", "name", "page", "per_page")
_RECORD_FIELDS = (
    "type",
    "name",
    "data",
    "ttl",
    "priority",
    "port",
    "weight",
    "flags",
    "tag",
)
_CREATE_REQUIRED = ("domain", "type", "name", "data")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _normalize_domain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    domain = value.strip().lower()
    if not domain or not _DOMAIN_RE.fullmatch(domain):
        return None
    return domain


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
        if err := _ensure_required(params, ("domain",)):
            return err
        domain = _normalize_domain(params.get("domain"))
        if domain is None:
            return _invalid_param_error("domain", "must be a valid domain name")
        query = _build_query(params, allowed=_LIST_QUERY)
        return await _do_get(f"/domains/{domain}/records", token, params=query)
    except Exception as exc:
        return _safe_call_error("do_list_domain_records", exc)


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
        if err := _ensure_required(params, _CREATE_REQUIRED):
            return err
        domain = _normalize_domain(params.get("domain"))
        if domain is None:
            return _invalid_param_error("domain", "must be a valid domain name")
        body = _build_body(params, fields=_RECORD_FIELDS)
        return await _do_post(f"/domains/{domain}/records", token, json_body=body)
    except Exception as exc:
        return _safe_call_error("do_create_domain_record", exc)


_NETWORKING_TOOLS = (
    (
        do_list_domain_records,
        "do_list_domain_records",
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    ),
    (
        do_create_domain_record,
        "do_create_domain_record",
        {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    ),
)


def register_networking_tools(mcp) -> None:
    """Attach domain-record tools to the FastMCP instance."""
    for fn, name, annotations in _NETWORKING_TOOLS:
        mcp.tool(name=name, annotations=annotations)(fn)
