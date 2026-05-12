"""
Phase 1 — Droplet tools.

All tools accept a single `params: dict` (FastMCP 3.x flat-kwargs caveat) and
return a normalized dict. Errors are returned as structured dicts (never
raised) so MCP clients can branch on `error: true`.
"""

from __future__ import annotations

from typing import Any

from .client import (
    _build_body,
    _build_query,
    _do_delete,
    _do_get,
    _do_post,
    _require_token,
    _safe_call_error,
)


def register_droplet_tools(mcp) -> None:
    """Attach droplet tools to the FastMCP instance."""

    @mcp.tool(
        name="do_list_droplets",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
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
            query = _build_query(
                params or {},
                allowed=["tag_name", "page", "per_page"],
            )
            return await _do_get("/droplets", token, params=query)
        except Exception as exc:
            return _safe_call_error("do_list_droplets", exc)

    @mcp.tool(
        name="do_get_droplet",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def do_get_droplet(params: dict) -> dict:
        """Get full metadata for a single droplet by id.

        Args:
            params: {
                droplet_id: int (required)
            }

        Returns:
            {droplet: {...}}
        """
        try:
            token = _require_token()
            droplet_id = (params or {}).get("droplet_id")
            if droplet_id is None:
                return {
                    "error": True,
                    "status_code": 400,
                    "message": "droplet_id is required",
                    "request_id": None,
                    "do_error_id": None,
                }
            return await _do_get(f"/droplets/{droplet_id}", token)
        except Exception as exc:
            return _safe_call_error("do_get_droplet", exc)

    @mcp.tool(
        name="do_create_droplet",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
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
            data: dict[str, Any] = params or {}
            for required in ("name", "region", "size", "image", "ssh_keys"):
                if required not in data or data[required] in (None, "", []):
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
                ],
            )
            return await _do_post("/droplets", token, json_body=body, timeout=60.0)
        except Exception as exc:
            return _safe_call_error("do_create_droplet", exc)

    @mcp.tool(
        name="do_delete_droplet",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def do_delete_droplet(params: dict) -> dict:
        """Permanently destroy a droplet.

        Args:
            params: {
                droplet_id: int (required)
            }

        Returns:
            {status_code: 204, data: None} on success.
        """
        try:
            token = _require_token()
            droplet_id = (params or {}).get("droplet_id")
            if droplet_id is None:
                return {
                    "error": True,
                    "status_code": 400,
                    "message": "droplet_id is required",
                    "request_id": None,
                    "do_error_id": None,
                }
            return await _do_delete(f"/droplets/{droplet_id}", token)
        except Exception as exc:
            return _safe_call_error("do_delete_droplet", exc)
