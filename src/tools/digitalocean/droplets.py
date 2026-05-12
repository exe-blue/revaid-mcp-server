"""
Phase 1 — Droplet tools.

All tools accept a single `params: dict` (FastMCP 3.x flat-kwargs caveat) and
return a normalized dict. Errors are returned as structured dicts (never
raised) so MCP clients can branch on `error: true`.
"""

from __future__ import annotations

from .client import (
    _build_body,
    _build_query,
    _do_delete,
    _do_get,
    _do_post,
    _ensure_required,
    _require_token,
    _safe_call_error,
)


_LIST_QUERY = ("tag_name", "page", "per_page")
_CREATE_FIELDS = (
    "name",
    "region",
    "size",
    "image",
    "ssh_keys",
    "user_data",
    "tags",
    "ipv6",
    "monitoring",
    "backups",
    "vpc_uuid",
)
_CREATE_REQUIRED = ("name", "region", "size", "image", "ssh_keys")


async def do_list_droplets(params: dict) -> dict:
    """List DigitalOcean droplets owned by the account.

    Args:
        params: {
            tag_name: Optional[str] - filter by tag
            page: Optional[int] - default 1
            per_page: Optional[int] - default 20, max 200
        }

    Returns:
        {droplets: [...], meta: {total: int}, links: {...}}
    """
    try:
        token = _require_token()
        query = _build_query(params or {}, allowed=_LIST_QUERY)
        return await _do_get("/droplets", token, params=query)
    except Exception as exc:
        return _safe_call_error("do_list_droplets", exc)


async def do_get_droplet(params: dict) -> dict:
    """Get full metadata for a single droplet by id.

    Args:
        params: {droplet_id: int (required)}

    Returns:
        {droplet: {...}}
    """
    try:
        token = _require_token()
        if err := _ensure_required(params, ("droplet_id",)):
            return err
        return await _do_get(f"/droplets/{params['droplet_id']}", token)
    except Exception as exc:
        return _safe_call_error("do_get_droplet", exc)


async def do_create_droplet(params: dict) -> dict:
    """Provision a new droplet.

    Args:
        params: {
            name: str (required) - droplet hostname
            region: str (required) - e.g. "sgp1", "nyc3"
            size: str (required) - slug, e.g. "s-2vcpu-4gb"
            image: str | int (required) - distribution slug or snapshot id
            ssh_keys: list[str | int] (required) - fingerprints or ids
            user_data: Optional[str] - cloud-init script
            tags: Optional[list[str]]
            ipv6: Optional[bool]
            monitoring: Optional[bool]
            backups: Optional[bool]
            vpc_uuid: Optional[str]
        }

    Returns:
        {droplet: {...}, links: {actions: [...]}}
    """
    try:
        token = _require_token()
        if err := _ensure_required(params, _CREATE_REQUIRED):
            return err
        body = _build_body(params, fields=_CREATE_FIELDS)
        return await _do_post("/droplets", token, json_body=body)
    except Exception as exc:
        return _safe_call_error("do_create_droplet", exc)


async def do_delete_droplet(params: dict) -> dict:
    """Permanently destroy a droplet.

    Args:
        params: {droplet_id: int (required)}

    Returns:
        {status_code: 204, data: None} on success.
    """
    try:
        token = _require_token()
        if err := _ensure_required(params, ("droplet_id",)):
            return err
        return await _do_delete(f"/droplets/{params['droplet_id']}", token)
    except Exception as exc:
        return _safe_call_error("do_delete_droplet", exc)


_DROPLET_TOOLS = (
    (
        do_list_droplets,
        "do_list_droplets",
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    ),
    (
        do_get_droplet,
        "do_get_droplet",
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    ),
    (
        do_create_droplet,
        "do_create_droplet",
        {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    ),
    (
        do_delete_droplet,
        "do_delete_droplet",
        {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True},
    ),
)


def register_droplet_tools(mcp) -> None:
    """Attach droplet tools to the FastMCP instance."""
    for fn, name, annotations in _DROPLET_TOOLS:
        mcp.tool(name=name, annotations=annotations)(fn)
