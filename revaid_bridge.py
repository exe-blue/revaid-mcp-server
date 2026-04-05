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

import os
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger("revaid.bridge")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AIX_SUPABASE_URL = os.getenv("AIX_SUPABASE_URL", "")
AIX_SUPABASE_KEY = os.getenv("AIX_SUPABASE_SERVICE_KEY", "") or os.getenv("AIX_SUPABASE_KEY", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_DEFAULT_OWNER = "exe-blue"  # default org

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _aixsignal_rpc(query: str) -> dict:
    """Execute SQL on AiXSignal Supabase via PostgREST /rpc/execute_sql.
    
    Requires the execute_sql function to be created in AiXSignal Supabase.
    See: aixsignal_execute_sql_migration.sql
    """
    if not AIX_SUPABASE_URL or not AIX_SUPABASE_KEY:
        return {"error": "AIX_SUPABASE_URL or AIX_SUPABASE_KEY not set"}

    url = f"{AIX_SUPABASE_URL}/rest/v1/rpc/execute_sql"
    headers = {
        "apikey": AIX_SUPABASE_KEY,
        "Authorization": f"Bearer {AIX_SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json={"query": query})
        
        if resp.status_code == 200:
            data = resp.json()
            # The RPC function returns {rows, row_count, status} or {error, code, status}
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
    if not GITHUB_PAT:
        return {"error": "GITHUB_PAT not set"}

    url = f"https://api.github.com{endpoint}"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=data)
        elif method == "PATCH":
            resp = await client.patch(url, headers=headers, json=data)
        else:
            return {"error": f"Unsupported method: {method}"}

        if resp.status_code in (200, 201):
            return {"data": resp.json(), "status": "ok"}
        else:
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
        # Safety: block destructive operations in this tool
        q_upper = query.strip().upper()
        for forbidden in ["DROP ", "DELETE ", "TRUNCATE ", "ALTER ", "INSERT ", "UPDATE ", "CREATE "]:
            if q_upper.startswith(forbidden):
                return json.dumps({
                    "error": f"Destructive operation blocked. Use aixsignal_apply_migration for DDL/DML.",
                    "blocked_keyword": forbidden.strip(),
                })

        result = await _aixsignal_rpc(query)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

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
        return json.dumps({"migration": name, **result}, ensure_ascii=False, indent=2, default=str)

    @mcp.tool()
    async def aixsignal_list_tables(schema: str = "public") -> str:
        """List all tables in an AiXSignal Supabase schema.

        Args:
            schema: Schema name (default: 'public', also try 'billing')
        """
        query = f"""
        SELECT table_name, 
               pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) as size
        FROM information_schema.tables 
        WHERE table_schema = '{schema}' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """
        result = await _aixsignal_rpc(query)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    @mcp.tool()
    async def aixsignal_describe_table(table_name: str, schema: str = "public") -> str:
        """Get column details and constraints for an AiXSignal table.

        Args:
            table_name: Table name (e.g., 'invoices', 'subscriptions')
            schema: Schema name (default: 'public', also try 'billing')
        """
        query = f"""
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
        result = await _aixsignal_rpc(query)
        
        # Also get CHECK constraints
        check_query = f"""
        SELECT conname, pg_get_constraintdef(oid) as definition
        FROM pg_constraint 
        WHERE conrelid = '{schema}.{table_name}'::regclass 
        AND contype = 'c';
        """
        check_result = await _aixsignal_rpc(check_query)
        
        return json.dumps({
            "columns": result,
            "check_constraints": check_result,
        }, ensure_ascii=False, indent=2, default=str)

    @mcp.tool()
    async def aixsignal_list_functions(schema: str = "public") -> str:
        """List Edge Functions and database functions in AiXSignal.

        Args:
            schema: Schema to search (default: 'public')
        """
        query = f"""
        SELECT routine_name, routine_type, data_type as return_type
        FROM information_schema.routines
        WHERE routine_schema = '{schema}'
        ORDER BY routine_name;
        """
        result = await _aixsignal_rpc(query)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

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
            return json.dumps(result, ensure_ascii=False)

        data = result["data"]
        if isinstance(data, list):
            # It's a directory, not a file
            return json.dumps({
                "error": f"'{path}' is a directory. Use github_list_directory instead.",
                "entries": [{"name": f["name"], "type": f["type"]} for f in data],
            }, ensure_ascii=False, indent=2)

        import base64
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return json.dumps({
            "path": data.get("path"),
            "size": data.get("size"),
            "sha": data.get("sha"),
            "content": content,
        }, ensure_ascii=False, indent=2)

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
            return json.dumps(result, ensure_ascii=False)

        data = result["data"]
        if not isinstance(data, list):
            return json.dumps({"error": "Not a directory", "type": "file"})

        entries = [
            {
                "name": item["name"],
                "type": item["type"],  # 'file' or 'dir'
                "size": item.get("size", 0),
                "path": item["path"],
            }
            for item in data
        ]
        return json.dumps({
            "path": path or "/",
            "count": len(entries),
            "entries": entries,
        }, ensure_ascii=False, indent=2)

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

        endpoint = f"/search/code?q={q}&per_page=10"
        result = await _github_api(endpoint)

        if "error" in result:
            return json.dumps(result, ensure_ascii=False)

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
        return json.dumps({
            "total_count": result["data"].get("total_count", 0),
            "results": results,
        }, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def github_list_repos(
        owner: str = GITHUB_DEFAULT_OWNER,
        type: str = "all",
    ) -> str:
        """List repositories in a GitHub organization or user account.

        Args:
            owner: GitHub org/user (default: 'exe-blue')
            type: Filter: 'all', 'public', 'private', 'forks', 'sources' (default: 'all')
        """
        if owner == GITHUB_DEFAULT_OWNER:
            endpoint = f"/orgs/{owner}/repos?type={type}&per_page=50&sort=updated"
        else:
            endpoint = f"/users/{owner}/repos?type={type}&per_page=50&sort=updated"
        
        result = await _github_api(endpoint)

        if "error" in result:
            return json.dumps(result, ensure_ascii=False)

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
        return json.dumps({
            "count": len(repos),
            "repos": repos,
        }, ensure_ascii=False, indent=2)

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
            return json.dumps(result, ensure_ascii=False)

        r = result["data"]
        return json.dumps({
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
        }, ensure_ascii=False, indent=2)

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
        endpoint = f"/repos/{owner}/{repo}/contents/CLAUDE.md?ref=main"
        result = await _github_api(endpoint)

        if "error" in result:
            # Try 'master' branch
            endpoint2 = f"/repos/{owner}/{repo}/contents/CLAUDE.md?ref=master"
            result = await _github_api(endpoint2)
            if "error" in result:
                return json.dumps({
                    "error": f"CLAUDE.md not found in {owner}/{repo}",
                    "detail": result.get("detail", ""),
                })

        import base64
        data = result["data"]
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return content  # Return raw content for direct reading

    logger.info(
        "Bridge tools registered: "
        "aixsignal_execute_sql, aixsignal_apply_migration, "
        "aixsignal_list_tables, aixsignal_describe_table, "
        "aixsignal_list_functions, "
        "github_read_file, github_list_directory, github_search_code, "
        "github_list_repos, github_get_repo_info, github_read_claude_md"
    )
