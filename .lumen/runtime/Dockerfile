FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
RUN python -m compileall -q . && python -c "import worker" && python -c "import mp_main" && python -c "import alert_main"
ENV PYTHONUNBUFFERED=1
CMD ["sh","-c","uvicorn public_entry:app --host 0.0.0.0 --port ${PORT:-8000}"]
