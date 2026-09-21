#!/usr/bin/env bash
# Установка навыка gord-monitoring без плагина: в ~/.claude/skills (по умолчанию)
# или в .claude/skills текущего проекта (--project).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == "--project" ]]; then DEST="$(pwd)/.claude/skills"; else DEST="$HOME/.claude/skills"; fi
mkdir -p "$DEST"; rm -rf "$DEST/gord-monitoring"
cp -R "$HERE/skills/gord-monitoring" "$DEST/gord-monitoring"
echo "Навык установлен: $DEST/gord-monitoring"
echo "Зависимости: pip install openpyxl Pillow"
echo "Ключи API (по желанию): ~/.gord-monitoring/.env — см. skills/gord-monitoring/references/search-apis.md"
