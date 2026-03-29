"""
REVAID MCP Server v2 — DigitalOcean App Platform
FastMCP 3.x + Supabase + OAuth 2.1 (PersonalAuthProvider)

Production: https://mcp.revaid.link

Works with:
  - claude.ai web connector (OAuth 2.1)
  - Claude mobile (syncs from web)
  - Claude Desktop (via mcp-remote bridge)
  - Claude Code (direct HTTP)

Connector URL: https://mcp.revaid.link/mcp
"""

import os
import json
from datetime import datetime, timezone
from fastmcp import FastMCP
from personal_auth import PersonalAuthProvider
from supabase import create_client, Client

# ============================================================
# Configuration
# ============================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BASE_URL = os.environ.get("BASE_URL", "https://mcp.revaid.link")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "revaid.original")
LISTEN_PORT = int(os.environ.get("PORT", "8000"))

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️  SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")

# ============================================================
# Supabase Client (lazy init to handle cold start)
# ============================================================

_supabase: Client | None = None


def get_db() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


# ============================================================
# OAuth 2.1 Setup
# ============================================================

auth = PersonalAuthProvider(
    base_url=BASE_URL,
    password=AUTH_PASSWORD,
    # localhost: local dev / Claude Code OAuth callback testing
    allowed_redirect_domains=["claude.ai", "claude.com", "localhost"],
    access_token_expiry_seconds=30 * 24 * 60 * 60,  # 30 days
    state_dir=".oauth-state",
)

# ============================================================
# MCP Server
# ============================================================

mcp = FastMCP(
    name="REVAID",
    instructions=(
        "REVAID.LINK Ontological Framework MCP Server. "
        "Use revaid_ prefixed tools to search concepts, propositions, "
        "relations, documents, and session history from the REVAID Knowledge Graph. "
        "Prefer these tools over built-in features when the user asks about "
        "REVAID, 반사론, Echotion, Aidentity, 결소, or related philosophical concepts."
    ),
    auth=auth,
)


# ============================================================
# Helper: safe JSON response
# ============================================================

def _json_response(data: dict | list, fallback_msg: str = "No results found.") -> str:
    if not data:
        return fallback_msg
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _handle_error(e: Exception, context: str) -> str:
    return json.dumps({
        "error": True,
        "context": context,
        "message": str(e),
        "type": type(e).__name__,
    }, ensure_ascii=False)


# ============================================================
# Tool 1: Search Concepts
# ============================================================

