#!/usr/bin/env bash
# scripts/uninstall.sh — remove a2a-cli
set -euo pipefail

VENV_PATH="${HOME}/.a2a-orchestrator/venv"
LOCAL_BIN="${HOME}/.local/bin"

echo "Removing a2a-orchestrator..."

# Remove venv
if [[ -d "$VENV_PATH" ]]; then
  rm -rf "$VENV_PATH"
  echo "Removed venv: $VENV_PATH"
fi

# Remove launcher
if [[ -f "$LOCAL_BIN/a2a-cli" ]]; then
  rm -f "$LOCAL_BIN/a2a-cli"
  echo "Removed launcher: $LOCAL_BIN/a2a-cli"
fi

# Remove from mcp.json
MCP_FILE="$HOME/.config/Code/User/mcp.json"
[[ ! -f "$MCP_FILE" ]] && MCP_FILE="/var/home/abyss/.distrobox/vscode-box/home/.config/Code/User/mcp.json"
if [[ -f "$MCP_FILE" ]] && grep -q '"a2a-cli"' "$MCP_FILE"; then
  python3 -c "
import json
p = '$MCP_FILE'
d = json.load(open(p))
d.get('servers', {}).pop('a2a-orchestrator', None)
json.dump(d, open(p,'w'), indent=2); open(p,'a').write('\n')
print(f'Removed a2a-cli from {p}')
"
fi

echo "✅ a2a-cli uninstalled!"
