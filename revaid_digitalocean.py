"""
Root-level auto-discovery shim for DigitalOcean tools.

main.py walks *.py at the repo root looking for register_* functions. The
real implementation lives under src/tools/digitalocean/ — this module re-
exports register_digitalocean so the discovery loader picks it up without
changes to main.py.
"""

from src.tools.digitalocean import register_digitalocean  # noqa: F401
