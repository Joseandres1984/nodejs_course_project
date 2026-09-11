FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY .lumen/bundle.part01 /tmp/bundle.part01
COPY .lumen/bundle.part02a /tmp/bundle.part02a
COPY .lumen/bundle.part02b /tmp/bundle.part02b
COPY .lumen/bundle.part02c /tmp/bundle.part02c

RUN cat /tmp/bundle.part01 /tmp/bundle.part02a /tmp/bundle.part02b /tmp/bundle.part02c > /tmp/lumen.b64 \
    && python -c "import base64, zipfile, pathlib; raw=pathlib.Path('/tmp/lumen.b64').read_bytes(); pathlib.Path('/tmp/lumen.zip').write_bytes(base64.b64decode(raw)); zipfile.ZipFile('/tmp/lumen.zip').extractall('/app')"

WORKDIR /app/lumen-prod
RUN pip install --no-cache-dir .

CMD ["sh", "-c", "uvicorn lumen.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
