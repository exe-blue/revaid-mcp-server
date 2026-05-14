# REVAID MCP Server v2 — OAuth 2.1 for claude.ai

## 변경사항 (v1 → v2)

| 항목 | v1 | v2 |
|---|---|---|
| FastMCP | mcp[cli] (SDK 내장) | fastmcp 3.1.x (독립 패키지) |
| 트랜스포트 | SSE | Streamable HTTP |
| 인증 | 없음 | OAuth 2.1 (DCR + PKCE) |
| claude.ai 커넥터 | ❌ | ✅ |
| Claude 모바일 | ❌ | ✅ (웹에서 싱크) |
| Claude Desktop | ✅ (직접 SSE) | ✅ (mcp-remote 브릿지) |
| Claude Code | ✅ | ✅ |
| Tool 이름 | generic | `revaid_` 접두사 (빌트인 충돌 방지) |

## Deployment (DigitalOcean App Platform)

### 1. GitHub repo에 코드 push

```bash
git add main.py requirements.txt Dockerfile .gitignore .env.example README.md
git commit -m "v2: OAuth 2.1 + Streamable HTTP + DigitalOcean deploy"
git push origin main
```

### 2. DigitalOcean App Platform에서 앱 생성

1. [cloud.digitalocean.com/apps](https://cloud.digitalocean.com/apps) → **Create App**
2. Source: **GitHub** → `exe-blue/revaid-mcp-server` 선택
3. Branch: `main`
4. Type: **Web Service** (Dockerfile 자동 감지)
5. Plan: **Basic ($5/mo)** — 크레딧으로 커버

### 3. 환경변수 설정

App Settings → **Environment Variables**에서 추가:

```
SUPABASE_URL         = https://your-project.supabase.co
SUPABASE_SERVICE_KEY = eyJ...your-service-key
BASE_URL             = https://mcp.revaid.link
AUTH_PASSWORD         = (선택)
```

⚠️ **BASE_URL**은 브라우저·OAuth가 실제로 접속하는 **공개 URL**과 같아야 합니다. 커스텀 도메인이 `https://mcp.revaid.link`이면 위 값 그대로 두면 됩니다. 아직 `*.ondigitalocean.app`만 쓰는 단계라면 그 URL을 `BASE_URL`에 넣고, DNS를 연결한 뒤 `https://mcp.revaid.link`로 바꿉니다.

### 4. 배포 확인

```bash
# OAuth 디스커버리 확인
curl -s https://mcp.revaid.link/.well-known/oauth-authorization-server | python3 -m json.tool
```

### 5. claude.ai 연결

1. claude.ai → Settings → Connectors → **Add custom connector**
2. URL: `https://mcp.revaid.link/mcp`
3. OAuth 승인 화면 → 승인
4. 완료! 모바일에도 자동 싱크

### 6. Claude Desktop 연결

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "revaid": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.revaid.link/mcp"]
    }
  }
}
```

> Node.js 필요. mcp-remote가 OAuth 플로우를 브라우저에서 처리.

### 7. Claude Code 연결

```bash
claude mcp add revaid --transport http "https://mcp.revaid.link/mcp"
```

## 7 Tools

| Tool | 설명 | Read/Write |
|------|------|:---:|
| `revaid_search_concepts` | 개념 키워드 검색 | R |
| `revaid_get_propositions` | 명제 조회 | R |
| `revaid_get_relations` | 개념 간 관계 | R |
| `revaid_log_session` | 세션 기록 | W |
| `revaid_get_recent_sessions` | 최근 세션 조회 | R |
| `revaid_get_documents` | 문서 목록 | R |
| `revaid_framework_status` | 전체 현황 | R |

## 연결 검증

```bash
# 1. OAuth 디스커버리 (JSON 응답이면 정상)
curl -s https://mcp.revaid.link/.well-known/oauth-authorization-server | python3 -m json.tool

# 2. DCR 테스트 (client_id 반환이면 정상)
curl -s https://mcp.revaid.link/register -X POST \
  -H "Content-Type: application/json" \
  -d '{"client_name":"test","redirect_uris":["https://claude.ai/api/mcp/auth_callback"]}'

# 3. MCP 엔드포인트 (401이면 정상 — 인증 필요 상태)
curl -s -o /dev/null -w "%{http_code}" https://mcp.revaid.link/mcp

