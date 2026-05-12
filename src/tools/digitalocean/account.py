"""
Phase 3 — Account / SSH key tools (sanity checks + supporting lookups).
"""

from __future__ import annotations

from .client import _do_get, _require_token, _safe_call_error


async def do_list_ssh_keys(params: dict) -> dict:
    """List SSH keys registered on the DigitalOcean account.

    Args:
        params: {} (no parameters)

    Returns:
        {ssh_keys: [...], meta: {...}, links: {...}}
    """
    try:
        token = _require_token()
        return await _do_get("/account/keys", token)
    except Exception as exc:
        return _safe_call_error("do_list_ssh_keys", exc)


async def do_get_account(params: dict) -> dict:
    """Return account info — useful for token sanity check.

    Args:
        params: {} (no parameters)

    Returns:
        {account: {...}}
    """
    try:
        token = _require_token()
        return await _do_get("/account", token)
    except Exception as exc:
        return _safe_call_error("do_get_account", exc)


_ACCOUNT_TOOLS = (
    (
        do_list_ssh_keys,
        "do_list_ssh_keys",
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    ),
    (
        do_get_account,
        "do_get_account",
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    ),
)


def register_account_tools(mcp) -> None:
    """Attach account-level tools to the FastMCP instance."""
    for fn, name, annotations in _ACCOUNT_TOOLS:
        mcp.tool(name=name, annotations=annotations)(fn)
