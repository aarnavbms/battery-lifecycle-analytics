# Battery Lifecycle Analytics: website + REST API
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8050
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# build the API database from the shipped results, so the first request is fast
RUN python -m batterylife db

RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8050
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/api/v1/health')"
CMD ["python", "dashboard/app.py"]
