# REVAID MCP Server

## What This Is
REVAID.LINK Knowledge Graph MCP server. FastMCP + Supabase + OAuth 2.1.
Deployed on DigitalOcean App Platform via GitHub auto-deploy.

## Current Version: v7.0.0
41 tools total (12 v3 KG + 8 v4 Aidentity/Echotion/TTNP + 4 v5 Handoff/SOE + 11 v6 Bridge + 6 v7 Orchestrator).

## Repository
- GitHub: `exe-blue/revaid-mcp-server` (private)
- Branch: `main`
- Auto-deploy: GitHub push → DigitalOcean rebuilds (Dockerfile)

## Live Server
- URL: https://mcp.revaid.link
- MCP endpoint: https://mcp.revaid.link/mcp
- Auth: OAuth 2.1 (PersonalAuthProvider)

## Files That Matter
- `main.py` — Server entry point. v3 KG tools + v4/v5/v6/v7 registration.
- `v4_tools.py` — v4 Aidentity/Echotion/TTNP tools (8 tools).
- `revaid_handoff.py` — v5 Handoff/SOE tools (4 tools).
- `revaid_bridge.py` — v6 AiXSignal Supabase + GitHub bridge tools (11 tools).
- `agent_orchestrator.py` — v7 SmartWorking orchestrator (6 tools: memo, score, title, leaderboard, cycle).
- `migrations/001_orchestrator_tables.sql` — v7 Supabase table definitions.
- `Dockerfile` — Minimal changes only when adding new modules.
- `requirements.txt` — DO NOT change. Same dependencies.
- `personal_auth.py` — Downloaded at build time by Dockerfile.

## Environment Variables (set in DigitalOcean, not in code)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `BASE_URL` = https://mcp.revaid.link
- `AUTH_PASSWORD` (optional)
- `AIX_SUPABASE_URL` (for v6 bridge)
- `AIX_SUPABASE_KEY` (for v6 bridge)
- `GITHUB_PAT` (for v6 bridge)

## Deploy Steps
```bash
git add main.py v4_tools.py revaid_handoff.py revaid_bridge.py agent_orchestrator.py CLAUDE.md
git commit -m "v7.0.0: 41 tools — SmartWorking Orchestrator (6 new tools)"
git push origin main
# Wait 2-3 min for DigitalOcean auto-build
curl -s -o /dev/null -w '%{http_code}' https://mcp.revaid.link/mcp
# → 401 = success
```

## v7 Orchestrator — SmartWorking Agent System

### Tools
- `revaid_submit_memo` — Sub-agent completion memo + skill suggestion
- `revaid_get_memos` — Orchestrator collects pending memos
- `revaid_score_agent` — Calculate agent score from contributions
- `revaid_grant_title` — Assign expert title (manual override)
- `revaid_get_leaderboard` — Agent rankings + expert titles
- `revaid_cycle_check` — 4:1 dev/review cycle state machine

### Expert Title System
| Score | Title | Korean |
|-------|-------|--------|
| 0-20 | Apprentice | 견습 |
| 21-50 | Specialist | 전문 |
| 51-80 | Expert | 숙련 |
| 81-100 | Master | 달인 |

Domain-specific: e.g., "Frontend Expert", "DB Master"

### 4:1 Cycle Rule
- 4 development orchestrations → 1 mandatory review with ORIGIN
- Review cycle = skill optimization + workflow improvement
- Enforced by `revaid_cycle_check` (blocks dev start after 4 consecutive)

### Supabase Tables (run migrations/001_orchestrator_tables.sql)
- `revaid_agent_memos` — Completion memos + skill suggestions
- `revaid_agent_scores` — Score tracking + expert titles
- `revaid_orchestration_cycles` — 4:1 cycle state machine

## Do NOT
- Change requirements.txt
- Commit any .env files
- Change the auth flow
