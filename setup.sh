#!/bin/bash
# REVAID MCP Server v2 — Setup Script
# Run this once in Replit Shell: bash setup.sh

set -e
echo "🔧 REVAID MCP Server v2 Setup"
echo "=============================="
echo ""

# 1. Install Python dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet
echo "   ✅ Dependencies installed"
echo ""

# 2. Download personal_auth.py (OAuth 2.1 provider)
echo "🔑 Downloading PersonalAuthProvider..."
if curl -fsSL -o personal_auth.py \
    "https://raw.githubusercontent.com/crumrine/fastmcp-personal-auth/main/personal_auth.py" 2>/dev/null; then
    echo "   ✅ personal_auth.py downloaded"
else
    echo "   ⚠️  curl failed — trying wget..."
    if wget -q -O personal_auth.py \
        "https://raw.githubusercontent.com/crumrine/fastmcp-personal-auth/main/personal_auth.py" 2>/dev/null; then
        echo "   ✅ personal_auth.py downloaded (wget)"
    else
        echo "   ❌ Could not download. Get it manually from:"
        echo "      https://github.com/crumrine/fastmcp-personal-auth/blob/main/personal_auth.py"
        echo "      Copy the raw file content into personal_auth.py in your Replit project."
        exit 1
    fi
fi
echo ""

# 3. Create OAuth state directory
mkdir -p .oauth-state
echo "   ✅ .oauth-state directory created"
echo ""

# 4. Verify installation
echo "🧪 Verifying..."
python -c "from fastmcp import FastMCP; print(f'   FastMCP: OK')" 2>/dev/null || echo "   ❌ FastMCP import failed"
python -c "from supabase import create_client; print(f'   Supabase: OK')" 2>/dev/null || echo "   ❌ Supabase import failed"
python -c "from personal_auth import PersonalAuthProvider; print(f'   PersonalAuth: OK')" 2>/dev/null || echo "   ❌ PersonalAuth import failed"
echo ""

# 5. Instructions
echo "=============================="
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo ""
echo "1. Set Replit Secrets (🔒 icon in sidebar):"
echo "   SUPABASE_URL       = https://your-project.supabase.co"
echo "   SUPABASE_SERVICE_KEY = eyJ...your-service-key"
echo "   BASE_URL            = https://revaid-mcp-server.replit.app"
echo "   AUTH_PASSWORD        = (optional, for extra security gate)"
echo ""
echo "2. Click Run (or: python main.py)"
echo ""
echo "3. Connect on claude.ai:"
echo "   Settings → Connectors → Add custom connector"
echo "   URL: https://revaid-mcp-server.replit.app/mcp"
echo ""
echo "4. Verify with curl:"
echo "   curl -s https://revaid-mcp-server.replit.app/.well-known/oauth-authorization-server | python3 -m json.tool"
echo ""
