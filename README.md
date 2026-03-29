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
