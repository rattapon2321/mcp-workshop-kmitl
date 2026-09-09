# Reference demo app: the completed agent API and Chainlit UI in one image.
#
# Built from the same source the participants extend, so the demo can never
# drift from the reference implementation.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "openai>=1.40" "httpx>=0.27" "mcp>=1.2" \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "sse-starlette>=2.1" \
    "pydantic>=2.8" "pydantic-settings>=2.4" "chainlit>=1.3" \
    "psycopg[binary]>=3.2" "pgvector>=0.3" "neo4j>=5.24" "opensearch-py>=2.7" \
    "pyyaml>=6.0" "python-dotenv>=1.0" "honcho>=2.0"

COPY apps/ ./apps/
COPY data/questions/ ./data/questions/
COPY data/mock_fs/ ./data/mock_fs/
COPY scripts/ ./scripts/
COPY docker/demo/Procfile docker/demo/entrypoint.sh ./

RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/agent-api:/app/apps/mcp-server \
    READ_ONLY=true

EXPOSE 8000 8080

ENTRYPOINT ["./entrypoint.sh"]
