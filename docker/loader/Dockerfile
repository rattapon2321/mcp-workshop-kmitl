# Log loader: parses raw device logs and indexes them into OpenSearch.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

ENV PYTHONUNBUFFERED=1

CMD ["python", "load_logs.py"]