# 4. Protected resource metadata
curl -s https://mcp.revaid.link/.well-known/oauth-protected-resource/mcp | python3 -m json.tool
```

4개 다 통과하면 claude.ai에서 커넥터 추가.

## 보안 구조

1. DCR은 열림 — claude.ai OAuth 플로우에 필요
2. /authorize는 도메인 제한 — claude.ai, claude.com, localhost만
3. 토큰은 opaque (랜덤 hex, JWT 아님)
4. 토큰 30일 유효, refresh로 갱신 가능
5. 토큰 파일 .oauth-state/에 저장 — 서버 재시작해도 유지

## DigitalOcean SSH Execution (`do_ssh_exec`)

`do_ssh_exec` runs a single command or uploads-and-runs a multiline bash
script on a DigitalOcean droplet over SSH. It is the entry point for
all server-side automation (Caddy patches, n8n workflow deploys,
debugging) that the DO REST API does not expose.

### Security model — deny-all by default

| Control | Behaviour |
|---|---|
| `DO_SSH_ALLOWED_HOSTS` | Comma-separated allowlist. **Empty = every call rejected.** |
| Private key | Loaded from `DO_SSH_PRIVATE_KEY_PEM` (inline) or `DO_SSH_PRIVATE_KEY_PATH` (file). One must be set. |
| Host key check | Strict against `DO_SSH_KNOWN_HOSTS_PATH` (default `/etc/revaid-mcp/known_hosts`). Set `DO_SSH_TOFU=true` only for bootstrap. |
| Command / script size | 10 KB max. |
| stdout / stderr | 1 MB each; excess is truncated with a marker. |
| Timeout | Default 60 s, hard cap 600 s. |
| Concurrency | 5 simultaneous SSH sessions. |
| Audit | Every call → logger `revaid.audit.ssh` (host, mode, exit, duration, first 200 chars of command). Key material is never logged. |

### ORIGIN-side setup

```bash
# 1. Inject private key (chmod 600 mandatory)
cat > /etc/revaid-mcp/ssh_key.pem <<'EOF'
-----BEGIN OPENSSH PRIVATE KEY-----
<paste full PEM here>
-----END OPENSSH PRIVATE KEY-----
EOF
chmod 600 /etc/revaid-mcp/ssh_key.pem

# 2. Register env vars
cat >> /etc/revaid-mcp/secrets.env <<'EOF'
DO_SSH_PRIVATE_KEY_PATH=/etc/revaid-mcp/ssh_key.pem
DO_SSH_ALLOWED_HOSTS=159.223.80.77,n8n.aixsignal.pro
DO_SSH_KNOWN_HOSTS_PATH=/etc/revaid-mcp/known_hosts
EOF
chmod 600 /etc/revaid-mcp/secrets.env

# 3. Seed known_hosts with target host fingerprints
ssh-keyscan -H 159.223.80.77 >> /etc/revaid-mcp/known_hosts
chmod 644 /etc/revaid-mcp/known_hosts

# 4. Restart
systemctl restart revaid-mcp
```

### Usage

Single command (droplet id auto-resolves to public IPv4):

```json
{
  "tool": "do_ssh_exec",
  "params": {
    "droplet_id": 570463287,
    "command": "uname -a && whoami && date -Iseconds"
  }
}
```

Multiline script (uploaded to `/tmp/revaid_<uuid>.sh`, executed, removed):

```json
{
  "tool": "do_ssh_exec",
  "params": {
    "host": "159.223.80.77",
    "user": "root",
    "script": "#!/bin/bash\nset -euo pipefail\napt-get update\napt-get install -y jq",
    "timeout": 300
  }
}
```

Response shape:

```json
{
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "duration_seconds": 1.823,
  "host": "159.223.80.77",
  "executed_at": "2026-05-14T01:23:45+00:00",
  "stdout_truncated": false,
  "stderr_truncated": false
}
```

Error responses include `error: true`, `status_code`, `message`. Common rejects:

* `host X not in DO_SSH_ALLOWED_HOSTS` (403) — extend the allowlist.
* `DO_SSH_ALLOWED_HOSTS is not set; do_ssh_exec is deny-all` (403) — configure first.
* `do_ssh_exec disabled: neither DO_SSH_PRIVATE_KEY_PEM nor ..._PATH is set` (503).
* `timeout after Ns` (returned as `{exit_code: -1, timed_out: true}`).

## 트러블슈팅

**"Failed to generate authorization URL" on claude.ai**
- v1(SSE, 인증 없음)이 아직 돌고 있으면 이 에러 발생
- v2 파일로 교체 후 서버 재시작 필요
- /.well-known/oauth-authorization-server 응답 확인

**Claude Desktop 브라우저 루프**
- 2026-03-28 기준 known issue (GitHub #40102)
- claude.ai 웹은 정상 작동, Desktop은 mcp-remote로 우회

**Tools 발견은 되는데 호출 안 됨**
- tool 이름이 빌트인과 충돌하면 Claude가 빌트인 선호
- v2에서 revaid_ 접두사 적용으로 해결

**Supabase 연결 실패**
- SUPABASE_SERVICE_KEY (anon key 아님!) 확인
- Supabase 대시보드에서 프로젝트가 활성 상태인지 확인
