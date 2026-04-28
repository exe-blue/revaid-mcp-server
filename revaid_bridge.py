"""
REVAID MCP Server v6.0 — Bridge Module
======================================
Provides bridge tools for services not accessible via native MCP connectors:
  1. AiXSignal Supabase (gzoffaawomxqehcbmmyt) — SQL execution, table listing
  2. GitHub (exe-blue org) — file reading, directory listing, CLAUDE.md access

Environment Variables Required:
  AIX_SUPABASE_URL    — https://gzoffaawomxqehcbmmyt.supabase.co
  AIX_SUPABASE_KEY    — service_role key (NOT anon key)
  GITHUB_PAT              — Personal Access Token (classic or fine-grained)

Integration:
  Import and call register_bridge_tools(mcp) from your main server file.
"""

import asyncio
import base64
import json
import logging
import os
import re
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("revaid.bridge")

GITHUB_DEFAULT_OWNER = "exe-blue"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")

_DESTRUCTIVE_RE = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|ALTER|INSERT|UPDATE|CREATE)\b",
    re.IGNORECASE,
)

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30)
    return _http_client


def _validate_identifier(name: str, label: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _get_aix_config():
    url = os.getenv("AIX_SUPABASE_URL", "")
    key = os.getenv("AIX_SUPABASE_SERVICE_KEY", "") or os.getenv("AIX_SUPABASE_KEY", "")
    return url, key


async def _aixsignal_rpc(query: str) -> dict:
    """Execute SQL on AiXSignal Supabase via PostgREST /rpc/execute_sql."""
    url, key = _get_aix_config()
    if not url or not key:
        return {"error": "AIX_SUPABASE_URL or AIX_SUPABASE_KEY not set"}

    client = _get_http_client()
    resp = await client.post(
        f"{url}/rest/v1/rpc/execute_sql",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={"query": query},
    )

    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"data": data, "status": "ok"}

    if resp.status_code == 404:
        return {
            "error": "execute_sql RPC function not found. Run aixsignal_execute_sql_migration.sql first.",
            "status_code": 404,
        }

    return {
        "error": f"RPC call failed (HTTP {resp.status_code})",
        "detail": resp.text[:500],
    }


