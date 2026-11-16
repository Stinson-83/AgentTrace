#!/usr/bin/env bash
# Run the GPT-6.1 Sol rollout for every environment through Harbor, exactly as the assignment specifies.
# Reads OPENAI_BASE_URL / OPENAI_API_KEY from .env (never printed), discovers environments/*/, and
# keeps every Harbor log under jobs/<env>/. Results are copied by scripts/collect_rollouts.py.
#   usage: scripts/run_rollouts.sh [env ...]        (JOB_NAME=rollout by default)
set -euo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

if [ ! -f "$S/.env" ]; then echo "missing $S/.env (OPENAI_BASE_URL / OPENAI_API_KEY)"; exit 2; fi
set -a; . "$S/.env"; set +a
if [ -z "${OPENAI_API_KEY:-}" ] || [ "${OPENAI_API_KEY}" = "PASTE_YOUR_API_KEY_HERE" ]; then
  echo "OPENAI_API_KEY is not set in .env — paste the assignment key first"; exit 2
fi
if [ -z "${OPENAI_BASE_URL:-}" ]; then echo "OPENAI_BASE_URL is not set"; exit 2; fi

# Connectivity check (prints model name only; never the key).
if ! curl -sf --max-time 180 "$OPENAI_BASE_URL/chat/completions" -H "Authorization: Bearer $OPENAI_API_KEY" \
     -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"Hi how are you"}]}' \
     | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d.get("model")=="gpt-6.1-sol" and d.get("choices"); print("endpoint ok: model", d["model"])'; then
  echo "endpoint check failed (authentication or availability)"; exit 3
fi

JOB_NAME="${JOB_NAME:-rollout}"
ENVS=("$@")
if [ ${#ENVS[@]} -eq 0 ]; then
  for env in "$S"/environments/*/; do ENVS+=("$(basename "$env")"); done
fi
mkdir -p "$S/jobs"
for id in "${ENVS[@]}"; do
  echo "=== rollout: $id (job $JOB_NAME) ==="
  mkdir -p "$S/jobs/$id"
  rm -rf "$S/jobs/$id/$JOB_NAME"
  harbor run -p "$S/environments" -i "$id" -a terminus-2 -m openai/gpt-6.1-sol -k 1 \
      -o "$S/jobs/$id" --job-name "$JOB_NAME" --yes --effort high -n 1 \
      > "$S/jobs/$id/$JOB_NAME.harbor.log" 2>&1 || echo "harbor exited non-zero for $id (see jobs/$id/$JOB_NAME.harbor.log)"
  tail -n 25 "$S/jobs/$id/$JOB_NAME.harbor.log" | grep -vi "api[_-]key" || true
done
python3 "$S/scripts/collect_rollouts.py" --job-name "$JOB_NAME" "${ENVS[@]}"
