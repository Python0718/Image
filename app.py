import os
import zipfile
import subprocess
from flask import Flask, render_template_string, request, send_file

app = Flask(__name__)
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>M3U8 / MP4 Converter</title>
    <style>
        body { font-family: sans-serif; margin: 40px; background: #f9f9f9; color: #333; }
        .card { background: white; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        input, button { margin: 8px 0; padding: 8px; width: 100%; box-sizing: border-box; }
        button { background: #0070f3; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        button:hover { background: #0051a2; }
        .row { display: flex; gap: 10px; }
        .col { flex: 1; }
    </style>
</head>
<body>
    <h1>M3U8 & MP4 相互変換ツール (Render版)</h1>

    <div class="card">
        <h2>1. MP4 ➔ M3U8 (HLS) 変換</h2>
        <form action="/to_m3u8" method="post" enctype="multipart/form-data">
            <label>MP4ファイルを選択:</label>
            <input type="file" name="file" accept="video/mp4" required>
            <button type="submit">変換してZIPでダウンロード</button>
        </form>
    </div>

    <div class="card">
        <h2>2. M3U8 (URL) ➔ MP4 変換 (アクセス制限・偽装対策付き)</h2>
        <form action="/to_mp4_url" method="post">
            <label>M3U8のURL:</label>
            <input type="text" name="m3u8_url" placeholder="https://example.com/playlist.m3u8" required>
            
            <div class="row">
                <div class="col">
                    <label>User-Agent (偽装用):</label>
                    <input type="text" name="user_agent" placeholder="Mozilla/5.0 (Windows NT 10.0; ...)">
                </div>
                <div class="col">
                    <label>Referer (偽装用):</label>
                    <input type="text" name="referer" placeholder="https://example.com/">
                </div>
            </div>
            
            <label>Cookie (必要な場合):</label>
            <input type="text" name="cookie" placeholder="session_id=xxxxx">
            
            <button type="submit">URLからMP4に変換してダウンロード</button>
        </form>
    </div>

    <div class="card">
        <h2>3. ローカルの M3U8 セット (ZIP) ➔ MP4 変換</h2>
        <form action="/to_mp4_local" method="post" enctype="multipart/form-data">
            <label>M3U8ファイルとTS片をまとめたZIPファイルを選択:</label>
            <input type="file" name="zip_file" accept=".zip" required>
            <button type="submit">ZIPからMP4に変換してダウンロード</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/to_m3u8', methods=['POST'])
def handle_to_m3u8():
    if 'file' not in request.files:
        return "ファイルがありません", 400
    file = request.files['file']
    if file.filename == '':
        return "ファイルが選択されていません", 400

    input_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(input_path)
    
    base_name = os.path.splitext(file.filename)[0]
    out_dir = os.path.join(OUTPUT_FOLDER, base_name)
    os.makedirs(out_dir, exist_ok=True)
    
    output_m3u8 = os.path.join(out_dir, f"{base_name}.m3u8")
    segment_pattern = os.path.join(out_dir, f"{base_name}_%03d.ts")

    cmd = [
        "ffmpeg", "-i", input_path,
        "-c:v", "libx264", "-c:a", "aac",
        "-hls_time", "10", "-hls_list_size", "0",
        "-hls_segment_filename", segment_pattern,
        output_m3u8
    ]

    try:
        subprocess.run(cmd, check=True)
        zip_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_hls.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(out_dir):
                for f in files:
                    zipf.write(os.path.join(root, f), f)
        return send_file(zip_path, as_attachment=True)
    except subprocess.CalledProcessError as e:
        return f"変換エラー: {e}", 500

@app.route('/to_mp4_url', methods=['POST'])
def handle_to_mp4_url():
    m3u8_url = request.form.get('m3u8_url')
    user_agent = request.form.get('user_agent')
    referer = request.form.get('referer')
    cookie = request.form.get('cookie')

    if not m3u8_url:
        return "URLが入力されていません", 400

    output_mp4 = os.path.join(OUTPUT_FOLDER, "output_from_url.mp4")
    cmd = ["ffmpeg"]

    headers = []
    if referer:
        headers.append(f"Referer: {referer}")
    if cookie:
        headers.append(f"Cookie: {cookie}")
    
    if user_agent:
        cmd.extend(["-user_agent", user_agent])
    
    if headers:
        cmd.extend(["-headers", "\r\n".join(headers) + "\r\n"])

    cmd.extend([
        "-i", m3u8_url,
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        output_mp4
    ])

    try:
        subprocess.run(cmd, check=True)
        return send_file(output_mp4, as_attachment=True)
    except subprocess.CalledProcessError as e:
        return f"変換エラー（アクセス制限やURLが無効です）: {e}", 500

@app.route('/to_mp4_local', methods=['POST'])
def handle_to_mp4_local():
    if 'zip_file' not in request.files:
        return "ZIPファイルがありません", 400
    file = request.files['zip_file']
    if file.filename == '':
        return "ファイルが選択されていません", 400

    zip_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(zip_path)

    extract_dir = os.path.join(UPLOAD_FOLDER, "extracted_" + os.path.splitext(file.filename)[0])
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)

    # 展開された中から .m3u8 ファイルを自動検出
    m3u8_file = None
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            if f.endswith('.m3u8'):
                m3u8_file = os.path.join(root, f)
                break
        if m3u8_file:
            break

    if not m3u8_file:
        return "エラー: 展開したZIPの中に .m3u8 ファイルが見つかりませんでした", 400

    output_mp4 = os.path.join(OUTPUT_FOLDER, "output_from_local.mp4")

    cmd = [
        "ffmpeg", "-i", m3u8_file,
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        output_mp4
    ]

    try:
        subprocess.run(cmd, check=True)
        return send_file(output_mp4, as_attachment=True)
    except subprocess.CalledProcessError as z_err:
        return f"変換エラー: {z_err}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
