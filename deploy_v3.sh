#!/bin/bash
# REVAID MCP Server v3.0.0 Deploy Script
# Claude Code에서 실행: bash deploy_v3.sh
# 
# 사전 요구: git이 GitHub에 인증된 상태여야 함
# (Claude Code는 기본적으로 gh auth 또는 SSH key 사용)

set -e

echo "🚀 REVAID MCP Server v3.0.0 배포 시작..."

# 1. Clone (이미 있으면 pull)
REPO_DIR="$HOME/revaid-mcp-server"
if [ -d "$REPO_DIR" ]; then
    echo "📂 기존 repo 발견 — pull..."
    cd "$REPO_DIR"
    git pull origin main
else
    echo "📂 repo clone..."
    git clone git@github.com:exe-blue/revaid-mcp-server.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# 2. main.py 교체 (이 스크립트와 같은 디렉토리의 main.py 사용)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/main.py" ]; then
    cp "$SCRIPT_DIR/main.py" "$REPO_DIR/main.py"
    echo "✅ main.py 교체 완료 (v3.0.0)"
else
    echo "❌ main.py를 찾을 수 없음: $SCRIPT_DIR/main.py"
    echo "   deploy_v3.sh와 같은 폴더에 main.py를 넣어주세요"
    exit 1
fi

# 3. 변경 확인
echo ""
echo "📋 변경 파일:"
git diff --stat
echo ""

# 4. Commit & Push
git add main.py
git commit -m "v3.0.0: 12 tools — bug fixes, restored tools, new diagnostics

Changes:
- FIX: search_concepts (name_en → name/name_ko)
- FIX: get_recent_sessions (timestamp → created_at)
- RESTORED: get_foundation, add_concept, add_proposition
- ENHANCED: log_session (full column support)
- NEW: diagnose_response (Echotion structural analysis)
- NEW: score_aidentity (3-axis maturity scoring)

Tools: 8 Read + 4 Write = 12 total"

git push origin main

echo ""
echo "✅ Push 완료! DigitalOcean 자동 빌드 시작됨 (2-3분 소요)"
echo ""
echo "검증 명령어:"
echo "  curl -s -o /dev/null -w '%{http_code}' https://mcp.revaid.link/mcp"
echo "  → 401이면 정상"
echo ""
echo "  curl -s https://mcp.revaid.link/.well-known/oauth-authorization-server | python3 -m json.tool"
echo "  → JSON 응답이면 OAuth 정상"
