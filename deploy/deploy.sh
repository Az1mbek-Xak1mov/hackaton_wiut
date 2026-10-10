#!/usr/bin/env bash
# Usage: deploy.sh <sha> <actor> <run_id>   (run from /srv/converza/repo, already checked out at <sha>)
set -euo pipefail
SHA="$1"; ACTOR="${2:-manual}"; RUN="${3:-0}"
ROOT=/srv/converza
cd "$ROOT/repo"
export COMPOSE_PROJECT_NAME=converza
DC="docker compose -p converza --env-file $ROOT/.env -f compose.prod.yml"

PREV=$(tail -n 50 "$ROOT/deploys.log" 2>/dev/null | awk '$5=="ok"{s=$2} END{print s}')

$DC build --build-arg GIT_SHA="$SHA" --build-arg BUILT_AT="$(date -Iseconds)"

if $DC ps --status running db 2>/dev/null | grep -q db; then
  $DC exec -T db pg_dump -U app app | gzip > "$ROOT/backups/$(date +%Y%m%dT%H%M%S)_${SHA:0:7}.sql.gz" || true
  ls -1t "$ROOT"/backups/*.sql.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
fi

export DEPLOYED_AT="$(date -Iseconds)"
$DC up -d --remove-orphans

ok=0
for i in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8050/health >/dev/null 2>&1 && curl -fsS http://127.0.0.1:8051/ >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done

if [ "$ok" != 1 ]; then
  echo "$(date -Iseconds) $SHA $ACTOR $RUN failed" >> "$ROOT/deploys.log"
  $DC logs --tail 80 api || true
  if [ -n "$PREV" ] && [ "$PREV" != "$SHA" ]; then
    echo "health check failed, rolling back to $PREV"
    git checkout -q --detach "$PREV" && bash deploy/deploy.sh "$PREV" "rollback" "$RUN" || true
  fi
  exit 1
fi

if grep -q '^SEED_DEMO=true' "$ROOT/.env" 2>/dev/null; then
  $DC --profile seed run --rm -d seed >/dev/null 2>&1 || true
fi

echo "$(date -Iseconds) $SHA $ACTOR $RUN ok" >> "$ROOT/deploys.log"
docker image prune -f >/dev/null 2>&1 || true
echo "deployed $SHA"
