import io
import os
import zipfile
import cairosvg
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.requests import Request

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
  template = templates.get_template("index.html")
  html_content = template.render({"request": request})
  return HTMLResponse(content=html_content)


@app.post("/convert/")
async def convert_images(
    files: list[UploadFile] = File(...), target_format: str = Form(...)
):
  target_format = target_format.upper()
  zip_io = io.BytesIO()

  with zipfile.ZipFile(
      zip_io, mode="w", compression=zipfile.ZIP_DEFLATED
  ) as zip_file:
    for file in files:
      contents = await file.read()
      orig_name, orig_ext = os.path.splitext(file.filename)
      orig_ext = orig_ext.lower()
      ext = f".{target_format.lower()}"

      try:
        # SVG形式の場合はcairosvgを使って一度PNG（バイトデータ）に変換してからPillowで処理する
        if orig_ext == ".svg":
          png_data = cairosvg.svg2png(bytestring=contents)
          img = Image.open(io.BytesIO(png_data))
        else:
          img = Image.open(io.BytesIO(contents))

        with img:
          # JPEG変換時のアルファチャンネル（透明度）対策
          if target_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
              img = img.convert("RGBA")
            background.paste(img, mask=img.split()[3])
            img = background
          elif target_format != "JPEG" and img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

          img_io = io.BytesIO()

          # 保存処理（ICO形式や各フォーマットの指定）
          if target_format == "ICO":
            # ICO形式の場合はマルチサイズ対応として一般的なサイズにリサイズまたはそのまま保存
            img.save(img_io, format="ICO", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
          elif target_format == "JPEG":
            img.save(img_io, "JPEG", quality=95)
          else:
            img.save(img_io, target_format)

          img_io.seek(0)
          zip_file.writestr(orig_name + ext, img_io.read())

      except Exception as e:
        print(f"Error processing {file.filename}: {e}")

  zip_io.seek(0)
  return StreamingResponse(
      zip_io,
      media_type="application/x-zip-compressed",
      headers={
          "Content-Disposition": "attachment; filename=converted_images.zip"
      },
  )
