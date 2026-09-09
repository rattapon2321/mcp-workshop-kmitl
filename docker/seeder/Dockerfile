# Seeder: a one-shot container that populates all three databases.
# Deliberately small - it only needs database drivers and an HTTP client.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY scenarios/ ./scenarios/

# Unbuffered so progress is visible while `make up` runs.
ENV PYTHONUNBUFFERED=1

CMD ["python", "seed.py"]
