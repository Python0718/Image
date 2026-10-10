import os
import zipfile
import subprocess
from flask import Flask, render_template_string, request, send_file, redirect, url_for

app = Flask(__name__)
UPLOAD_FOLDER = '/tmp/uploads'
OUTPUT_FOLDER = '/tmp/outputs'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 簡易的なHTMLテンプレート
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>M3U8 / MP4 Converter</title>
    <style>
        body { font-family-sans-serif; margin: 40px; background: #f9f9f9; color: #333; }
        .card { background: white; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        input, button { margin: 10px 0; padding: 8px; }
        button { background: #0070f3; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0051a2; }
    </style>
</head>
<body>
    <h1>M3U8 & MP4 相互変換ツール (Render版)</h1>

    <div class="card">
        <h2>1. MP4 ➔ M3U8 (HLS) 変換</h2>
        <form action="/to_m3u8" method="post" enctype="multipart/form-data">
            <input type="file" name="file" accept="video/mp4" required><br>
            <button type="submit">変換してZIPでダウンロード</button>
        </form>
    </div>

    <div class="card">
        <h2>2. M3U8 (URL) ➔ MP4 変換</h2>
        <form action="/to_mp4" method="post">
            <input type="text" name="m3u8_url" placeholder="https://example.com/playlist.m3u8" style="width: 80%;" required><br>
            <button type="submit">MP4に変換してダウンロード</button>
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
        
        # 出力されたファイル群をZIPに固める
        zip_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_hls.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(out_dir):
                for f in files:
                    zipf.write(os.path.join(root, f), f)
                    
        return send_file(zip_path, as_attachment=True)
    except subprocess.CalledProcessError as e:
        return f"変換エラー: {e}", 500

@app.route('/to_mp4', methods=['POST'])
def handle_to_mp4():
    m3u8_url = request.form.get('m3u8_url')
    if not m3u8_url:
        return "URLが入力されていません", 400

    output_mp4 = os.path.join(OUTPUT_FOLDER, "output.mp4")

    cmd = [
        "ffmpeg", "-i", m3u8_url,
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        output_mp4
    ]

    try:
        subprocess.run(cmd, check=True)
        return send_file(output_mp4, as_attachment=True)
    except subprocess.CalledProcessError as e:
        return f"変換エラー（URLが無効かアクセス制限があります）: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
