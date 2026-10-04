import io
import os
import uuid
import base64
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image
from reportlab.graphics import renderPM
from starlette.requests import Request
from svglib.svglib import svg2rlg

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

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
    orig_name, orig_ext = os.path.splitext(file.filename)
    orig_ext = orig_ext.lower()
    ext = f".{target_format.lower()}"
    new_filename = orig_name + ext

    try:
      # SVG出力が選ばれた場合、または入力がSVGの場合の処理
      if target_format == "SVG":
        # 入力が何であれ一度PNGのバイトデータにしてからBase64埋め込みSVGにする
        if orig_ext == ".svg":
          svg_io = io.BytesIO(contents)
          drawing = svg2rlg(svg_io)
          temp_png = io.BytesIO()
          renderPM.drawToFile(drawing, temp_png, fmt="PNG")
          img_bytes = temp_png.getvalue()
          # サイズ取得用
          img = Image.open(io.BytesIO(img_bytes))
        else:
          img = Image.open(io.BytesIO(contents))
          temp_png = io.BytesIO()
          img.save(temp_png, format="PNG")
          img_bytes = temp_png.getvalue()

        width, height = img.size
        b64_data = base64.b64encode(img_bytes).decode("utf-8")
        svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
    <image href="data:image/png;base64,{b64_data}" width="{width}" height="{height}"/>
</svg>'''
        converted_files[new_filename] = svg_content.encode("utf-8")
        continue

      # 通常のラスター変換（JPEG, PNG, WEBP, ICOなど）
      if orig_ext == ".svg":
        svg_io = io.BytesIO(contents)
        drawing = svg2rlg(svg_io)
        png_io = io.BytesIO()
        renderPM.drawToFile(drawing, png_io, fmt="PNG")
        png_io.seek(0)
        img = Image.open(png_io)
      else:
        img = Image.open(io.BytesIO(contents))

      with img:
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
  media_type = (
      "image/svg+xml" if filename.lower().endswith(".svg") else "application/octet-stream"
  )
  return StreamingResponse(
      io.BytesIO(file_data),
      media_type=media_type,
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
  )
