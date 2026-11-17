#!/usr/bin/env bash
set -euo pipefail

# Vietnamese labels/output must not crash on a non-UTF-8 console.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "== Tool nha dat: bootstrap =="

PYTHON_BIN="$(command -v python3 || command -v python)"
"$PYTHON_BIN" --version

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

if [[ -x .venv/bin/python ]]; then
  VENV_PYTHON=".venv/bin/python"
else
  VENV_PYTHON=".venv/Scripts/python.exe"
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

echo "== Cai Chromium cho Playwright =="
"$VENV_PYTHON" -m playwright install chromium

# Register the Playwright MCP server for Claude Code in this project.
if command -v claude &>/dev/null; then
  if claude mcp list 2>/dev/null | grep -q '^playwright:'; then
    echo "Playwright MCP da duoc cau hinh, bo qua."
  else
    echo "== Dang ky Playwright MCP =="
    claude mcp add playwright -- npx -y '@playwright/mcp@0.0.85' --browser chromium --user-data-dir "$PROJECT_ROOT/Temp/browser-profile"
  fi
else
  echo "[WARN] Khong tim thay claude CLI. Bo qua Playwright MCP; xem README de cau hinh thu cong."
fi

mkdir -p Temp research/jobs
"$VENV_PYTHON" -m src.property_tool.cli "https://example.com" --output "Temp/smoke-test.xlsx"

echo
echo "Cai dat thanh cong."
echo "Python environment: $VENV_PYTHON"
echo "Smoke test: Temp/smoke-test.xlsx"
echo
echo "Kiem tra lai MCP:"
echo "  claude mcp list"
echo
echo "Chay tool:"
echo "  $VENV_PYTHON -m src.property_tool.cli --urls-file urls.txt --output research/jobs/property-data.xlsx"