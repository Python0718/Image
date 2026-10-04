import io
import os
import zipfile
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.requests import Request

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/")
def index(request: Request):
  return templates.TemplateResponse("index.html", {"request": request})


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
      try:
        with Image.open(io.BytesIO(contents)) as img:
          # ファイル名と拡張子の調整
          orig_name, _ = os.path.splitext(file.filename)
          ext = f".{target_format.lower()}"

          # JPEG変換時のアルファチャンネル（透明度）対策
          if target_format == "JPEG" and img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
          elif target_format != "JPEG" and img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

          # メモリ上に変換後の画像を保存
          img_io = io.BytesIO()
          if target_format == "JPEG":
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
