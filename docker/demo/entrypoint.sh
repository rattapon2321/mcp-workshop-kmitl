#!/usr/bin/env bash
# Start the demo app.
#
# The warm-up step matters more than it looks: a 27B model that has not been
# touched takes tens of seconds to load on the first request. Doing that here
# means it does not happen in front of an audience.
set -euo pipefail

echo "=== AI x IP-MPLS demo ==="
echo "mode: ${DEMO_MODE:-live}"

wait_for() {
    local name=$1 host=$2 port=$3 tries=${4:-60}
    echo -n "waiting for ${name} "
    for _ in $(seq 1 "${tries}"); do
        if (echo >"/dev/tcp/${host}/${port}") 2>/dev/null; then
            echo "ok"; return 0
        fi
        echo -n "."; sleep 2
    done
    echo " TIMEOUT"; return 1
}

wait_for postgres   "${PG_HOST:-postgres}" 5432
wait_for neo4j      neo4j 7687
wait_for opensearch opensearch 9200

if [ "${DEMO_MODE:-live}" = "live" ]; then
    # Warm the model. Failure here is not fatal: replay mode still works, and
    # a slow first answer is better than refusing to start.
    echo -n "warming up the model "
    curl -s --max-time 180 "${LLM_BASE_URL:-http://host.docker.internal:11434/v1}/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"${LLM_MODEL:-gemma3:27b}\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":1}" \
        >/dev/null 2>&1 && echo "ok" || echo "skipped (model unreachable)"
else
    echo "replay mode: no LLM required"
fi

echo "UI  -> http://localhost:8100"
echo "API -> http://localhost:8180/docs"

exec honcho start -f Procfile
