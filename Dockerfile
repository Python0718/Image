FROM python:3.10-slim

# FFmpegのインストール
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係のインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードのコピー
COPY . .

# Renderのデフォルトポート
EXPOSE 10000

# Gunicornで起動（タイムアウトを10分に設定）
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app", "--timeout", "600"]
