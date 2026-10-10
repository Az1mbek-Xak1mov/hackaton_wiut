# 06 — Deployment

## Server facts (checked 2026-10-10 17:00)

| Item | Value |
|---|---|
| Host | `deploy@159.195.213.245`, Debian 13, 4 vCPU, 7.8 GiB RAM (~5.6 GiB available), 220 GB free disk, **no GPU** |
| Shared with | satstars (web/api/redis/postgres), goedu (backend/db), samfreightinc, maestrokids (off) — **production sites; never restart host nginx without `nginx -t`** |
| Reverse proxy | host nginx (`/etc/nginx/sites-enabled/*.conf`), certbot on the host, `deploy` has passwordless sudo and is in the `docker` group |
| Ports taken | 127.0.0.1:8000, 8020, 8030, 8040 → **we use 127.0.0.1:8050 (api), 8051 (web)** |
| DNS | `converza.uz` currently resolves to **77.42.28.135** (NS rdns*.ahost.uz) → T-001 repoints it to 159.195.213.245 |

## Layout

```
/srv/converza/
  repo/            git checkout of the deployed SHA (detached)
  .env             secrets (chmod 600, owner deploy)
  deploys.log      "2026-10-10T18:22+05:00 <sha> <actor> <run_id> ok"
  backups/         pg_dump before each migration (keep 5)
docker volumes: converza_db-data, converza_files
```

## Compose services (`compose.prod.yml`, project name `converza`)

| Service | Image | Ports | Command | Limits | Health |
|---|---|---|---|---|---|
| db | postgres:16-alpine | none | — | 512m | `pg_isready` |
| api | built from `Dockerfile` (`converza-app:<sha>`) | 127.0.0.1:8050:8020 | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8020 --workers 2` | 1g, cpus 1.5 | `GET /health` |
| worker | same image | none | `python -m app.worker` | 2g, cpus 2 | heartbeat row age < 60 s |
| web | built from `web/Dockerfile` (node build → nginx:alpine) | 127.0.0.1:8051:80 | — | 64m | `GET /` |

`SEED_DEMO=true` runs `python -m app.seed_demo` once (idempotent) as a one-shot `seed` service with `profiles: [seed]`, invoked by the deploy script after migrations.

## Host nginx vhost: `/etc/nginx/sites-available/converza.uz.conf` (symlinked into sites-enabled)

```nginx
limit_req_zone $binary_remote_addr zone=converza_analyse:10m rate=10r/m;

server {
    server_name converza.uz www.converza.uz;
    access_log /var/log/nginx/converza.access.log;
    error_log  /var/log/nginx/converza.error.log;
    client_max_body_size 25m;

    location ^~ /.well-known/acme-challenge/ { root /var/www/html; }

    location = /api/v1/analyse {
        limit_req zone=converza_analyse burst=5 nodelay;
        proxy_pass http://127.0.0.1:8050;
        include /etc/nginx/proxy_params;
        proxy_read_timeout 70s;
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8050;
        include /etc/nginx/proxy_params;
        proxy_read_timeout 70s;
    }
    location /health { proxy_pass http://127.0.0.1:8050; }
    location / {
        proxy_pass http://127.0.0.1:8051;
        include /etc/nginx/proxy_params;
    }
    listen 80; listen [::]:80;
}
```

Then: `sudo nginx -t && sudo systemctl reload nginx && sudo certbot --nginx -d converza.uz -d www.converza.uz --redirect --register-unsafely-without-email --agree-tos -n`. Certbot adds the 443 block. Afterwards: `curl -sI https://satstars.uz https://admin.goedu.uz | head` to confirm the neighbours still work.

## GitHub Actions: `.github/workflows/deploy.yml`

```yaml
name: deploy
on:
  push: { branches: [main] }
  workflow_dispatch: { inputs: { sha: { description: "SHA to deploy (rollback)", required: false } } }
concurrency: { group: production, cancel-in-progress: false }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked && uv run pytest -q
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: cd web && npm ci && npm run build
  deploy:
    needs: test
    runs-on: ubuntu-latest
    environment: { name: production, url: https://converza.uz }
    steps:
      - name: ssh deploy
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: deploy
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: /srv/converza/repo/deploy/deploy.sh ${{ inputs.sha || github.sha }} ${{ github.actor }} ${{ github.run_id }}
      - name: verify
        run: test "$(curl -fsS https://converza.uz/api/v1/version | jq -r .git_sha)" = "${{ inputs.sha || github.sha }}"
```

`deploy/deploy.sh <sha> <actor> <run_id>`: `set -euo pipefail` → `git -C repo fetch origin && git -C repo checkout --detach <sha>` → `docker compose -p converza -f compose.prod.yml build --build-arg GIT_SHA=<sha> --build-arg BUILT_AT=$(date -Iseconds)` → `pg_dump` to `backups/` → `docker compose up -d` → wait for `/health` (60 s) → `docker compose --profile seed run --rm seed` (if `SEED_DEMO=true`) → append `deploys.log` → prune images older than the last 5 tags. On a health failure: re-run itself with the previous SHA from `deploys.log` and exit 1.

## Env / secrets

| Name | Where | Value source |
|---|---|---|
| `DEPLOY_HOST`, `DEPLOY_SSH_KEY` | GitHub secrets | new ed25519 key; public half appended to `deploy`'s `authorized_keys` with `restrict` |
| `JWT_SECRET` | server `.env` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | server `.env` | `openssl rand -hex 16` |
| `OPENAI_API_KEY` | server `.env` | team key with a hard monthly limit set in the OpenAI dashboard |
| `LLM_PROVIDER=openai`, `LLM_MODEL`, `LLM_REDACT=true`, `LLM_TIMEOUT_S=20` | `.env` | |
| `SEED_ADMIN_EMAIL/PASSWORD`, `DEMO_LOGIN_ENABLED=true`, `SEED_DEMO=true` | `.env` | |
| `WORKER_CONCURRENCY=2`, `PUBLIC_RETENTION_HOURS=24`, `PUBLIC_DEADLINE_S=55` | `.env` | |
| `CORS_ORIGINS=["https://converza.uz"]` | `.env` | |

`.env.example` in the repo lists all of them with comments (blueprint §4).

## Rollback

1. GitHub → Actions → deploy → Run workflow with `sha` = the previous line of `deploys.log` (or `git tag`).
2. Emergency (GitHub down): `ssh deploy@159.195.213.245 /srv/converza/repo/deploy/deploy.sh <sha> manual 0`.
3. A migration that broke data: `docker compose exec -T db psql … < backups/<latest>.sql` after stopping api/worker.

## Showing deployment history at the defence

| Evidence | Where |
|---|---|
| Every deploy with SHA, time, actor, status | GitHub repo → **Deployments** (environment `production`) and Actions run list |
| Running version | footer of every page: `v1.0 · <sha7> · deployed 2026-10-10 23:1x` from `/api/v1/version` |
| Server-side log | `/srv/converza/deploys.log` (screenshot in the deck appendix) |
| Code freeze | tag `v1.0` = last deployed SHA before 23:15; no deploys after it (Deployments list shows it) |
