# hiru-assemble: ffmpeg on Cloud Run (a SERVICE: it needs ffmpeg in the image).
FROM python:3.12-slim

# ffmpeg from Debian: the last-frame grab and ffprobe are all this service uses.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV PORT=8080
CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1
