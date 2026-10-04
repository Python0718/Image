import io
import os
import re
import subprocess
import tempfile
import threading
import uuid
import zipfile
from flask import Flask, jsonify, render_template, request, send_file
import imageio_ffmpeg
from PIL import Image, ImageSequence
import pillow_heif
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

pillow_heif.register_heif_opener()

app = Flask(__name__)

# タスク管理用ストレージ
TASKS = {}

RAW_EXTENSIONS = {
    ".dng",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".orf",
    ".rw2",
    ".pef",
    ".raf",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".mkv",
    ".m4v",
    ".wmv",
    ".flv",
}


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


def resize_image(
    img: Image.Image,
    target_width: int | None,
    target_height: int | None,
    maintain_aspect: bool,
) -> Image.Image:
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


def process_conversion_task(
    task_id, files_data, target_format, target_w, target_h, maintain_aspect
):
  task = TASKS[task_id]
  ffmpeg_exe = get_ffmpeg_path()
  converted_files = {}
  errors = []

  total_files = len(files_data)

  for idx, file_info in enumerate(files_data):
    filename = file_info["filename"]
    contents = file_info["contents"]
    orig_name, orig_ext = os.path.splitext(filename)
    orig_ext = orig_ext.lower()

    base_progress = int((idx / total_files) * 100)
    next_base_progress = int(((idx + 1) / total_files) * 100)
    task["message"] = f"変換中 ({idx + 1}/{total_files}): {filename}"
    task["progress"] = base_progress

    try:
      # === A. 動画ファイルの処理 (FFmpeg超高速処理) ===
      if orig_ext in VIDEO_EXTENSIONS or target_format in (
          "MP4",
          "WEBM",
          "MOV",
          "AVI",
          "M3U8",
      ):
        with tempfile.TemporaryDirectory() as tmpdir:
          input_path = os.path.join(tmpdir, f"input{orig_ext}")
          with open(input_path, "wb") as f:
            f.write(contents)

          # --- M3U8 (HLS) 変換 ---
          if target_format == "M3U8":
            output_m3u8 = os.path.join(tmpdir, "output.m3u8")
            cmd = [
                ffmpeg_exe,
                "-y",
                "-i",
                input_path,
                "-preset",
                "ultrafast",
            ]  # 超高速プリセット

            if target_w or target_h:
              w = target_w if target_w else -2
              h = target_h if target_h else -2
              vf = (
                  f"scale=trunc({w}/2)*2:trunc({h}/2)*2"
                  if target_w and target_h
                  else (f"scale={w}:-2" if target_w else f"scale=-2:{h}")
              )
              cmd.extend(["-vf", vf])

            cmd.extend([
                "-codec:v",
                "libx264",
                "-codec:a",
                "aac",
                "-hls_time",
                "4",
                "-hls_playlist_type",
                "vod",
                output_m3u8,
            ])

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )

            duration = None
            for line in process.stderr:
              if not duration:
                dur_match = re.search(
                    r"Duration:\s*(\d+:\d+:\d+\.\d+)", line
                )
                if dur_match:
                  duration = parse_time_to_seconds(dur_match.group(1))

              time_match = re.search(r"time=\s*(\d+:\d+:\d+\.\d+)", line)
              if time_match and duration and duration > 0:
                cur_time = parse_time_to_seconds(time_match.group(1))
                if cur_time:
                  sub_prog = cur_time / duration
                  task["progress"] = min(
                      99,
                      int(
                          base_progress
                          + sub_prog * (next_base_progress - base_progress)
                      ),
                  )

            process.wait()

            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, "w", zipfile.ZIP_DEFLATED) as zipf:
              for root, _, filenames in os.walk(tmpdir):
                for fn in filenames:
                  if fn == f"input{orig_ext}":
                    continue
                  file_path = os.path.join(root, fn)
                  arcname = (
                      f"{orig_name}_{fn}"
                      if fn != "output.m3u8"
                      else f"{orig_name}.m3u8"
                  )
                  zipf.write(file_path, arcname)

            zip_filename = f"{orig_name}_m3u8.zip"
            converted_files[zip_filename] = zip_io.getvalue()

          # --- 通常の動画変換 (MP4, MOV, WEBM 等) ---
          else:
            ext = f".{target_format.lower()}"
            output_video = os.path.join(tmpdir, f"output{ext}")

            cmd = [
                ffmpeg_exe,
                "-y",
                "-i",
                input_path,
                "-preset",
                "ultrafast",
            ]  # 超高速プリセット

            if target_w or target_h:
              if target_w and target_h:
                vf = f"scale={target_w}:{target_h}"
              elif target_w:
                vf = f"scale={target_w}:-2"
              else:
                vf = f"scale=-2:{target_h}"
              cmd.extend(["-vf", vf])

            if target_format == "MP4":
              cmd.extend(
                  ["-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p"]
              )
            elif target_format == "WEBM":
              cmd.extend([
                  "-c:v",
                  "libvpx",
                  "-speed",
                  "8",
                  "-crf",
                  "30",
                  "-c:a",
                  "libopus",
              ])
            elif target_format == "MOV":
              cmd.extend(["-c:v", "libx264", "-c:a", "aac"])

            cmd.append(output_video)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )

            duration = None
            for line in process.stderr:
              if not duration:
                dur_match = re.search(
                    r"Duration:\s*(\d+:\d+:\d+\.\d+)", line
                )
                if dur_match:
                  duration = parse_time_to_seconds(dur_match.group(1))

              time_match = re.search(r"time=\s*(\d+:\d+:\d+\.\d+)", line)
              if time_match and duration and duration > 0:
                cur_time = parse_time_to_seconds(time_match.group(1))
                if cur_time:
                  sub_prog = cur_time / duration
                  task["progress"] = min(
                      99,
                      int(
                          base_progress
                          + sub_prog * (next_base_progress - base_progress)
                      ),
                  )

            process.wait()

            with open(output_video, "rb") as vf:
              new_filename = orig_name + ext
              converted_files[new_filename] = vf.read()

      # === B. 画像ファイルの処理 ===
      else:
        ext = f".{target_format.lower()}"
        new_filename = orig_name + ext

        if orig_ext == ".svg":
          svg_io = io.BytesIO(contents)
          drawing = svg2rlg(svg_io)
          png_io = io.BytesIO()
          renderPM.drawToFile(drawing, png_io, fmt="PNG")
          png_io.seek(0)
          img = Image.open(png_io)
        elif orig_ext in RAW_EXTENSIONS:
          try:
            img = Image.open(io.BytesIO(contents))
          except Exception:
            jpeg_start = contents.find(b"\xff\xd8")
            jpeg_end = contents.rfind(b"\xff\xd9")
            if jpeg_start != -1 and jpeg_end != -1 and jpeg_end > jpeg_start:
              img = Image.open(io.BytesIO(contents[jpeg_start : jpeg_end + 2]))
            else:
              raise ValueError("RAWデータから画像を取得できませんでした")
        else:
          img = Image.open(io.BytesIO(contents))

        if hasattr(img, "n_frames") and img.n_frames > 1:
          resized_frames = []
          for frame in ImageSequence.Iterator(img):
            f = frame.copy()
            f = resize_image(f, target_w, target_h, maintain_aspect)
            resized_frames.append(f)
          img = resized_frames[0]
        else:
          img = resize_image(img, target_w, target_h, maintain_aspect)

        img_io = io.BytesIO()
        if target_format == "GIF":
          if "resized_frames" in locals() and len(resized_frames) > 1:
            resized_frames[0].save(
                img_io,
                format="GIF",
                save_all=True,
                append_images=resized_frames[1:],
                loop=0,
            )
          else:
            img.save(img_io, format="GIF")
        elif target_format in ("HEIC", "HEIF"):
          heif_file = pillow_heif.from_pillow(img)
          heif_file.save(img_io, quality=90)
        elif target_format == "AVIF":
          img.save(img_io, format="AVIF", quality=80)
        elif target_format == "ICO":
          if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
          img.save(
              img_io,
              format="ICO",
              sizes=[(256, 256), (64, 64), (32, 32), (16, 16)],
          )
        elif target_format == "JPEG":
          if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
              img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
              background.paste(img, mask=img.split()[3])
            img = background
          else:
            img = img.convert("RGB")
          img.save(img_io, "JPEG", quality=95)
        else:
          img.save(img_io, target_format)

        converted_files[new_filename] = img_io.getvalue()
        task["progress"] = next_base_progress

    except Exception as e:
      print(f"Error processing {filename}: {e}")
      errors.append(f"{filename}: {str(e)}")

  task["status"] = "completed"
  task["progress"] = 100
  task["message"] = "変換が完了しました！"
  task["files"] = converted_files
  task["errors"] = errors


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

  target_w = (
      int(width_str) if width_str and width_str.strip().isdigit() else None
  )
  target_h = (
      int(height_str) if height_str and height_str.strip().isdigit() else None
  )
  maintain_aspect = maintain_aspect_str.lower() == "true"

  files = request.files.getlist("files")
  files_data = []

  for file in files:
    if file.filename:
      files_data.append({"filename": file.filename, "contents": file.read()})

  if not files_data:
    return jsonify({"error": "ファイルが選択されていません"}), 400

  TASKS[task_id] = {
      "status": "processing",
      "progress": 0,
      "message": "変換準備中...",
      "files": {},
      "errors": [],
  }

  thread = threading.Thread(
      target=process_conversion_task,
      args=(
          task_id,
          files_data,
          target_format,
          target_w,
          target_h,
          maintain_aspect,
      ),
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
      "files": list(task["files"].keys()),
      "errors": task["errors"],
  })


@app.route("/download/<task_id>/<filename>", methods=["GET"])
def download_file(task_id: str, filename: str):
  if task_id not in TASKS or filename not in TASKS[task_id]["files"]:
    return "File not found", 404

  file_data = TASKS[task_id]["files"][filename]
  ext = os.path.splitext(filename)[1].lower()

  media_types = {
      ".svg": "image/svg+xml",
      ".gif": "image/gif",
      ".heic": "image/heic",
      ".heif": "image/heif",
      ".avif": "image/avif",
      ".mp4": "video/mp4",
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
