import base64
import io
import os
from typing import Optional
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageSequence
import pillow_heif
from reportlab.graphics import renderPM
from starlette.requests import Request
from svglib.svglib import svg2rlg

# HEIF / HEIC プラグイン登録
pillow_heif.register_heif_opener()

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


def resize_image(
    img: Image.Image,
    target_width: Optional[int],
    target_height: Optional[int],
    maintain_aspect: bool,
) -> Image.Image:
  """画像をリサイズするヘルパー関数"""
  if not target_width and not target_height:
    return img

  orig_w, orig_h = img.size

  if maintain_aspect:
    if target_width and target_height:
      # 両方指定された場合は、枠内に収まるよう縦横比を維持して縮小/拡大
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

  # 1px未満にならないよう安全策
  new_w = max(1, new_w)
  new_h = max(1, new_h)

  return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
  template = templates.get_template("index.html")
  return HTMLResponse(content=template.render({"request": request}))


@app.post("/convert/")
async def convert_images(
    files: list[UploadFile] = File(...),
    target_format: str = Form(...),
    width: Optional[str] = Form(None),
    height: Optional[str] = Form(None),
    maintain_aspect: bool = Form(False),
):
  target_format = target_format.upper()
  session_id = str(uuid.uuid4())
  converted_files = {}

  # 数値への変換（空文字列や不正値の処理）
  target_w = int(width) if width and width.strip().isdigit() else None
  target_h = int(height) if height and height.strip().isdigit() else None

  for file in files:
    contents = await file.read()
    orig_name, orig_ext = os.path.splitext(file.filename)
    orig_ext = orig_ext.lower()
    ext = f".{target_format.lower()}"
    new_filename = orig_name + ext

    try:
      img = None

      # 1. 画像の読み込み
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

      # 2. リサイズ処理（多重フレーム対応）
      if hasattr(img, "n_frames") and img.n_frames > 1:
        resized_frames = []
        for frame in ImageSequence.Iterator(img):
          f = frame.copy()
          f = resize_image(f, target_w, target_h, maintain_aspect)
          resized_frames.append(f)
        # 代表フレームとして先頭を設定
        img = resized_frames[0]
      else:
        img = resize_image(img, target_w, target_h, maintain_aspect)

      # 3. 出力フォーマット別の保存処理
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

  return {"session_id": session_id, "files": list(converted_files.keys())}


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
