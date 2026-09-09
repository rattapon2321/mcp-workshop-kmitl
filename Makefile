# ============================================================
#  AI x IP-MPLS Workshop
#  Run `make help` to list all targets.
# ============================================================
COMPOSE := docker compose -f docker/docker-compose.yml --env-file .env
PY      := uv run

.DEFAULT_GOAL := help
.PHONY: help install up down reset verify seed reseed logs-tail \
        load-logs load-logs-watch api ui mcp demo demo-offline demo-record \
        demo-export test eval lint protocol-version \
        lab1-reset lab1-solution embed-tickets embed-devices vector-compare

help: ## List all available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------- Install ----------
install: ## Install all dependencies (requires uv)
	uv sync --all-extras

# ---------- Infrastructure ----------
up: ## Start all services and seed automatically
	$(COMPOSE) up -d postgres pgadmin neo4j opensearch opensearch-dashboards mailhog
	$(COMPOSE) up seeder
	@echo ""
	@echo "Stack is up  ->  verify with: make verify"

down: ## Stop services (data is kept)
	$(COMPOSE) down

reset: ## Remove everything including volumes (full reset)
	$(COMPOSE) down -v
	@echo "All data removed  ->  start again with: make up"

verify: ## Health-check all 3 databases and the LLM endpoint
	$(COMPOSE) run --rm seeder python verify.py

seed: ## Seed data (keeps existing rows)
	$(COMPOSE) run --rm seeder python seed.py

reseed: ## Purge and re-seed with fresh timestamps  << run on demo morning
	$(COMPOSE) run --rm seeder python seed.py --purge
	@echo "Data re-seeded. Run make demo-record if you use replay mode."

logs-tail: ## Tail logs from all containers
	$(COMPOSE) logs -f

# ---------- Log ingestion ----------
load-logs: ## Load logs from data/logs/incoming/ (optional FILE=... SHIFT=now)
	$(COMPOSE) run --rm loader python load_logs.py $(if $(FILE),--file $(FILE),) $(if $(SHIFT),--shift $(SHIFT),)

load-logs-watch: ## Watch incoming/ and auto-load new files
	$(COMPOSE) run --rm loader python watch.py

# ---------- Participant apps ----------
api: ## Run the Agent API (:8080)
	$(PY) uvicorn apps.agent-api.main:app --reload --port $${AGENT_API_PORT:-8080}

ui: ## Run the Chainlit UI (:8000)
	$(PY) chainlit run apps/chainlit-ui/app.py --port $${CHAINLIT_PORT:-8000} -w

mcp: ## Run the MCP server standalone (:9000)
	$(PY) python apps/mcp-server/server.py --transport streamable-http --port 9000

# ---------- Reference demo app ----------
demo: ## Start the reference demo app, live mode (:8100)
	$(COMPOSE) --profile demo up -d mcp-demo
	@echo "Open http://localhost:8100"

demo-offline: ## Start the demo app in replay mode (no LLM or network needed)
	DEMO_MODE=replay $(COMPOSE) --profile demo up -d mcp-demo
	@echo "Open http://localhost:8100 (replay mode)"

demo-record: ## Record fresh traces for replay mode  << run after every reseed
	$(PY) python apps/demo-app/record_traces.py

demo-export: ## Save the demo image to a .tar for offline machines
	docker save -o mcp-demo.tar ai-mpls-workshop-demo:latest
	@echo "Created mcp-demo.tar"

# ---------- Lab helpers ----------
lab1-reset: ## Remove vectors from Postgres AND Neo4j so Lab 1 can rebuild them
	docker exec -i mpls-postgres psql -U $${PG_USER:-mpls} -d $${PG_DATABASE:-mplsdb} < scripts/lab/lab1_reset_vector.sql
	docker exec -i mpls-neo4j cypher-shell -u $${NEO4J_USER:-neo4j} -p $${NEO4J_PASSWORD:-neo4j_dev_password} < scripts/lab/lab1_reset_vector.cypher
	@echo "Vectors removed from Postgres and Neo4j. Semantic search fails until Lab 1 is complete."

lab1-solution: ## Apply the reference DDL for Lab 1 (spoiler)
	docker exec -i mpls-postgres psql -U $${PG_USER:-mpls} -d $${PG_DATABASE:-mplsdb} < scripts/lab/lab1_solution_vector.sql

embed-tickets: ## Generate and backfill ticket embeddings (Postgres)
	$(PY) python scripts/embed_tickets.py

embed-devices: ## Generate and backfill device profile embeddings (Neo4j)
	$(PY) python scripts/embed_devices.py

vector-compare: ## Run the same query against pgvector, Neo4j and OpenSearch
	$(PY) python scripts/compare_vector_stores.py

# ---------- Checks ----------
test: ## Run the full test suite
	$(PY) pytest -v

eval: ## Evaluate answer quality against the golden question set
	$(PY) python eval/run_eval.py

lint: ## Lint the codebase
	$(PY) ruff check .

protocol-version: ## Print the MCP spec version supported by the installed SDK
	$(PY) python scripts/print_protocol_version.py
