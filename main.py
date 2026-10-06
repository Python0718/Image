import io
import os
import cairosvg
from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageOps
import pillow_heif
import rawpy

pillow_heif.register_heif_opener()

app = Flask(__name__)

RAW_EXTENSIONS = {
    "cr2",
    "cr3",
    "nef",
    "arw",
    "dng",
    "orf",
    "rw2",
    "pef",
    "raf",
}


def process_image(
    file_bytes: bytes, filename: str, target_format: str, quality: int
) -> tuple[bytes, str]:
  ext = filename.split(".")[-1].lower()
  target_format = target_format.upper()

  # 1. 読み込み
  if ext == "svg":
    png_bytes = cairosvg.svg2png(bytestring=file_bytes)
    img = Image.open(io.BytesIO(png_bytes))
  elif ext in RAW_EXTENSIONS:
    with rawpy.imread(io.BytesIO(file_bytes)) as raw:
      rgb = raw.postprocess(
          use_camera_wb=True, half_size=False, no_auto_bright=True
      )
      img = Image.fromarray(rgb)
  else:
    img = Image.open(io.BytesIO(file_bytes))
    img = ImageOps.exif_transpose(img)

  # 2. カラーモード調整（JPEG変換時のアルファチャンネル処理など）
  if target_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
    background = Image.new("RGB", img.size, (255, 255, 255))
    if img.mode == "RGBA":
      background.paste(img, mask=img.split()[-1])
    else:
      background.paste(img.convert("RGBA"))
    img = background
  elif img.mode not in ("RGB", "RGBA") and target_format not in [
      "PNG",
      "GIF",
      "WEBP",
  ]:
    img = img.convert("RGB")

  # 3. 書き出し
  output_buffer = io.BytesIO()
  if target_format in ["HEIC", "HEIF", "AVIF"]:
    heif_file = pillow_heif.from_pillow(img)
    heif_file.save(output_buffer, format=target_format)
    mimetype = f"image/{target_format.lower()}"
  else:
    save_kwargs = {}
    if target_format in ["JPEG", "WEBP"]:
      save_kwargs["quality"] = quality
      mimetype = f"image/{'jpeg' if target_format == 'JPEG' else 'webp'}"
    elif target_format == "PNG":
      save_kwargs["optimize"] = True
      mimetype = "image/png"
    elif target_format == "GIF":
      mimetype = "image/gif"
    else:
      mimetype = "application/octet-stream"

    img.save(output_buffer, format=target_format, **save_kwargs)

  return output_buffer.getvalue(), mimetype


# --- UptimeRobot用のヘルスチェックエンドポイント ---
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health_check():
  return jsonify({"status": "ok", "message": "Image Converter is running"}), 200


# --- 画像変換エンドポイント ---
@app.route("/convert", methods=["POST"])
def convert():
  if "file" not in request.files:
    return jsonify({"error": "ファイルが添付されていません"}), 400

  file = request.files["file"]
  target_format = request.form.get("target_format", "JPEG")
  quality = int(request.form.get("quality", 90))

  if file.filename == "":
    return jsonify({"error": "ファイル名が空です"}), 400

  try:
    file_bytes = file.read()
    output_bytes, mimetype = process_image(
        file_bytes, file.filename, target_format, quality
    )

    out_ext = "jpg" if target_format.upper() == "JPEG" else target_format.lower()
    base_name = os.path.splitext(file.filename)[0]
    out_filename = f"{base_name}_converted.{out_ext}"

    return send_file(
        io.BytesIO(output_bytes),
        mimetype=mimetype,
        as_attachment=True,
        download_name=out_filename,
    )
  except Exception as e:
    return jsonify({"error": f"画像変換エラー: {str(e)}"}), 400


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
