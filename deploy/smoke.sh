#!/usr/bin/env bash
# End-to-end smoke test against a running BoardRoom instance.
# Usage: ./deploy/smoke.sh [BASE_URL] [PROJECT_PATH]
#   BASE_URL     default http://localhost:8000
#   PROJECT_PATH path to a KiCad project dir VISIBLE TO THE SERVER
# Exits 0 when a session reaches "signed" and the review downloads.

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
PROJECT_PATH="${2:-/app/fixtures/stickhub}"

echo "1/4 health..."
curl -sf "${BASE_URL}/health" | grep -q '"ok"'

echo "2/4 create session for ${PROJECT_PATH}..."
SESSION_ID=$(curl -sf -X POST "${BASE_URL}/sessions" \
  -H "Content-Type: application/json" \
  -d "{\"project_path\": \"${PROJECT_PATH}\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "    session ${SESSION_ID}"

echo "3/4 wait for signed state (timeout 600s)..."
for i in $(seq 1 120); do
  STATE=$(curl -sf "${BASE_URL}/sessions/${SESSION_ID}" | python3 -c "import sys,json;print(json.load(sys.stdin)['state'])")
  case "$STATE" in
    signed) break ;;
    failed) echo "session FAILED"; curl -sf "${BASE_URL}/sessions/${SESSION_ID}"; exit 1 ;;
    *) sleep 5 ;;
  esac
done
[ "${STATE:-}" = "signed" ] || { echo "timed out in state ${STATE:-unknown}"; exit 1; }

echo "4/4 download review..."
curl -sf "${BASE_URL}/sessions/${SESSION_ID}/review" > /tmp/boardroom_smoke_review.json
python3 -c "import json;r=json.load(open('/tmp/boardroom_smoke_review.json'));print(f'  findings: {len(r[\"findings\"])}, coverage notes: {len(r.get(\"coverage_notes\",[]))}')"
echo "SMOKE OK"
