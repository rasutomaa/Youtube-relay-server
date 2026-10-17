#!/bin/bash
# YouTube中継サーバー セットアップスクリプト
set -e

echo "========================================"
echo "  YouTube中継サーバー セットアップ"
echo "========================================"
echo ""

# Python確認
if ! command -v python3 &> /dev/null; then
    echo "[エラー] Python3がインストールされていません"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
    echo "  Arch:          sudo pacman -S python python-pip"
    exit 1
fi
echo "[OK] Python3: $(python3 --version)"

# FFmpeg確認
if ! command -v ffmpeg &> /dev/null; then
    echo "[エラー] FFmpegがインストールされていません"
    echo "  Ubuntu/Debian: sudo apt install ffmpeg"
    echo "  Fedora/RHEL:   sudo dnf install ffmpeg"
    echo "  Arch:          sudo pacman -S ffmpeg"
    exit 1
fi
echo "[OK] FFmpeg: $(ffmpeg -version 2>&1 | head -1)"

# venv作成
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "仮想環境を作成中..."
    python3 -m venv "$VENV_DIR"
fi

# パッケージインストール
echo "パッケージをインストール中..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" -q

echo ""
echo "========================================"
echo "  セットアップ完了!"
echo "  ./start.sh で起動できます"
echo "========================================"
