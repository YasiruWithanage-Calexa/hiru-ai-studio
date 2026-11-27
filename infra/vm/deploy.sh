#!/usr/bin/env bash
# Runs ON the API VM, as root, started by scripts/deploy_api.ps1: `deploy.sh <project> <region>` with the uploaded
# files beside it. Builds api.env (settings + secret values read with the VM's own identity), starts the new version,
# waits for it to be healthy, and restores the previous one when it is not.
set -euo pipefail
PROJECT="$1"
REGION="$2"
FROM="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/hiru
umask 077

for _ in $(seq 1 60); do docker compose version >/dev/null 2>&1 && break; sleep 5; done # a first boot still installs
docker compose version >/dev/null

token() {
  curl -fsS -H "Metadata-Flavor: Google" \
    http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
}
TOKEN="$(token)"

# compose reads a single-quoted value literally (a `$` in a password stays a `$`).
quote() { python3 -c 'import sys; v=sys.stdin.read(); print("\x27" + v.replace("\x27", "\\\x27") + "\x27")'; }

: > "$FROM/api.env"
while IFS='=' read -r name value; do
  [ -n "$name" ] || continue
  printf '%s=%s\n' "$name" "$(printf '%s' "$value" | quote)" >> "$FROM/api.env"
done < "$FROM/settings.env"
while IFS='=' read -r name secret; do
  [ -n "$name" ] || continue
  value="$(curl -fsS -H "Authorization: Bearer $TOKEN" \
    "https://secretmanager.googleapis.com/v1/projects/$PROJECT/secrets/$secret/versions/latest:access" |
    python3 -c 'import base64,json,sys; sys.stdout.write(base64.b64decode(json.load(sys.stdin)["payload"]["data"]).decode().strip())')"
  [ -n "$value" ] || { echo "The secret $secret is empty" >&2; exit 1; }
  printf '%s=%s\n' "$name" "$(printf '%s' "$value" | quote)" >> "$FROM/api.env"
done < "$FROM/secrets.list"

printf '%s' "$TOKEN" | docker login -u oauth2accesstoken --password-stdin "https://$REGION-docker.pkg.dev" >/dev/null

# keep what runs now, to go back to
rm -rf "$APP/previous"
if [ -f "$APP/.env" ]; then
  mkdir -p "$APP/previous"
  cp -p "$APP/.env" "$APP/api.env" "$APP/compose.yaml" "$APP/Caddyfile" "$APP/previous/"
fi
install -m 600 "$FROM/compose.env" "$APP/.env"
install -m 600 "$FROM/api.env" "$APP/api.env"
install -m 644 "$FROM/compose.yaml" "$APP/compose.yaml"
install -m 644 "$FROM/Caddyfile" "$APP/Caddyfile"
rm -rf "$FROM" # nothing with a secret stays in /tmp

healthy() {
  local id
  for _ in $(seq 1 30); do
    id="$(docker compose ps -q api)"
    [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null)" = healthy ] && return 0
    sleep 5
  done
  return 1
}

cd "$APP"
if docker compose pull --quiet && docker compose up -d --remove-orphans && healthy; then
  docker compose restart caddy >/dev/null # picks up a changed Caddyfile
  docker image prune -af --filter "until=336h" >/dev/null || true
  echo "The new version is healthy."
  exit 0
fi

echo "The new version did not become healthy. Its last log lines are in Cloud Logging." >&2
if [ -d "$APP/previous" ]; then
  cp -p "$APP/previous/." "$APP/" -r
  docker compose up -d --remove-orphans && healthy && echo "The previous version is running again." >&2
fi
exit 1