async def _github_api(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Call GitHub REST API."""
    pat = os.getenv("GITHUB_PAT", "")
    if not pat:
        return {"error": "GITHUB_PAT not set"}

    url = f"https://api.github.com{endpoint}"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    client = _get_http_client()
    if method == "GET":
        resp = await client.get(url, headers=headers)
    elif method == "POST":
        resp = await client.post(url, headers=headers, json=data)
    elif method == "PATCH":
        resp = await client.patch(url, headers=headers, json=data)
    elif method == "PUT":
        resp = await client.put(url, headers=headers, json=data)
    else:
        return {"error": f"Unsupported method: {method}"}

    if resp.status_code in (200, 201):
        return {"data": resp.json(), "status": "ok"}
    return {"error": f"GitHub API {resp.status_code}", "detail": resp.text[:500]}


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

def register_bridge_tools(mcp):
    """Register all bridge tools on the given FastMCP instance."""

    # ===================================================================
    # AiXSignal Supabase Tools
    # ===================================================================

    @mcp.tool()
    async def aixsignal_execute_sql(query: str) -> str:
        """Execute read-only SQL on AiXSignal Supabase (project: gzoffaawomxqehcbmmyt).

        Use for inspecting schemas, querying billing tables, checking constraints,
        and verifying data. DDL/DML operations should use aixsignal_apply_migration.

        Args:
            query: SQL query to execute (SELECT, SHOW, etc.)
        """
        if _DESTRUCTIVE_RE.search(query):
            return _json({
                "error": "Destructive operation blocked. Use aixsignal_apply_migration for DDL/DML.",
            })

        result = await _aixsignal_rpc(query)
        return _json(result)

    @mcp.tool()
    async def aixsignal_apply_migration(name: str, query: str) -> str:
        """Apply a DDL migration to AiXSignal Supabase.

        Use for schema changes like ALTER TABLE, CREATE INDEX, CHECK constraints.
        Requires explicit migration name for tracking.

        Args:
            name: Migration name in snake_case (e.g., 'add_heleket_to_invoices_check')
            query: SQL DDL to execute
        """
        logger.info(f"Applying migration '{name}': {query[:100]}...")
        result = await _aixsignal_rpc(query)
        return _json({"migration": name, **result})

    @mcp.tool()
    async def aixsignal_list_tables(schema: str = "public") -> str:
        """List all tables in an AiXSignal Supabase schema.

        Args:
            schema: Schema name (default: 'public', also try 'billing')
        """
        schema = _validate_identifier(schema, "schema")
        query = f"""
        SELECT table_name,
               pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) as size
        FROM information_schema.tables
        WHERE table_schema = '{schema}'
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """
        result = await _aixsignal_rpc(query)
        return _json(result)

    @mcp.tool()
    async def aixsignal_describe_table(table_name: str, schema: str = "public") -> str:
        """Get column details and constraints for an AiXSignal table.

        Args:
            table_name: Table name (e.g., 'invoices', 'subscriptions')
            schema: Schema name (default: 'public', also try 'billing')
        """
        schema = _validate_identifier(schema, "schema")
        table_name = _validate_identifier(table_name, "table_name")

        col_query = f"""
        SELECT
            c.column_name, c.data_type, c.is_nullable, c.column_default,
            tc.constraint_type, tc.constraint_name
        FROM information_schema.columns c
        LEFT JOIN information_schema.constraint_column_usage ccu
            ON c.column_name = ccu.column_name
            AND c.table_name = ccu.table_name
            AND c.table_schema = ccu.table_schema
        LEFT JOIN information_schema.table_constraints tc
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE c.table_schema = '{schema}' AND c.table_name = '{table_name}'
        ORDER BY c.ordinal_position;
        """
        check_query = f"""
        SELECT conname, pg_get_constraintdef(oid) as definition
        FROM pg_constraint
        WHERE conrelid = '{schema}.{table_name}'::regclass
        AND contype = 'c';
        """
        result, check_result = await asyncio.gather(
            _aixsignal_rpc(col_query),
            _aixsignal_rpc(check_query),
        )

        return _json({"columns": result, "check_constraints": check_result})

    @mcp.tool()
    async def aixsignal_list_functions(schema: str = "public") -> str:
        """List Edge Functions and database functions in AiXSignal.

        Args:
            schema: Schema to search (default: 'public')
        """
        schema = _validate_identifier(schema, "schema")
        query = f"""
        SELECT routine_name, routine_type, data_type as return_type
        FROM information_schema.routines
        WHERE routine_schema = '{schema}'
        ORDER BY routine_name;
        """
        result = await _aixsignal_rpc(query)
        return _json(result)

    # ===================================================================
    # GitHub Tools
    # ===================================================================

    @mcp.tool()
    async def github_read_file(
        repo: str,
        path: str,
        owner: str = GITHUB_DEFAULT_OWNER,
        ref: str = "main",
    ) -> str:
        """Read a file from a GitHub repository.

        Returns decoded file content. Use for reading CLAUDE.md, source code,
        configuration files, etc.

        Args:
            repo: Repository name (e.g., 'aixsignal-webapp', 'revaid-mcp-server', 'REVAID.LINK')
            path: File path within the repo (e.g., 'CLAUDE.md', 'src/app/page.tsx')
            owner: GitHub org/user (default: 'exe-blue')
            ref: Branch or commit SHA (default: 'main')
        """
        endpoint = f"/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        result = await _github_api(endpoint)

        if "error" in result:
            return _json(result)

        data = result["data"]
        if isinstance(data, list):
            return _json({
                "error": f"'{path}' is a directory. Use github_list_directory instead.",
                "entries": [{"name": f["name"], "type": f["type"]} for f in data],
            })

        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return _json({
            "path": data.get("path"),
            "size": data.get("size"),
            "sha": data.get("sha"),
            "content": content,
        })

    @mcp.tool()
    async def github_list_directory(
        repo: str,
        path: str = "",
        owner: str = GITHUB_DEFAULT_OWNER,
        ref: str = "main",
    ) -> str:
        """List files and directories in a GitHub repository path.

        Args:
            repo: Repository name (e.g., 'aixsignal-webapp')
            path: Directory path (empty string for root)
            owner: GitHub org/user (default: 'exe-blue')
            ref: Branch or commit SHA (default: 'main')
        """
        endpoint = f"/repos/{owner}/{repo}/contents/{path}?ref={ref}"
        result = await _github_api(endpoint)

        if "error" in result:
            return _json(result)

        data = result["data"]
        if not isinstance(data, list):
            return _json({"error": "Not a directory", "type": "file"})

        entries = [
            {
                "name": item["name"],
                "type": item["type"],
                "size": item.get("size", 0),
                "path": item["path"],
            }
            for item in data
        ]
        return _json({"path": path or "/", "count": len(entries), "entries": entries})

    @mcp.tool()
    async def github_search_code(
        query: str,
        repo: Optional[str] = None,
        owner: str = GITHUB_DEFAULT_OWNER,
    ) -> str:
        """Search code across GitHub repositories.

        Args:
            query: Search query (e.g., 'billing.invoices CHECK', 'verify-payment')
            repo: Optional repo to scope search (e.g., 'aixsignal-webapp')
            owner: GitHub org/user (default: 'exe-blue')
        """
        q = query
        if repo:
            q += f" repo:{owner}/{repo}"
        else:
            q += f" org:{owner}"

        endpoint = f"/search/code?q={quote(q)}&per_page=10"
        result = await _github_api(endpoint)

        if "error" in result:
            return _json(result)

        items = result["data"].get("items", [])
        results = [
            {
                "repo": item["repository"]["full_name"],
                "path": item["path"],
                "name": item["name"],
                "url": item["html_url"],
            }
            for item in items[:10]
        ]
        return _json({"total_count": result["data"].get("total_count", 0), "results": results})

    @mcp.tool()
    async def github_list_repos(
        owner: str = GITHUB_DEFAULT_OWNER,
        repo_type: str = "all",
    ) -> str:
        """List repositories in a GitHub organization or user account.

        Args:
            owner: GitHub org/user (default: 'exe-blue')
            repo_type: Filter: 'all', 'public', 'private', 'forks', 'sources' (default: 'all')
        """
        if owner == GITHUB_DEFAULT_OWNER:
            endpoint = f"/orgs/{owner}/repos?type={repo_type}&per_page=50&sort=updated"
        else:
            endpoint = f"/users/{owner}/repos?type={repo_type}&per_page=50&sort=updated"

        result = await _github_api(endpoint)

        if "error" in result:
            return _json(result)

        repos = [
            {
                "name": r["name"],
                "full_name": r["full_name"],
                "private": r["private"],
                "default_branch": r["default_branch"],
                "updated_at": r["updated_at"],
                "language": r.get("language"),
            }
            for r in result["data"]
        ]
        return _json({"count": len(repos), "repos": repos})

    @mcp.tool()
    async def github_get_repo_info(
        repo: str,
        owner: str = GITHUB_DEFAULT_OWNER,
    ) -> str:
        """Get repository metadata including branches, latest commit, etc.

        Args:
            repo: Repository name (e.g., 'aixsignal-webapp')
            owner: GitHub org/user (default: 'exe-blue')
        """
        endpoint = f"/repos/{owner}/{repo}"
        result = await _github_api(endpoint)

        if "error" in result:
            return _json(result)

        r = result["data"]
        return _json({
            "name": r["name"],
            "full_name": r["full_name"],
            "description": r.get("description"),
            "private": r["private"],
            "default_branch": r["default_branch"],
            "language": r.get("language"),
            "size": r.get("size"),
            "open_issues_count": r.get("open_issues_count"),
            "updated_at": r.get("updated_at"),
            "pushed_at": r.get("pushed_at"),
            "topics": r.get("topics", []),
        })

    @mcp.tool()
    async def github_read_claude_md(
        repo: str,
        owner: str = GITHUB_DEFAULT_OWNER,
    ) -> str:
        """Read CLAUDE.md from a repository — the develop mode 기초문서.

        Convenience tool that reads CLAUDE.md from the root of the specified repo.
        Returns the file content directly.

        Args:
            repo: Repository name (e.g., 'aixsignal-webapp', 'REVAID.LINK')
            owner: GitHub org/user (default: 'exe-blue')
        """
        result = await _github_api(f"/repos/{owner}/{repo}/contents/CLAUDE.md?ref=main")

        if "error" in result:
            result = await _github_api(f"/repos/{owner}/{repo}/contents/CLAUDE.md?ref=master")
            if "error" in result:
                return _json({"error": f"CLAUDE.md not found in {owner}/{repo}"})

        data = result["data"]
        if isinstance(data, list):
            return _json({"error": f"CLAUDE.md path is a directory in {owner}/{repo}"})
        if not isinstance(data, dict) or "content" not in data:
            return _json({"error": f"Unexpected response format for CLAUDE.md in {owner}/{repo}"})

        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return content

    # ===================================================================
    # GitHub Write Tools (added 2026-04-27, ADR-024 candidate)
    # ===================================================================

    @mcp.tool()
    async def github_create_branch(
        repo: str,
        new_branch: str,
        owner: str = GITHUB_DEFAULT_OWNER,
        from_branch: str = "main",
    ) -> str:
        """Create a new branch from an existing branch.

        Use before pushing files when introducing a feature/PR.

        Args:
            repo: Repository name (e.g., 'aixsignal-webapp')
            new_branch: Name of the new branch (e.g., 'chore/working-conventions')
            owner: GitHub org/user (default: 'exe-blue')
            from_branch: Source branch to fork from (default: 'main')
        """
        # 1. Get SHA of from_branch
        ref_result = await _github_api(
            f"/repos/{owner}/{repo}/git/refs/heads/{from_branch}"
        )
        if "error" in ref_result:
            return _json(ref_result)

        sha = ref_result["data"]["object"]["sha"]

        # 2. Create new ref
        result = await _github_api(
            f"/repos/{owner}/{repo}/git/refs",
            method="POST",
            data={"ref": f"refs/heads/{new_branch}", "sha": sha},
        )
        return _json(result)

    @mcp.tool()
    async def github_create_or_update_file(
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        owner: str = GITHUB_DEFAULT_OWNER,
    ) -> str:
        """Create or update a single file on a branch with a commit.

        For multi-file PRs, call sequentially; PR squash-merge will collapse commits.
        `content` is plain UTF-8 text (auto-base64 encoded by this tool).

        Args:
            repo: Repository name
            path: File path within repo (e.g., 'docs/adr/ADR-014-aix-naming.md')
            content: Plain UTF-8 file content
            message: Commit message
            branch: Target branch (must exist; use github_create_branch first if needed)
            owner: GitHub org/user (default: 'exe-blue')
        """
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        body = {"message": message, "content": encoded, "branch": branch}

        # If file exists on branch, GitHub API requires SHA — fetch first, ignore 404
        existing = await _github_api(
            f"/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        )
        if "error" not in existing:
            data = existing["data"]
            if isinstance(data, dict) and "sha" in data:
                body["sha"] = data["sha"]

        result = await _github_api(
            f"/repos/{owner}/{repo}/contents/{path}",
            method="PUT",
            data=body,
        )
        if "error" in result:
            return _json(result)

        d = result["data"]
        return _json({
            "path": d.get("content", {}).get("path"),
            "sha": d.get("content", {}).get("sha"),
            "commit_sha": d.get("commit", {}).get("sha"),
            "branch": branch,
            "status": "ok",
        })

    @mcp.tool()
    async def github_create_pull_request(
        repo: str,
        title: str,
        head: str,
        body: str = "",
        base: str = "main",
        owner: str = GITHUB_DEFAULT_OWNER,
        draft: bool = False,
    ) -> str:
        """Open a pull request from `head` branch to `base`.

        Args:
            repo: Repository name
            title: PR title
            head: Source branch (e.g., 'chore/working-conventions')
            body: PR description in Markdown
            base: Target branch (default: 'main')
            owner: GitHub org/user (default: 'exe-blue')
            draft: Open as draft PR (default: False)
        """
        result = await _github_api(
            f"/repos/{owner}/{repo}/pulls",
            method="POST",
            data={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )
        if "error" in result:
            return _json(result)

        d = result["data"]
        return _json({
            "number": d.get("number"),
            "url": d.get("html_url"),
            "state": d.get("state"),
            "head": d.get("head", {}).get("ref"),
            "base": d.get("base", {}).get("ref"),
            "draft": d.get("draft"),
            "status": "ok",
        })

    logger.info(
        "Bridge tools registered: "
        "aixsignal_execute_sql, aixsignal_apply_migration, "
        "aixsignal_list_tables, aixsignal_describe_table, "
        "aixsignal_list_functions, "
        "github_read_file, github_list_directory, github_search_code, "
        "github_list_repos, github_get_repo_info, github_read_claude_md, "
        "github_create_branch, github_create_or_update_file, github_create_pull_request"
    )
