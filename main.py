import base64
import io
import os
import uuid
from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image, ImageSequence
import pillow_heif
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

# HEIF / HEIC プラグイン登録
pillow_heif.register_heif_opener()

app = Flask(__name__)

CONVERTED_STORAGE = {}

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

  new_w = max(1, new_w)
  new_h = max(1, new_h)

  return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


@app.route("/", methods=["GET"])
def index():
  return render_template("index.html")


@app.route("/convert/", methods=["POST"])
def convert_images():
  target_format = request.form.get("target_format", "JPEG").upper()
  session_id = str(uuid.uuid4())
  converted_files = {}

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

  for file in files:
    if not file.filename:
      continue

    contents = file.read()
    orig_name, orig_ext = os.path.splitext(file.filename)
    orig_ext = orig_ext.lower()
    ext = f".{target_format.lower()}"
    new_filename = orig_name + ext

    try:
      img = None

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

      if target_format == "SVG":
        temp_png = io.BytesIO()
        img.save(temp_png, format="PNG")
        img_bytes = temp_png.getvalue()
        w, h = img.size
        b64_data = base64.b64encode(img_bytes).decode("utf-8")
        svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
    <image href="data:image/png;base64,{b64_data}" width="{w}" height="{h}"/>
</svg>'''
        converted_files[new_filename] = svg_content.encode("utf-8")
        continue

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

    except Exception as e:
      print(f"Error processing {file.filename}: {e}")

  CONVERTED_STORAGE[session_id] = converted_files

  return jsonify({"session_id": session_id, "files": list(converted_files.keys())})


@app.route("/download/<session_id>/<filename>", methods=["GET"])
def download_file(session_id: str, filename: str):
  if (
      session_id not in CONVERTED_STORAGE
      or filename not in CONVERTED_STORAGE[session_id]
  ):
    return "File not found", 404

  file_data = CONVERTED_STORAGE[session_id][filename]
  ext = os.path.splitext(filename)[1].lower()

  media_types = {
      ".svg": "image/svg+xml",
      ".gif": "image/gif",
      ".heic": "image/heic",
      ".heif": "image/heif",
      ".avif": "image/avif",
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
