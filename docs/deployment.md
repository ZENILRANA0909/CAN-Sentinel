# Deployment

- [Bare-metal / systemd](#bare-metal--systemd)
- [Serving the dashboard](#serving-the-dashboard)
- [Reverse proxy (production TLS)](#reverse-proxy-production-tls)
- [Environment for production](#environment-for-production)
- [Database](#database)
- [Health checks and monitoring](#health-checks-and-monitoring)
- [Upgrading](#upgrading)
- [Hardening checklist](#hardening-checklist)

---

## Bare-metal / systemd

```bash
python3 -m venv /opt/can-sentinel/venv
/opt/can-sentinel/venv/bin/pip install -r backend/requirements.txt
```

```ini
# /etc/systemd/system/can-sentinel.service
[Unit]
Description=CAN-Sentinel backend
After=network.target

[Service]
Type=simple
User=can-sentinel
WorkingDirectory=/opt/can-sentinel/backend
Environment=APP_ENV=production
EnvironmentFile=/opt/can-sentinel/.env
ExecStart=/opt/can-sentinel/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/can-sentinel/data /opt/can-sentinel/logs

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now can-sentinel
journalctl -u can-sentinel -f
```

On Windows, run the same `uvicorn` command under NSSM, Task Scheduler, or any
process manager that restarts on failure — there is nothing platform-specific
about the backend itself.

## Serving the dashboard

Build once and serve the static output with any web server:

```bash
cd frontend && npm ci && npm run build
# dist/ can be served by nginx, Apache, IIS, or any static file host
```

The dashboard reads its API base from `VITE_API_BASE_URL` at **build time**
(defaults to `/api`, same-origin). Set it before building if the API is served
from a different origin than the dashboard:

```bash
VITE_API_BASE_URL=https://api.example.com/api \
VITE_WS_URL=wss://api.example.com/ws/traffic \
npm run build
```

For a quick local preview of the production build:

```bash
npm run preview   # serves dist/ on :4173
```

## Reverse proxy (production TLS)

Terminate TLS at the proxy; the backend does not speak TLS itself. Putting the
dashboard and API behind one origin avoids CORS entirely. An nginx example:

```nginx
server {
    listen 443 ssl http2;
    server_name can-sentinel.example.com;

    ssl_certificate     /etc/letsencrypt/live/can-sentinel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/can-sentinel.example.com/privkey.pem;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    location / {
        root /opt/can-sentinel/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

## Environment for production

```bash
APP_ENV=production
LOG_JSON=true              # line-delimited JSON for a log shipper
LOG_LEVEL=INFO
CORS_ORIGINS=              # empty when served same-origin behind the proxy
DATABASE_URL=sqlite:///./data/can_sentinel.db
```

Set thresholds from a measured baseline, not the demonstration defaults — see
[`docs/detection.md`](detection.md#tuning). If monitoring real hardware, also
set `CAN_INTERFACE=python-can`, `CAN_BUSTYPE`, `CAN_CHANNEL` and replace
`ALLOWED_CAN_IDS` with that vehicle's actual identifier set.

## Database

SQLite is the right choice for a single-node monitoring appliance and is what
ships by default. `DATABASE_URL` accepts a relative path — resolved against the
project root regardless of the working directory the process starts in — or an
absolute one.

Back it up like any file:

```bash
sqlite3 data/can_sentinel.db ".backup data/backup-$(date +%F).db"
```

Retention (`RETENTION_MAX_MESSAGES`, `RETENTION_DAYS`, etc.) keeps the file
bounded automatically; there is no need to prune manually. To outgrow SQLite,
point `DATABASE_URL` at a server (e.g.
`postgresql://user:pass@host/can_sentinel`) — the schema and repositories are
plain SQLAlchemy and do not assume SQLite, though the in-memory
connection-sharing lock in `Database.session()` only activates for SQLite's
`:memory:` mode and is a no-op otherwise.

Migrations:

```bash
alembic upgrade head        # apply
alembic downgrade base      # roll back everything (verified both directions)
alembic revision --autogenerate -m "description"   # after a model change
```

## Health checks and monitoring

`GET /api/health` returns `healthy` or `degraded` and is what a process
manager or load balancer should poll. It never fails purely because the
database is briefly unreachable — it reports the true state instead, which is
what lets an operator tell "starting up" from "actually broken."

For deeper monitoring, `GET /api/status` carries every subsystem's counters —
dropped frames, queue depth, write errors, event throttling — and is designed
to be scraped on an interval and graphed.

The `system_events` table is the audit trail: every start, stop, error and
configuration change, with context. Query it directly, or through
`GET /api/system/events`, when investigating an incident after the fact.

## Upgrading

```bash
git pull
cd backend && pip install -r requirements.txt && python -m alembic upgrade head
cd ../frontend && npm ci && npm run build
sudo systemctl restart can-sentinel
```

Run migrations explicitly whenever the release notes mention a schema change —
nothing runs them automatically.

## Hardening checklist

- [ ] `CORS_ORIGINS` set to the real dashboard origin, or empty for same-origin
- [ ] TLS terminated at a reverse proxy in front of the API
- [ ] The API is **not** exposed directly to the internet — it has no
      authentication and exposes controls that transmit onto a CAN bus
- [ ] `LOG_JSON=true` with logs shipped somewhere durable
- [ ] Retention limits set deliberately, not left at the demonstration defaults
- [ ] Detection thresholds set from a measured baseline, not the shipped ones
- [ ] `ALLOWED_CAN_IDS` reflects the real vehicle's identifier set, if
      monitoring real hardware
- [ ] Backups of the SQLite file (or the external database) on a schedule
- [ ] The service runs as an unprivileged user
- [ ] Read [`../README.md#security-limitations`](../README.md#security-limitations)
      and understand what this system is — and is not
