#!/bin/bash
# YouTube中継サーバー 起動スクリプト
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "先に ./setup.sh を実行してください"
    exit 1
fi

echo "YouTube中継サーバーを起動します..."
"$VENV_DIR/bin/python" "$SCRIPT_DIR/server.py"
