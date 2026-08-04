FROM python:3.11-slim

# ffmpeg is needed to extract audio from any video/audio container (including webm)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py identify_speaker.py .
COPY voxlib/ voxlib/

# HuggingFace model cache is placed in a volume so models aren't
# re-downloaded every time the container is recreated. Output documents
# live under the project's own bind mount (/workspace), not a separate volume.
VOLUME ["/root/.cache/huggingface"]

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
