FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-host.txt ./
RUN pip install -r requirements-host.txt
COPY musicbot ./musicbot
# توکن و کلیدها هرگز داخل ایمیج نیستند؛ از متغیرهای محیطی میزبان می‌آیند.
CMD ["python", "-m", "musicbot"]
