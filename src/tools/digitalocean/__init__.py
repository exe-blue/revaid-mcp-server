"""
DigitalOcean tool package.

Exposes register_digitalocean(mcp) which attaches all 8 DO tools (4 droplet,
2 networking, 2 account) to the given FastMCP instance.
"""

from .account import register_account_tools
from .client import TOKEN_ENV_VAR, aclose_client
from .droplets import register_droplet_tools
from .networking import register_networking_tools

__all__ = [
    "TOKEN_ENV_VAR",
    "aclose_client",
    "register_digitalocean",
]


def register_digitalocean(mcp) -> None:
    """Register all DigitalOcean tools on the FastMCP instance."""
    register_droplet_tools(mcp)
    register_networking_tools(mcp)
    register_account_tools(mcp)