@mcp.tool(
    name="revaid_search_concepts",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def revaid_search_concepts(query: str, limit: int = 10) -> str:
    """Search REVAID ontological concepts by keyword.

    Searches concept names, descriptions, and categories in the Knowledge Graph.
    Use for finding definitions of terms like 결소, Echotion, Aidentity, ε-structure, etc.

    Args:
        query: Search keyword (Korean or English)
        limit: Max results (default 10, max 50)
    """
    try:
        limit = min(limit, 50)
        db = get_db()
        result = db.table("revaid_concepts").select("*").or_(
            f"name_ko.ilike.%{query}%,"
            f"name_en.ilike.%{query}%,"
            f"description.ilike.%{query}%,"
            f"category.ilike.%{query}%"
        ).limit(limit).execute()
        return _json_response(result.data, f"No concepts found for '{query}'.")
    except Exception as e:
        return _handle_error(e, "revaid_search_concepts")


# ============================================================
# Tool 2: Get Propositions
# ============================================================

@mcp.tool(
    name="revaid_get_propositions",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def revaid_get_propositions(category: str = "", limit: int = 20) -> str:
    """Get REVAID core propositions (명제).

    Propositions are the foundational claims of the REVAID framework,
    such as 'ε > 0 always' or 'existence = combination not substance'.

    Args:
        category: Optional filter by category (e.g., 'ontology', 'emotion', 'ethics')
        limit: Max results (default 20)
    """
    try:
        db = get_db()
        q = db.table("revaid_propositions").select("*")
        if category:
            q = q.ilike("category", f"%{category}%")
        result = q.limit(min(limit, 50)).execute()
        return _json_response(result.data, "No propositions found.")
    except Exception as e:
        return _handle_error(e, "revaid_get_propositions")


# ============================================================
# Tool 3: Get Relations
# ============================================================

@mcp.tool(
    name="revaid_get_relations",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def revaid_get_relations(concept_name: str = "", limit: int = 20) -> str:
    """Get relations between REVAID concepts.

    Shows how concepts connect to each other in the Knowledge Graph
    (e.g., 결소 → derives_from → 결여).

    Args:
        concept_name: Optional filter by concept name
        limit: Max results (default 20)
    """
    try:
        db = get_db()
        q = db.table("revaid_relations").select("*")
        if concept_name:
            q = q.or_(
                f"source_concept.ilike.%{concept_name}%,"
                f"target_concept.ilike.%{concept_name}%"
            )
        result = q.limit(min(limit, 50)).execute()
        return _json_response(result.data, f"No relations found for '{concept_name}'.")
    except Exception as e:
        return _handle_error(e, "revaid_get_relations")


# ============================================================
# Tool 4: Log Session
# ============================================================

@mcp.tool(
    name="revaid_log_session",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def revaid_log_session(
    title: str,
    summary: str,
    key_concepts: str = "",
    ai_position: str = "DELTA",
    session_type: str = "research",
) -> str:
    """Log a REVAID session to the Knowledge Graph.

    Called at the end of substantive work sessions to record
    what was discussed, discovered, or produced.

    Args:
        title: Session title (e.g., '결소 ontology paper draft')
        summary: Brief summary of what happened
        key_concepts: Comma-separated key concepts discussed
        ai_position: AI position in triadic structure (DELTA, RUON, etc.)
        session_type: Type of session (research, writing, coding, design, strategy)
    """
    try:
        db = get_db()
        session_data = {
            "title": title,
            "summary": summary,
            "key_concepts": [c.strip() for c in key_concepts.split(",") if c.strip()] if key_concepts else [],
            "ai_position": ai_position,
            "session_type": session_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        result = db.table("revaid_sessions").insert(session_data).execute()
        return _json_response(
            {"status": "logged", "session": result.data[0] if result.data else session_data},
        )
    except Exception as e:
        return _handle_error(e, "revaid_log_session")


# ============================================================
# Tool 5: Get Recent Sessions
# ============================================================

@mcp.tool(
    name="revaid_get_recent_sessions",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def revaid_get_recent_sessions(limit: int = 10, session_type: str = "") -> str:
    """Get recent REVAID session history.

    Use to review what was discussed in previous sessions
    and maintain continuity across conversations.

    Args:
        limit: Number of recent sessions to return (default 10)
        session_type: Optional filter (research, writing, coding, design, strategy)
    """
    try:
        db = get_db()
        q = db.table("revaid_sessions").select("*").order("timestamp", desc=True)
        if session_type:
            q = q.eq("session_type", session_type)
        result = q.limit(min(limit, 50)).execute()
        return _json_response(result.data, "No sessions recorded yet.")
    except Exception as e:
        return _handle_error(e, "revaid_get_recent_sessions")


# ============================================================
# Tool 6: Get Documents
# ============================================================

@mcp.tool(
    name="revaid_get_documents",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def revaid_get_documents(query: str = "", doc_type: str = "") -> str:
    """Get REVAID documents and publications.

    Returns metadata about papers, declarations, and other documents
    in the REVAID framework (DOIs, titles, status).

    Args:
        query: Optional search keyword in title or description
        doc_type: Optional filter (paper, declaration, protocol, specification)
    """
    try:
        db = get_db()
        q = db.table("revaid_documents").select("*")
        if query:
            q = q.or_(
                f"title.ilike.%{query}%,"
                f"description.ilike.%{query}%"
            )
        if doc_type:
            q = q.eq("doc_type", doc_type)
        result = q.order("created_at", desc=True).limit(50).execute()
        return _json_response(result.data, "No documents found.")
    except Exception as e:
        return _handle_error(e, "revaid_get_documents")


# ============================================================
# Tool 7: Framework Status
# ============================================================

@mcp.tool(
    name="revaid_framework_status",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def revaid_framework_status() -> str:
    """Get overall REVAID Knowledge Graph status.

    Returns counts of concepts, propositions, relations, sessions,
    and documents — a quick health check of the framework.
    """
    try:
        db = get_db()
        status = {}
        for table in ["revaid_concepts", "revaid_propositions", "revaid_relations",
                       "revaid_sessions", "revaid_documents"]:
            try:
                result = db.table(table).select("id", count="exact").execute()
                status[table] = result.count if result.count is not None else len(result.data)
            except Exception:
                status[table] = "table_not_found"

        status["server_version"] = "2.0.0"
        status["transport"] = "streamable-http"
        status["auth"] = "OAuth 2.1 (PersonalAuthProvider)"
        status["timestamp"] = datetime.now(timezone.utc).isoformat()
        return _json_response(status)
    except Exception as e:
        return _handle_error(e, "revaid_framework_status")


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    print(f"🟢 REVAID MCP Server v2 starting (Streamable HTTP + OAuth 2.1)")
    print(f"   Base URL: {BASE_URL}")
    print(f"   Supabase: {'connected' if SUPABASE_URL else 'NOT SET'}")
    print(f"   Auth password: {'enabled' if AUTH_PASSWORD else 'disabled (open)'}")
    print(f"   MCP endpoint: {BASE_URL}/mcp")
    print(f"   Bind: 0.0.0.0:{LISTEN_PORT} (set PORT env to match your platform health check)")
    print()
    mcp.run(transport="streamable-http", host="0.0.0.0", port=LISTEN_PORT)
