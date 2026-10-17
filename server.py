#!/usr/bin/env python3
"""
YouTube中継サーバー
Android 2.3.4向けにYouTube動画をH.264 Baseline + AACに変換して配信する
"""

import os
import re
import json
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from flask import (
    Flask, request, render_template, send_file,
    Response, redirect, url_for
)
import yt_dlp

app = Flask(__name__)

BASE_DIR = Path(__file__).parent.resolve()
CACHE_DIR = BASE_DIR / 'cache'
CACHE_DIR.mkdir(exist_ok=True)

# 動画準備タスクの状態管理
# video_id -> {status, progress, title, error}
tasks = {}
tasks_lock = threading.Lock()

# --- ユーティリティ ---

def get_video_path(video_id):
    return CACHE_DIR / f'{video_id}.mp4'


def get_info_path(video_id):
    return CACHE_DIR / f'{video_id}.json'


def get_local_ip():
    """LAN内IPアドレスを取得"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def format_duration(seconds):
    """秒数を mm:ss または h:mm:ss 形式に変換"""
    if not seconds:
        return '--:--'
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def validate_video_id(video_id):
    """YouTube動画IDの形式を検証"""
    return bool(re.match(r'^[a-zA-Z0-9_-]{11}$', video_id))


# --- YouTube検索 ---

def search_youtube(query, max_results=10):
    """yt-dlpを使ってYouTubeを検索"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'skip_download': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(
            f'ytsearch{max_results}:{query}', download=False
        )
        entries = results.get('entries', [])
        videos = []
        for entry in entries:
            if entry and entry.get('id'):
                videos.append({
                    'id': entry.get('id', ''),
                    'title': entry.get('title', '不明'),
                    'duration': entry.get('duration', 0),
                    'channel': entry.get('channel',
                                         entry.get('uploader', '不明')),
                })
        return videos


# --- 動画ダウンロード・変換 ---

def prepare_video(video_id):
    """YouTube動画をダウンロードしてAndroid 2.3互換形式に変換"""
    output_path = get_video_path(video_id)

    # キャッシュ済みならスキップ
    if output_path.exists():
        title = ''
        info_path = get_info_path(video_id)
        if info_path.exists():
            with open(info_path, 'r', encoding='utf-8') as f:
                title = json.load(f).get('title', '')
        with tasks_lock:
            tasks[video_id] = {
                'status': 'ready', 'progress': 100, 'title': title
            }
        return

    with tasks_lock:
        tasks[video_id] = {
            'status': 'downloading', 'progress': 10, 'title': '準備中...'
        }

    temp_dir = CACHE_DIR / 'temp'
    temp_dir.mkdir(exist_ok=True)
    downloaded_file = None

    try:
        # --- ダウンロード ---
        temp_path = str(temp_dir / video_id)

        ydl_opts = {
            'format': (
                'bestvideo[height<=480][vcodec^=avc1]+bestaudio[acodec^=mp4a]/'
                'bestvideo[height<=480]+bestaudio/'
                'best[height<=480]/'
                'best'
            ),
            'outtmpl': temp_path + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f'https://www.youtube.com/watch?v={video_id}',
                download=True
            )
            title = info.get('title', '不明')
            downloaded_file = ydl.prepare_filename(info)

            # yt-dlpがマージ後に拡張子を変えることがあるため探す
            if not os.path.exists(downloaded_file):
                base = os.path.splitext(downloaded_file)[0]
                for ext in ['.mp4', '.mkv', '.webm', '.m4a']:
                    candidate = base + ext
                    if os.path.exists(candidate):
                        downloaded_file = candidate
                        break

        if not os.path.exists(downloaded_file):
            raise FileNotFoundError(
                f'ダウンロードファイルが見つかりません: {downloaded_file}'
            )

        with tasks_lock:
            tasks[video_id]['title'] = title
            tasks[video_id]['status'] = 'transcoding'
            tasks[video_id]['progress'] = 50

        # 動画情報をキャッシュ
        info_path = get_info_path(video_id)
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump({'title': title, 'id': video_id}, f, ensure_ascii=False)

        # --- 変換 (H.264 Baseline + AAC) ---
        cmd = [
            'ffmpeg', '-y',
            '-i', downloaded_file,
            '-c:v', 'libx264',
            '-profile:v', 'baseline',
            '-level', '3.0',
            '-preset', 'fast',
            '-crf', '23',
            '-vf', 'scale=-2:480',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ac', '2',
            '-ar', '44100',
            '-movflags', '+faststart',
            str(output_path),
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1200
        )

        if result.returncode != 0:
            # 出力ファイルが不完全なら削除
            if output_path.exists():
                output_path.unlink()
            stderr_tail = result.stderr[-800:] if result.stderr else ''
            raise RuntimeError(f'FFmpeg変換エラー:\n{stderr_tail}')

        with tasks_lock:
            tasks[video_id]['status'] = 'ready'
            tasks[video_id]['progress'] = 100

    except Exception as e:
        # 出力ファイルが不完全なら削除
        if output_path.exists():
            output_path.unlink()
        with tasks_lock:
            tasks[video_id] = {
                'status': 'error', 'progress': 0,
                'title': '', 'error': str(e)
            }
    finally:
        # 一時ファイルを削除
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except OSError:
                pass


