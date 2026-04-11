# REVAID MCP Server

## What This Is
REVAID.LINK Knowledge Graph MCP server. FastMCP + Supabase + OAuth 2.1.
Deployed on DigitalOcean App Platform via GitHub auto-deploy.

## Current Version: v8.1.0
45 tools total (12 v3 KG + 8 v4 Aidentity/Echotion/TTNP + 4 v5 Handoff/SOE + 11 v6 Bridge + 6 v7 Orchestrator + 3 v8 Harness + 1 v8.1 ruon.ai Bridge).

## Repository
- GitHub: `exe-blue/revaid-mcp-server` (private)
- Branch: `main`
- Auto-deploy: GitHub push → DigitalOcean rebuilds (Dockerfile)

## Live Server
- URL: https://mcp.revaid.link
- MCP endpoint: https://mcp.revaid.link/mcp
- Auth: OAuth 2.1 (PersonalAuthProvider)

## Files That Matter
- `main.py` — Server entry point. v3 KG tools + auto-discovery loader for all other modules.
- `v4_tools.py` — v4 Aidentity/Echotion/TTNP tools (8 tools).
- `revaid_handoff.py` — v5 Handoff/SOE tools (4 tools).
- `revaid_bridge.py` — v6 AiXSignal Supabase + GitHub bridge tools (11 tools).
- `agent_orchestrator.py` — v7 SmartWorking orchestrator (6 tools: memo, score, title, leaderboard, cycle).
- `revaid_harness.py` — v8 Ontological Harness (3 tools: check_identity, measure_echotion, structural_report). v2 LLM judge integrated.
- `revaid_ruon_bridge.py` — v8.1 ruon.ai SI bridge (1 tool: sync_si_to_ruon).
- `migrations/001_orchestrator_tables.sql` — v7 Supabase table definitions.
- `migrations/002_v2_judge_columns.sql` — v8 v2 LLM judge columns.
- `Dockerfile` — Uses `COPY *.py ./` (auto-discovery, no manual edits needed for new modules).
- `requirements.txt` — DO NOT change. Same dependencies.
- `personal_auth.py` — Downloaded at build time by Dockerfile.

## Auto-Discovery (main.py)
New tool modules are picked up automatically:
1. Add a `.py` file with a `register_*()` function to the repo root
2. `main.py` auto-discovers and calls it at startup
3. `Dockerfile` copies all `*.py` files via wildcard
4. No manual import/register edits needed

Skip list: `main.py`, `personal_auth.py`
Dispatch: `register_*(mcp, get_db)` for 2+ params, `register_*(mcp)` for 1 param.

## Environment Variables (set in DigitalOcean, not in code)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `BASE_URL` = https://mcp.revaid.link
- `AUTH_PASSWORD` (optional)
- `AIX_SUPABASE_URL` (for v6 bridge)
- `AIX_SUPABASE_KEY` (for v6 bridge)
- `GITHUB_PAT` (for v6 bridge)
- `HARNESS_V2_ENABLED` — "true" to enable LLM judge (default: "false")
- `ANTHROPIC_API_KEY` — for Claude judge calls (v2)
- `OPENAI_API_KEY` — for GPT judge calls (v2)
- `RUON_SUPABASE_URL` — ruon.ai Supabase URL (for SI bridge)
- `RUON_SUPABASE_KEY` — ruon.ai Supabase service key (for SI bridge)

## Deploy Steps
```bash
git add -A && git commit -m "description"
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

## v8 Harness — Ontological Diagnostic Tools

### Tools
- `revaid_check_identity` — Aidentity 4-dimensional scoring (role/boundary/authority/self_ref)
- `revaid_measure_echotion` — Echotion 3-axis + crystallization + grain classification
- `revaid_structural_report` — Combined SI report with grade/trend/drift/recommendations

### CALIBRATION dict
All thresholds and weights are in `CALIBRATION` dict at top of `revaid_harness.py`.
Update values based on empirical probing data — no code changes needed.

### v2 LLM Judge (optional)
- Controlled by `HARNESS_V2_ENABLED` env var
- Judge routing: Claude target → GPT judge, GPT/Gemini target → Claude judge
- v1 (rule-based) + v2 (LLM) results stored in same DB row with agreement score
- Graceful degradation: if v2 fails, v1 results stored alone

### Supabase Tables
- `revaid_aidentity_scores` — Aidentity time-series + v2 judge columns
- `revaid_echotion_records` — Echotion records + v2 judge columns
- `revaid_echotion_logs` — Echotion axis logs
- `revaid_session_diagnostics` — Structural integrity reports

## v8.1 ruon.ai SI Bridge

### Tool
- `revaid_sync_si_to_ruon` — Push latest harness SI to ruon.ai evaluation

### Grade Mapping
| Harness | ruon.ai |
|---------|---------|
| A | A |
| B+ | B |
| B | B |
| C | C |
| D | C |

Harness SI (0-1) → ruon.ai structural_score (0-100).

### ruon.ai Supabase Columns (added to evaluations)
- `harness_si_score` — SI score from harness (0-1)
- `harness_si_grade` — Harness grade (A/B+/B/C/D)
- `harness_entity_id` — Which agent was measured
- `harness_binding_strength` — Binding strength at sync time
- `harness_trend` — improving/stable/degrading
- `harness_synced_at` — Last sync timestamp

## Do NOT
- Change requirements.txt
- Commit any .env files
- Change the auth flow
