import base64
import io
import os
import uuid
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageSequence
import pillow_heif

# RAW画像を純Pythonで読み込むライブラリ
import rawread
from reportlab.graphics import renderPM
from starlette.requests import Request
from svglib.svglib import svg2rlg

# HEIF / HEIC / AVIF のプラグイン登録
pillow_heif.register_heif_opener()
pillow_heif.register_avif_opener()

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

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


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
  template = templates.get_template("index.html")
  html_content = template.render({"request": request})
  return HTMLResponse(content=html_content)


@app.post("/convert/", response_class=HTMLResponse)
async def convert_images(
    request: Request,
    files: list[UploadFile] = File(...),
    target_format: str = Form(...),
):
  target_format = target_format.upper()
  session_id = str(uuid.uuid4())
  converted_files = {}

  for file in files:
    contents = await file.read()
    orig_name, orig_ext = os.path.splitext(file.filename)
    orig_ext = orig_ext.lower()
    ext = f".{target_format.lower()}"
    new_filename = orig_name + ext

    try:
      img = None

      # 入力ファイルの読み込み（SVG / RAW / 通常画像・HEIC）
      if orig_ext == ".svg":
        svg_io = io.BytesIO(contents)
        drawing = svg2rlg(svg_io)
        png_io = io.BytesIO()
        renderPM.drawToFile(drawing, png_io, fmt="PNG")
        png_io.seek(0)
        img = Image.open(png_io)

      elif orig_ext in RAW_EXTENSIONS:
        # rawreadを使用したRAWデータの安全な抽出・読み込み
        try:
          raw_data = rawread.read(io.BytesIO(contents))
          img = Image.fromarray(raw_data)
        except Exception:
          # 万が一RAWのピクセル展開に失敗した場合は内蔵サムネイル/プレビューを抽出
          img = Image.open(io.BytesIO(contents))

      else:
        img = Image.open(io.BytesIO(contents))

      # 出力フォーマット別の保存処理
      if target_format == "SVG":
        temp_png = io.BytesIO()
        if hasattr(img, "n_frames") and img.n_frames > 1:
          img.seek(0)
        img.save(temp_png, format="PNG")
        img_bytes = temp_png.getvalue()
        width, height = img.size
        b64_data = base64.b64encode(img_bytes).decode("utf-8")
        svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <image href="data:image/png;base64,{b64_data}" width="{width}" height="{height}"/>
</svg>'''
        converted_files[new_filename] = svg_content.encode("utf-8")
        continue

      img_io = io.BytesIO()

      if target_format == "GIF":
        if hasattr(img, "n_frames") and img.n_frames > 1:
          frames = [frame.copy() for frame in ImageSequence.Iterator(img)]
          frames[0].save(
              img_io,
              format="GIF",
              save_all=True,
              append_images=frames[1:],
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

  template = templates.get_template("index.html")
  html_content = template.render({
      "request": request,
      "session_id": session_id,
      "files": list(converted_files.keys()),
  })
  return HTMLResponse(content=html_content)


@app.get("/download/{session_id}/{filename}")
def download_file(session_id: str, filename: str):
  if (
      session_id not in CONVERTED_STORAGE
      or filename not in CONVERTED_STORAGE[session_id]
  ):
    raise HTTPException(status_code=404, detail="File not found")

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

  return StreamingResponse(
      io.BytesIO(file_data),
      media_type=media_type,
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
  )
