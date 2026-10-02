#!/usr/bin/env bash
# =============================================================================
# Avvio dell'intera architettura a microservizi in un colpo solo (macOS/Linux).
#
#   ./scripts/avvia_tutto.sh          avvia i 4 servizi
#   ./scripts/avvia_tutto.sh stop     li ferma
#
# I log finiscono in logs/. Per la correzione passo-passo si possono comunque
# avviare i servizi a mano in 4 terminali (vedi README).
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs shared/charts

PID_FILE="logs/servizi.pid"

stop_all() {
  if [[ -f "$PID_FILE" ]]; then
    while read -r pid nome; do
      if kill -0 "$pid" 2>/dev/null; then
        echo "  ⏹  fermo $nome (pid $pid)"
        kill "$pid" 2>/dev/null || true
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi

  # Rete di sicurezza: libera comunque le porte dei quattro servizi, perché un
  # processo avviato a mano (o un figlio sopravvissuto) resterebbe in ascolto.
  for porta in "${CHROMA_PORT:-8001}" "${DATA_AGENT_PORT:-8000}" "${BACKEND_PORT:-3001}" 5173; do
    for pid in $(lsof -ti:"$porta" 2>/dev/null); do
      echo "  ⏹  libero la porta $porta (pid $pid)"
      kill "$pid" 2>/dev/null || true
    done
  done
  echo "✅ Servizi fermati."
}

if [[ "${1:-start}" == "stop" ]]; then
  stop_all
  exit 0
fi

if [[ ! -f .env ]]; then
  echo "❌ Manca il file .env alla root. Copia .env.example in .env e inserisci OPENAI_API_KEY."
  exit 1
fi

set -a; source .env; set +a

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "❌ OPENAI_API_KEY non valorizzata nel file .env."
  exit 1
fi

PY="$ROOT_DIR/data_agent/venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "❌ Virtualenv Python non trovato in data_agent/venv (vedi README, step 3)."
  exit 1
fi

: > "$PID_FILE"

echo "🚀 Avvio dell'architettura..."

# 1) ChromaDB -----------------------------------------------------------------
echo "  1/4 ChromaDB     -> http://localhost:${CHROMA_PORT:-8001}"
(exec "$ROOT_DIR/data_agent/venv/bin/chroma" run \
  --path "$ROOT_DIR/chroma_db" \
  --host "${CHROMA_HOST:-localhost}" \
  --port "${CHROMA_PORT:-8001}" > logs/chroma.log 2>&1) &
echo "$! chromadb" >> "$PID_FILE"

# 2) Data agent Python --------------------------------------------------------
echo "  2/4 Data agent   -> http://localhost:${DATA_AGENT_PORT:-8000}"
(cd "$ROOT_DIR/data_agent" && exec "$ROOT_DIR/data_agent/venv/bin/uvicorn" app.main:app \
  --host 127.0.0.1 --port "${DATA_AGENT_PORT:-8000}" > "$ROOT_DIR/logs/data_agent.log" 2>&1) &
echo "$! data_agent" >> "$PID_FILE"

# 3) Backend Node -------------------------------------------------------------
echo "  3/4 Backend Node -> http://localhost:${BACKEND_PORT:-3001}"
(cd "$ROOT_DIR/backend" && exec node src/server.js > "$ROOT_DIR/logs/backend.log" 2>&1) &
echo "$! backend" >> "$PID_FILE"

# 4) Front end React ----------------------------------------------------------
echo "  4/4 Front end    -> http://localhost:5173"
(cd "$ROOT_DIR/frontend" && exec node_modules/.bin/vite > "$ROOT_DIR/logs/frontend.log" 2>&1) &
echo "$! frontend" >> "$PID_FILE"

sleep 12
echo ""
echo "📊 Stato dei servizi:"
curl -s -m 5 "http://localhost:${BACKEND_PORT:-3001}/api/health" || echo "  (backend non ancora pronto, riprova fra qualche secondo)"
echo ""
echo ""
echo "👉 Apri http://localhost:5173"
echo "   Log in logs/ · per fermare tutto: ./scripts/avvia_tutto.sh stop"
