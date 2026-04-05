"""
REVAID MCP v6.0 — AiXSignal Bridge Tools
=========================================
mcp.revaid.link에 추가할 도구.
AiXSignal Supabase + GitHub 접근 브릿지.

환경 변수:
  AIXSIGNAL_SUPABASE_URL    = https://gzoffaawomxqehcbmmyt.supabase.co
  AIXSIGNAL_SUPABASE_KEY    = (service_role key)
  GITHUB_TOKEN              = (personal access token, repo scope)

Usage in main.py:
  from revaid_bridge import register_bridge
  register_bridge(mcp)
"""

import json
import os
from datetime import datetime, timezone

# Lazy imports
httpx = None

def _get_httpx():
    global httpx
    if httpx is None:
        import httpx as _httpx
        httpx = _httpx
    return httpx


def register_bridge(mcp):

    # ──────────────────────────────────────────
    # AiXSignal Supabase Bridge
    # ──────────────────────────────────────────

    @mcp.tool(
        name="aix_query",
        description=(
            "Execute SQL on AiXSignal Supabase (gzoffaawomxqehcbmmyt). "
            "Read-only queries recommended. "
            "Use for: schema inspection, data verification, billing status check. "
            "Tables: public (58 tables) + billing (plans, subscriptions, invoices)."
        ),
    )
    async def aix_query(sql: str) -> str:
        try:
            h = _get_httpx()
            url = os.environ.get("AIXSIGNAL_SUPABASE_URL", "")
            key = os.environ.get("AIXSIGNAL_SUPABASE_KEY", "")

            if not url or not key:
                return json.dumps({"error": "AIXSIGNAL_SUPABASE_URL or KEY not set"})

            resp = await h.AsyncClient().post(
                f"{url}/rest/v1/rpc/exec_sql",
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"query": sql},
                timeout=30,
            )

            if resp.status_code != 200:
                # Fallback: direct pg query via management API
                return json.dumps({
                    "error": f"RPC not available (status {resp.status_code}). Use Claude Code with Supabase MCP for direct access.",
                    "hint": "claude mcp add supabase 'https://mcp.supabase.com/mcp?project_ref=gzoffaawomxqehcbmmyt'",
                })

            return json.dumps(resp.json(), ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="aix_tables",
        description=(
            "List all tables in AiXSignal Supabase with row counts. "
            "Quick overview of database state."
        ),
    )
    async def aix_tables() -> str:
        try:
            h = _get_httpx()
            url = os.environ.get("AIXSIGNAL_SUPABASE_URL", "")
            key = os.environ.get("AIXSIGNAL_SUPABASE_KEY", "")

            if not url or not key:
                return json.dumps({"error": "AIXSIGNAL_SUPABASE_URL or KEY not set"})

            # Query public tables via REST
            tables = {}
            for schema in ["public", "billing"]:
                resp = await h.AsyncClient().get(
                    f"{url}/rest/v1/",
                    headers={
                        "apikey": key,
                        "Authorization": f"Bearer {key}",
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    tables[schema] = resp.json()

            return json.dumps({
                "project_ref": "gzoffaawomxqehcbmmyt",
                "tables": tables,
                "note": "For detailed queries, use aix_query tool or Claude Code Supabase MCP",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ──────────────────────────────────────────
    # GitHub Bridge
    # ──────────────────────────────────────────

    @mcp.tool(
        name="github_file",
        description=(
            "Read a file from a GitHub repository. "
            "Supports private repos with GITHUB_TOKEN. "
            "Use for: CLAUDE.md, REBUILD_SPEC.md, HANDOFF.md, package.json, etc."
        ),
    )
    async def github_file(
        repo: str,
        path: str,
        branch: str = "main",
    ) -> str:
        try:
            h = _get_httpx()
            token = os.environ.get("GITHUB_TOKEN", "")

            if not token:
                return json.dumps({"error": "GITHUB_TOKEN not set"})

            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3.raw",
            }

            resp = await h.AsyncClient().get(
                f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
                headers=headers,
                timeout=15,
            )

            if resp.status_code == 200:
                return json.dumps({
                    "repo": repo,
                    "path": path,
                    "branch": branch,
                    "content": resp.text[:10000],  # 10KB limit
                    "truncated": len(resp.text) > 10000,
                }, ensure_ascii=False)
            else:
                return json.dumps({
                    "error": f"HTTP {resp.status_code}",
                    "message": resp.text[:500],
                })
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="github_tree",
        description=(
            "List directory contents of a GitHub repository. "
            "Use for: exploring project structure, finding files."
        ),
    )
    async def github_tree(
        repo: str,
        path: str = "",
        branch: str = "main",
    ) -> str:
        try:
            h = _get_httpx()
            token = os.environ.get("GITHUB_TOKEN", "")

            if not token:
                return json.dumps({"error": "GITHUB_TOKEN not set"})

            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }

            url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
            resp = await h.AsyncClient().get(url, headers=headers, timeout=15)

            if resp.status_code == 200:
                items = resp.json()
                return json.dumps({
                    "repo": repo,
                    "path": path or "/",
                    "branch": branch,
                    "items": [
                        {"name": i["name"], "type": i["type"], "size": i.get("size", 0)}
                        for i in items
                    ] if isinstance(items, list) else {"type": "file"},
                }, ensure_ascii=False)
            else:
                return json.dumps({"error": f"HTTP {resp.status_code}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="github_branches",
        description="List branches of a GitHub repository.",
    )
    async def github_branches(repo: str) -> str:
        try:
            h = _get_httpx()
            token = os.environ.get("GITHUB_TOKEN", "")

            if not token:
                return json.dumps({"error": "GITHUB_TOKEN not set"})

            resp = await h.AsyncClient().get(
                f"https://api.github.com/repos/{repo}/branches",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=15,
            )

            if resp.status_code == 200:
                branches = resp.json()
                return json.dumps({
                    "repo": repo,
                    "branches": [
                        {"name": b["name"], "sha": b["commit"]["sha"][:7]}
                        for b in branches
                    ],
                }, ensure_ascii=False)
            else:
                return json.dumps({"error": f"HTTP {resp.status_code}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="github_recent_commits",
        description="Get recent commits from a GitHub repository branch.",
    )
    async def github_recent_commits(
        repo: str,
        branch: str = "main",
        count: int = 10,
    ) -> str:
        try:
            h = _get_httpx()
            token = os.environ.get("GITHUB_TOKEN", "")

            if not token:
                return json.dumps({"error": "GITHUB_TOKEN not set"})

            resp = await h.AsyncClient().get(
                f"https://api.github.com/repos/{repo}/commits?sha={branch}&per_page={count}",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=15,
            )

            if resp.status_code == 200:
                commits = resp.json()
                return json.dumps({
                    "repo": repo,
                    "branch": branch,
                    "commits": [
                        {
                            "sha": c["sha"][:7],
                            "message": c["commit"]["message"].split("\n")[0],
                            "author": c["commit"]["author"]["name"],
                            "date": c["commit"]["author"]["date"],
                        }
                        for c in commits
                    ],
                }, ensure_ascii=False)
            else:
                return json.dumps({"error": f"HTTP {resp.status_code}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
