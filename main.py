import io
import os
import uuid
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.requests import Request

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# メモリ上で変換済みデータを一時保存する辞書（簡易ストレージ）
# 構造: { session_id: { filename: bytes } }
CONVERTED_STORAGE = {}


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
    orig_name, _ = os.path.splitext(file.filename)
    ext = f".{target_format.lower()}"
    new_filename = orig_name + ext

    try:
      with Image.open(io.BytesIO(contents)) as img:
        # 透過やカラーモードの調整
        if target_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
          background = Image.new("RGB", img.size, (255, 255, 255))
          if img.mode == "P":
            img = img.convert("RGBA")
          if img.mode in ("RGBA", "LA"):
            background.paste(img, mask=img.split()[3])
          img = background
        elif target_format != "JPEG" and img.mode not in ("RGB", "RGBA"):
          img = img.convert("RGB")

        img_io = io.BytesIO()
        if target_format == "ICO":
          img.save(
              img_io,
              format="ICO",
              sizes=[(256, 256), (64, 64), (32, 32), (16, 16)],
          )
        elif target_format == "JPEG":
          img.save(img_io, "JPEG", quality=95)
        elif target_format == "WEBP":
          img.save(img_io, "WEBP")
        else:
          img.save(img_io, "PNG")

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
  return StreamingResponse(
      io.BytesIO(file_data),
      media_type="application/octet-stream",
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
  )
