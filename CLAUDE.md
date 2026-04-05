# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

REVAID MCP Server v3 — a FastMCP-based Model Context Protocol server exposing the REVAID ontological knowledge graph (Supabase-backed) via OAuth 2.1 authenticated Streamable HTTP transport. 12 tools total (8 read, 4 write) with `revaid_` prefix.

## Commands

```bash
# Local dev
bash setup.sh              # One-time setup (installs deps, downloads personal_auth.py)
python main.py             # Start server on port 8000

# Dependencies
pip install -r requirements.txt

# Docker
docker build -t revaid-mcp .
docker run -p 8080:8080 --env-file .env revaid-mcp

# Verify deployment
curl -s https://mcp.revaid.link/.well-known/oauth-authorization-server | python3 -m json.tool
curl -s -o /dev/null -w "%{http_code}" https://mcp.revaid.link/mcp  # 401 = auth working
```

## Architecture

Single-file server (`main.py`) with two main components:

- **MCP Tools**: All defined as `@mcp.tool()` functions in `main.py`. Each tool queries/writes Supabase tables (`revaid_concepts`, `revaid_propositions`, `revaid_relations`, `revaid_sessions`, `revaid_documents`). Two diagnostic tools (`revaid_diagnose_response`, `revaid_score_aidentity`) are pure computation — no DB calls.
- **OAuth 2.1 Auth** (`personal_auth.py`): `PersonalAuthProvider` extends FastMCP's `InMemoryOAuthProvider` with redirect domain restriction, optional password gate, token persistence to `.oauth-state/oauth_tokens.json`, and configurable token expiry. DCR is open (required for claude.ai flow).

## Environment Variables

```
SUPABASE_URL           # Supabase project URL
SUPABASE_SERVICE_KEY   # Service role key (not anon key)
BASE_URL               # Public URL (must match what browsers/OAuth see)
AUTH_PASSWORD           # Optional extra authorization gate
```

## Deployment

Deployed on DigitalOcean App Platform via Dockerfile. Also has Railway (`railway.toml`, `nixpacks.toml`) and generic PaaS (`Procfile`) configs. The Dockerfile downloads `personal_auth.py` from GitHub at build time; the local copy is also in the repo.

## Key Details

- Transport: Streamable HTTP (not SSE) — required for claude.ai connector
- Server listens on port 8000 locally; Dockerfile exposes 8080 (override with `PORT` env)
- Supabase client is lazily initialized via `get_db()` singleton
- Tool names use `revaid_` prefix to avoid collision with Claude's built-in tools
- Token format: opaque `pat_`/`prt_` prefixed hex strings, not JWT
- Allowed OAuth redirect domains: claude.ai, claude.com, localhost
