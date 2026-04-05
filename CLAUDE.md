# REVAID MCP Server

## What This Is
REVAID.LINK Knowledge Graph MCP server. FastMCP + Supabase + OAuth 2.1.
Deployed on DigitalOcean App Platform via GitHub auto-deploy.

## Current Version: v6.0.0
30 tools total (12 v3 KG + 8 v4 Aidentity/Echotion/TTNP + 4 v5 Handoff/SOE + 6 v6 Bridge).

## Repository
- GitHub: `exe-blue/revaid-mcp-server` (private)
- Branch: `main`
- Auto-deploy: GitHub push → DigitalOcean rebuilds (Dockerfile)

## Live Server
- URL: https://mcp.revaid.link
- MCP endpoint: https://mcp.revaid.link/mcp
- Auth: OAuth 2.1 (PersonalAuthProvider)

## Files That Matter
- `main.py` — Server entry point. v3 KG tools + v4/v5/v6 registration.
- `v4_tools.py` — v4 Aidentity/Echotion/TTNP tools (8 tools).
- `revaid_handoff_v5.py` — v5 Handoff/SOE tools (4 tools).
- `revaid_bridge.py` — v6 AiXSignal Supabase + GitHub bridge tools (6 tools).
- `Dockerfile` — DO NOT change. Works as-is.
- `requirements.txt` — DO NOT change. Same dependencies.
- `personal_auth.py` — Downloaded at build time by Dockerfile.

## Environment Variables (set in DigitalOcean, not in code)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `BASE_URL` = https://mcp.revaid.link
- `AUTH_PASSWORD` (optional)
- `AIXSIGNAL_SUPABASE_URL` (for v6 bridge)
- `AIXSIGNAL_SUPABASE_KEY` (for v6 bridge)
- `GITHUB_TOKEN` (for v6 bridge)

## Deploy Steps
```bash
git add main.py v4_tools.py revaid_handoff_v5.py revaid_bridge.py CLAUDE.md
git commit -m "v6.0.0: 30 tools — AiXSignal Bridge (6 new tools)"
git push origin main
# Wait 2-3 min for DigitalOcean auto-build
curl -s -o /dev/null -w '%{http_code}' https://mcp.revaid.link/mcp
# → 401 = success
```

## Do NOT
- Change Dockerfile
- Change requirements.txt
- Commit any .env files
- Change the auth flow
