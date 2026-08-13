FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY odrclone ./odrclone
RUN pip install --no-cache-dir .
RUN mkdir -p /config /cache /downloads /app/data
ENV ODRCLONE_CONFIG=/config/config.yml
EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/api/health', timeout=3)"
CMD ["od-rclone"]