# --- ルーティング ---

@app.route('/')
def index():
    """トップページ（検索フォーム）"""
    return render_template('index.html')


@app.route('/search')
def search():
    """検索結果ページ"""
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index'))
    try:
        results = search_youtube(query)
    except Exception:
        results = []
    return render_template('results.html', query=query, results=results)


@app.route('/watch/<video_id>')
def watch(video_id):
    """動画準備・再生ページ"""
    if not validate_video_id(video_id):
        return '不正な動画IDです', 400

    with tasks_lock:
        task = tasks.get(video_id)

    # 未開始またはエラーなら準備を開始
    if task is None or task.get('status') == 'error':
        thread = threading.Thread(
            target=prepare_video, args=(video_id,), daemon=True
        )
        thread.start()
        time.sleep(0.5)
        with tasks_lock:
            task = tasks.get(video_id, {
                'status': 'downloading', 'progress': 0, 'title': '準備中...'
            })

    return render_template('watch.html', video_id=video_id, task=task)


@app.route('/video/<video_id>')
def video(video_id):
    """動画ファイル配信（Range Requestsサポート）"""
    if not validate_video_id(video_id):
        return '不正な動画IDです', 400

    path = get_video_path(video_id)
    if not path.exists():
        return '動画が見つかりません', 404

    file_size = path.stat().st_size
    range_header = request.headers.get('Range')

    if range_header:
        match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1

            def generate():
                with open(path, 'rb') as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk_size = min(65536, remaining)
                        data = f.read(chunk_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            resp = Response(generate(), status=206, mimetype='video/mp4')
            resp.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
            resp.headers['Content-Length'] = length
            resp.headers['Accept-Ranges'] = 'bytes'
            return resp

    # Range指定なし → 全体を返す
    def generate_full():
        with open(path, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                yield data

    resp = Response(generate_full(), mimetype='video/mp4')
    resp.headers['Content-Length'] = file_size
    resp.headers['Accept-Ranges'] = 'bytes'
    return resp


@app.route('/thumb/<video_id>')
def thumb(video_id):
    """サムネイル画像プロキシ（Android 2.3はHTTPSのYouTubeに接続不可）"""
    if not validate_video_id(video_id):
        return '', 400

    thumb_path = CACHE_DIR / f'thumb_{video_id}.jpg'
    if not thumb_path.exists():
        try:
            url = f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'
            urllib.request.urlretrieve(url, str(thumb_path))
        except Exception:
            return '', 404

    return send_file(str(thumb_path), mimetype='image/jpeg')


@app.route('/cache/clear')
def clear_cache():
    """キャッシュを全削除"""
    count = 0
    for f in CACHE_DIR.iterdir():
        if f.is_file():
            f.unlink()
            count += 1
    with tasks_lock:
        tasks.clear()
    return f'{count}個のファイルを削除しました。<br><a href="/">トップに戻る</a>'


# --- テンプレートフィルター ---

@app.template_filter('duration')
def duration_filter(seconds):
    return format_duration(seconds)


# --- メイン ---

if __name__ == '__main__':
    local_ip = get_local_ip()
    print('=' * 48)
    print('  YouTube中継サーバー')
    print(f'  http://{local_ip}:8080')
    print('  Android端末のブラウザで上記URLにアクセス')
    print('=' * 48)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
