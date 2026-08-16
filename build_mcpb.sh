#!/usr/bin/env bash
# Empaqueta Mail-MCP-r como extensión .mcpb para Claude Desktop.
# Uso: ./build_mcpb.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$HOME/mcpb-bundles/mail-mcp-r"
VENV_PY="$REPO/.venv/bin/python"
ENTRY="$REPO/workspace/mcp_server/stdio.py"
OUT="mail-mcp"

mkdir -p "$BUILD_DIR"

cat > "$BUILD_DIR/manifest.json" <<EOF
{
  "\$schema": "https://raw.githubusercontent.com/anthropics/mcpb/main/dist/mcpb-manifest.schema.json",
  "manifest_version": "0.1",
  "name": "mail-mcp-r",
  "display_name": "Mail-MCP-r",
  "version": "0.1.0",
  "description": "Servidor MCP para correo",
  "author": { "name": "Martín" },
  "server": {
    "type": "python",
    "entry_point": "workspace/mcp_server/stdio.py",
    "mcp_config": {
      "command": "$VENV_PY",
      "args": ["$ENTRY"]
    }
  }
}
EOF

cd "$BUILD_DIR"

if ! command -v mcpb &> /dev/null; then
  echo "Instalando mcpb CLI..."
  npm install -g @anthropic-ai/mcpb
fi

mcpb pack . "$OUT"

echo ""
echo "Listo: $BUILD_DIR/$OUT"
echo "Para instalar: Claude Desktop -> Settings -> Extensions -> Advanced settings -> Extension Developer -> Install Extension..."
