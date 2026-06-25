#!/usr/bin/env bash
# scripts/install.sh — one-command a2a-orchestrator install
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --version 1.0.0
#   curl -fsSL .../install.sh | bash -s -- --venv ~/.a2a-venv --mcp
#
# Flags:
#   --version VERSION   a2a-orchestrator version to install (default: latest)
#   --venv PATH         Create a venv at PATH (default: ~/.a2a-orchestrator/venv)
#   --no-venv           Install into current Python, no venv
#   --uv                Use uv instead of pip (auto-detected)
#   --mcp               Set up VS Code MCP integration (no prompt)
#   --no-mcp            Skip VS Code MCP integration (no prompt)
#   --help              Show this help
set -euo pipefail

VERSION=""
VENV_PATH="${HOME}/.a2a-orchestrator/venv"
NO_VENV=false
USE_UV=false
MCP_SETUP="ask"
LOCAL_BIN="${HOME}/.local/bin"
REPO="Korrnals/a2a-orchestrator"

usage() { sed -n '2,16p' "$0" | sed 's/^# \?//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --venv) VENV_PATH="$2"; shift 2 ;;
    --no-venv) NO_VENV=true; shift ;;
    --uv) USE_UV=true; shift ;;
    --mcp) MCP_SETUP="yes"; shift ;;
    --no-mcp) MCP_SETUP="no"; shift ;;
    --help|-h) usage ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

echo "╔══════════════════════════════════════════════╗"
echo "║  a2a-orchestrator — MCP server installer     ║"
echo "╚══════════════════════════════════════════════╝"

command -v uv &>/dev/null && USE_UV=true
INSTALL_CMD="pip install"; $USE_UV && INSTALL_CMD="uv pip install"

if [[ -z "$VERSION" ]]; then
  VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
    | grep -oP '"tag_name":\s*"v\K[^"]+' || echo "1.0.0")
fi
echo "Version: ${VERSION}"

if ! $NO_VENV; then
  echo "Creating venv at ${VENV_PATH}..."
  $USE_UV && uv venv "$VENV_PATH" || python3 -m venv "$VENV_PATH"
  source "$VENV_PATH/bin/activate"
fi

echo "Installing a2a-orchestrator..."
$INSTALL_CMD "git+https://github.com/${REPO}.git@v${VERSION}"

if ! $NO_VENV; then
  mkdir -p "$LOCAL_BIN"
  cat > "$LOCAL_BIN/a2a-orchestrator" << EOF
#!/usr/bin/env bash
exec "$VENV_PATH/bin/python3" -m a2a_orchestrator.cli "\$@"
EOF
  chmod +x "$LOCAL_BIN/a2a-orchestrator"
  echo "Launcher: $LOCAL_BIN/a2a-orchestrator"
fi

if [[ "$MCP_SETUP" == "ask" ]]; then
  read -rp "Set up VS Code MCP integration? [Y/n] " r
  case "$r" in [Nn]*) MCP_SETUP="no" ;; *) MCP_SETUP="yes" ;; esac
fi

if [[ "$MCP_SETUP" == "yes" ]]; then
  MCP_FILE="$HOME/.config/Code/User/mcp.json"
  [[ ! -f "$MCP_FILE" ]] && MCP_FILE="/var/home/abyss/.distrobox/vscode-box/home/.config/Code/User/mcp.json"
  PBIN="$NO_VENV" && PBIN=$(which python3); $NO_VENV || PBIN="$VENV_PATH/bin/python3"
  python3 -c "
import json, os
p = '$MCP_FILE'
os.makedirs(os.path.dirname(p), exist_ok=True)
if not os.path.exists(p): open(p,'w').write('{\"servers\":{}}')
d = json.load(open(p))
d.setdefault('servers',{})['a2a-orchestrator'] = {'type':'stdio','command':'$PBIN','args':['-m','a2a_orchestrator']}
json.dump(d, open(p,'w'), indent=2); open(p,'a').write('\n')
print(f'Added a2a-orchestrator to {p}')
"
fi

echo ""
echo "✅ a2a-orchestrator v${VERSION} installed!"
echo "Reload VS Code: Ctrl+Shift+P → Reload Window"
