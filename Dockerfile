# F88tball — backend (Python + FastAPI + ffmpeg for video assembly)
FROM python:3.12-slim

# System deps: ffmpeg for MoviePy, libGL/glib for Pillow/opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Fast dependency management with uv
RUN pip install --no-cache-dir uv

# Install deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# App source
COPY . .

EXPOSE 5001

CMD ["uv", "run", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "5001"]
