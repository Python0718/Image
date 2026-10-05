import io
import os
import re
import subprocess
import tempfile
import threading
import uuid
import zipfile
import traceback
import urllib.parse
import urllib.request
from flask import Flask, jsonify, render_template, request, send_file
import imageio_ffmpeg
from PIL import Image, ImageSequence
import pillow_heif
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

pillow_heif.register_heif_opener()

app = Flask(__name__)

TASKS = {}

RAW_EXTENSIONS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".pef", ".raf"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".wmv", ".flv", ".ts", ".m3u8"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic", ".heif", ".ico", ".svg"}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_ffmpeg_path():
    return imageio_ffmpeg.get_ffmpeg_exe()

def parse_time_to_seconds(time_str):
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception:
        pass
    return None

def resolve_m3u8_url(m3u8_url):
    """マスタープレイリストの場合、最高画質のサブプレイリストURLを自動抽出する"""
    try:
        req = urllib.request.Request(m3u8_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as response:
            content = response.read().decode("utf-8", errors="ignore")

        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            best_bandwidth = -1
            best_url = None

            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF"):
                    bw_match = re.search(r"BANDWIDTH=(\d+)", line)
                    bw = int(bw_match.group(1)) if bw_match else 0
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if next_line and not next_line.startswith("#"):
                            if bw > best_bandwidth:
                                best_bandwidth = bw
                                best_url = urllib.parse.urljoin(m3u8_url, next_line)
            if best_url:
                return best_url
    except Exception as e:
        print(f"M3U8解析警告: {e}")
    return m3u8_url

def resize_image(img: Image.Image, target_width: int | None, target_height: int | None, maintain_aspect: bool) -> Image.Image:
    if not target_width and not target_height:
        return img
    orig_w, orig_h = img.size
    if maintain_aspect:
        if target_width and target_height:
            img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
            return img
        elif target_width:
            new_w = target_width
            new_h = int(orig_h * (target_width / orig_w))
        elif target_height:
            new_h = target_height
            new_w = int(orig_w * (target_height / orig_h))
    else:
        new_w = target_width if target_width else orig_w
        new_h = target_height if target_height else orig_h
    return img.resize((max(1, new_w), max(1, new_h)), Image.Resampling.LANCZOS)

def process_conversion_task(task_id, files_data, target_format, target_w, target_h, maintain_aspect):
    task = TASKS.get(task_id)
    if not task:
        return

    try:
        ffmpeg_exe = get_ffmpeg_path()
        converted_files = {}
        errors = []

        task["message"] = "ファイルを準備中..."
        task["progress"] = 5

        # 1. URL指定の処理 (M3U8 → TS / MP4 等の抽出)
        url_file = next((f for f in files_data if "url" in f), None)
        if url_file:
            with tempfile.TemporaryDirectory() as tmpdir:
                input_path = resolve_m3u8_url(url_file["url"])
                ext = f".{target_format.lower()}"
                output_video = os.path.join(tmpdir, f"output{ext}")

                cmd = [ffmpeg_exe, "-y", "-user_agent", USER_AGENT, "-i", input_path]
                
                # TSフォーマット抽出の場合は無劣化コピー
                if target_format == "TS":
                    cmd.extend(["-c", "copy"])
                elif target_format == "MP4":
                    cmd.extend(["-preset", "ultrafast", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p"])
                else:
                    cmd.extend(["-preset", "ultrafast"])

                cmd.append(output_video)

                process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8", errors="replace")
                process.wait()

                if process.returncode != 0:
                    raise RuntimeError("URLからのTS/動画抽出処理に失敗しました。")

                with open(output_video, "rb") as vf:
                    converted_files[f"extracted_video{ext}"] = vf.read()

            task["status"] = "completed"
            task["progress"] = 100
            task["message"] = "抽出・変換が完了しました！"
            task["files"] = converted_files
            return

        # 2. ローカルファイルの処理
        with tempfile.TemporaryDirectory() as tmpdir:
            has_m3u8 = False
            m3u8_file_path = None

            for file_info in files_data:
                filename = file_info["filename"]
                save_path = os.path.join(tmpdir, filename)

                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(file_info["contents"])

                if filename.lower().endswith(".zip"):
                    with zipfile.ZipFile(save_path, 'r') as zip_ref:
                        zip_ref.extractall(tmpdir)

            for root, _, filenames in os.walk(tmpdir):
                for fn in filenames:
                    if fn.lower().endswith(".m3u8"):
                        has_m3u8 = True
                        m3u8_file_path = os.path.join(root, fn)
                        break
                if has_m3u8:
                    break

            # M3U8からTSやMP4への結合・抽出
            if has_m3u8 and target_format in ("MP4", "WEBM", "MOV", "AVI", "TS"):
                task["message"] = "M3U8からTS/動画ファイルを抽出・結合中..."
                ext = f".{target_format.lower()}"
                out_name = os.path.splitext(os.path.basename(m3u8_file_path))[0]
                output_video = os.path.join(tmpdir, f"output{ext}")

                cmd = [ffmpeg_exe, "-y", "-i", m3u8_file_path]

                if target_format == "TS":
                    cmd.extend(["-c", "copy"])
                else:
                    cmd.extend(["-preset", "ultrafast"])
                    if target_format == "MP4":
                        cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p"])

                cmd.append(output_video)

                process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, universal_newlines=True, encoding="utf-8", errors="replace")
                process.wait()

                if process.returncode != 0:
                    raise RuntimeError("TSファイルの抽出・結合に失敗しました。.tsセグメントファイルが不足している可能性があります。")

                with open(output_video, "rb") as vf:
                    converted_files[f"{out_name}{ext}"] = vf.read()

            else:
                for idx, file_info in enumerate(files_data):
                    filename = file_info["filename"]
                    if filename.lower().endswith(".zip"):
                        continue

                    orig_name, orig_ext = os.path.splitext(filename)
                    orig_ext = orig_ext.lower()
                    input_file = os.path.join(tmpdir, filename)

                    is_target_video = target_format in ("MP4", "WEBM", "MOV", "AVI", "M3U8", "TS")
                    is_source_video = orig_ext in VIDEO_EXTENSIONS

                    if is_target_video or is_source_video:
                        ext = f".{target_format.lower()}"
                        output_video = os.path.join(tmpdir, f"out_{orig_name}{ext}")

                        cmd = [ffmpeg_exe, "-y", "-i", input_file]
                        if target_format == "TS":
                            cmd.extend(["-c", "copy"])
                        else:
                            cmd.extend(["-preset", "ultrafast"])
                            if target_format == "MP4":
                                cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p"])

                        cmd.append(output_video)

                        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                        process.wait()

                        if process.returncode == 0:
                            with open(output_video, "rb") as vf:
                                converted_files[f"{orig_name}{ext}"] = vf.read()
                    else:
                        img = Image.open(input_file)
                        img = resize_image(img, target_w, target_h, maintain_aspect)
                        img_io = io.BytesIO()
                        if target_format == "JPEG":
                            img = img.convert("RGB")
                            img.save(img_io, "JPEG", quality=95)
                        else:
                            img.save(img_io, target_format)
                        converted_files[f"{orig_name}.{target_format.lower()}"] = img_io.getvalue()

        task["status"] = "completed"
        task["progress"] = 100
        task["message"] = "完了しました！"
        task["files"] = converted_files
        task["errors"] = errors

    except Exception as e:
        traceback.print_exc()
        task["status"] = "error"
        task["message"] = f"エラーが発生しました: {str(e)}"
        task["errors"] = [str(e)]


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/convert/", methods=["POST"])
def convert_files():
    target_format = request.form.get("target_format", "JPEG").upper()
    task_id = str(uuid.uuid4())

    width_str = request.form.get("width")
    height_str = request.form.get("height")
    maintain_aspect_str = request.form.get("maintain_aspect", "true")

    target_w = int(width_str) if width_str and width_str.strip().isdigit() else None
    target_h = int(height_str) if height_str and height_str.strip().isdigit() else None
    maintain_aspect = maintain_aspect_str.lower() == "true"

    files = request.files.getlist("files")
    video_url = request.form.get("video_url")
    
    files_data = []

    for file in files:
        if file.filename:
            files_data.append({"filename": file.filename, "contents": file.read()})

    if video_url and video_url.strip():
        url_str = video_url.strip()
        parsed = urllib.parse.urlparse(url_str)
        base_name = os.path.basename(parsed.path) or "downloaded_video"
        files_data.append({"filename": base_name, "url": url_str})

    if not files_data:
        return jsonify({"error": "ファイルまたはURLが指定されていません"}), 400

    TASKS[task_id] = {
        "status": "processing",
        "progress": 0,
        "message": "変換準備中...",
        "files": {},
        "errors": [],
    }

    thread = threading.Thread(
        target=process_conversion_task,
        args=(task_id, files_data, target_format, target_w, target_h, maintain_aspect)
    )
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/progress/<task_id>", methods=["GET"])
def get_progress(task_id: str):
    if task_id not in TASKS:
        return jsonify({"error": "タスクが見つかりません"}), 404

    task = TASKS[task_id]
    return jsonify({
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "files": list(task.get("files", {}).keys()),
        "errors": task.get("errors", []),
    })


@app.route("/download/<task_id>/<filename>", methods=["GET"])
def download_file(task_id: str, filename: str):
    if task_id not in TASKS or filename not in TASKS[task_id]["files"]:
        return "File not found", 404

    file_data = TASKS[task_id]["files"][filename]
    ext = os.path.splitext(filename)[1].lower()

    media_types = {
        ".mp4": "video/mp4",
        ".ts": "video/mp2t",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".zip": "application/zip",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return send_file(
        io.BytesIO(file_data),
        mimetype=media_type,
        as_attachment=True,
        download_name=filename,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
