# Deployment

<!-- nav:start -->
[Docs](README.md) · [Spec](spec.md) · [Architecture](architecture.md) · [Database](database.md) · [Accounting](accounting.md) · [API](api.md) · [Security](security.md) · [Audit](security-audit.md) · [Development](development.md) · **Deployment**
<!-- nav:end -->

Self-hosted on a single VPS with Docker Compose. Everything below assumes Ubuntu
22.04+ or Debian 12+.

**Minimum viable server:** 2 vCPU, 4 GB RAM, 40 GB SSD. The compose file's
resource limits assume roughly that; PostgreSQL's `shared_buffers` should be
raised to about 25% of RAM on anything larger.

---

## 1. Prepare the server

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER" && newgrp docker

# Firewall - only SSH and HTTP(S) reach the host.
# PostgreSQL and Redis are never published; they live on the internal Docker
# network, which is what stops a misconfigured rule exposing the database.
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Unattended security updates
sudo apt install -y unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 2. Configure

```bash
sudo mkdir -p /srv/personalerp && sudo chown "$USER" /srv/personalerp
git clone <repo> /srv/personalerp && cd /srv/personalerp
cp .env.example .env
```

Generate real secrets - do not hand-write them:

```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(32))"
```

Required production values:

```env
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<64-byte random>
ENCRYPTION_KEY=<Fernet key>
POSTGRES_PASSWORD=<strong>
REDIS_PASSWORD=<strong>
CORS_ORIGINS=https://app.yourdomain.com
ALLOWED_HOSTS=app.yourdomain.com
FRONTEND_URL=https://app.yourdomain.com
PUBLIC_API_URL=https://app.yourdomain.com
LOG_JSON=true

# Email. Base64 of a pickled Credentials with the gmail.send scope. Produce it with
# `uv run python scripts/mint_gmail_token.py`, and keep it in a secret store.
GMAIL_CREDENTIALS_B64=<output of scripts/mint_gmail_token.py>
GMAIL_SENDER=no-reply@yourdomain.com
EMAIL_FROM_NAME=Personal ERP
```

```bash
chmod 600 .env
```

The app **validates this at boot and refuses to start** if `SECRET_KEY` is a
placeholder, `DEBUG` is true, CORS is `*`, `ENCRYPTION_KEY` is missing, or the
database password is still a default. Crashing at boot beats silently serving
traffic with a placeholder signing key.

> `PUBLIC_API_URL` is baked into the frontend bundle at **build** time, because
> Vite inlines `VITE_*` values. Changing it later requires a rebuild, not a
> restart.

---

## 3. TLS

Point an A record at the server, then edit
`infra/nginx/conf.d/personalerp.conf`, replacing `app.example.com` with the real
domain (three places: the HTTP block, the HTTPS block, and the certificate paths).

```bash
# The HTTP block must be live first - the ACME challenge is served over plain HTTP.
docker compose -f docker-compose.prod.yml up -d nginx

docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d app.yourdomain.com \
  --agree-tos -m you@yourdomain.com --no-eff-email

docker compose -f docker-compose.prod.yml restart nginx
```

Renewal is automatic: the `certbot` service wakes twice daily and renews inside
the 30-day window. Cheap, and a renewal is never missed.

---

## 4. Launch

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl -fsS https://app.yourdomain.com/health/ready
```

Migrations run as a **one-shot `migrate` service** that the API waits on via
`service_completed_successfully`. This is what makes two API replicas safe - they
cannot race to apply the same migration.

Register the first account at `https://app.yourdomain.com/register`. The first user
to create an organization becomes its owner.

---

## 5. Backups

```bash
# Nightly at 02:00
(crontab -l 2>/dev/null; echo "0 2 * * * cd /srv/personalerp && ./infra/scripts/backup.sh >> logs/backup.log 2>&1") | crontab -
```

`backup.sh` writes a compressed custom-format dump, **verifies it** with
`pg_restore --list`, and prunes archives older than 14 days. The verification step
is not optional decoration: a backup that has never been read back is a guess.

Restoring:

```bash
./infra/scripts/restore.sh infra/backups/personalerp-20260726T020000Z.dump
```

It requires typing the database name, stops the app, restores in a single
transaction, and re-applies any migrations newer than the backup.

**Copy backups off the machine.** A backup on the same disk as the database does
not survive the failure it exists for:

```bash
0 3 * * * rclone sync /srv/personalerp/infra/backups remote:personalerp-backups
```

---

## 6. Deploying updates

### Automated

Tag a release. `.github/workflows/deploy.yml` builds and publishes images, then
over SSH: backs up the database, pulls, migrates, and rolls out.

```bash
git tag v0.2.0 && git push origin v0.2.0
```

Required secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_APP_PATH`, and the
`PUBLIC_API_URL` variable.

### Manual

```bash
cd /srv/personalerp
./infra/scripts/backup.sh                                    # always first
git pull --ff-only
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm migrate    # separate step, on purpose
docker compose -f docker-compose.prod.yml up -d --no-deps backend frontend
curl -fsS https://app.yourdomain.com/health/ready
```

### Why zero-downtime works

Three things together:

1. **`order: start-first`** - the replacement container starts and passes its
   health check before the old one stops.
2. **Stateless replicas** - no instance holds session state, so Nginx can route to
   either during the overlap.
3. **Migrations as a separate step** - if a migration fails, the currently-running
   version keeps serving traffic untouched. Rolling out first and migrating after
   would leave the new code pointed at an old schema.

The corollary is a constraint on migrations: during the overlap, two versions run
against one schema. A migration must be **backward-compatible with the previous
release**. Adding a nullable column is safe; dropping a column the old code still
reads is not. Renames become expand → migrate → contract across two deploys.

### Rolling back

```bash
# Images are tagged by commit SHA precisely so this is exact
docker compose -f docker-compose.prod.yml pull
IMAGE_TAG=sha-<previous> docker compose -f docker-compose.prod.yml up -d backend frontend
```

If the schema also changed: `alembic downgrade -1`. CI verifies every migration is
reversible on every pull request, so this path is tested before it is needed.

---

## 7. Operating it

### Logs

logifyx writes JSON in production (`LOG_JSON=true`), to both stdout and rotating
files in `./logs`.

```bash
docker compose -f docker-compose.prod.yml logs -f --tail=100 backend
tail -f logs/personalerp.log | jq 'select(.levelname == "ERROR")'
tail -f logs/personalerp.log | jq 'select(.request_id == "01930f4c-...")'   # one request
```

Every line carries `request_id`, and authenticated lines carry `user_id` and
`org_id`. Audit rows store the same `request_id`, so a business event pivots
directly to its operational log lines.

Container logs are capped at 10 MB × 3 files per service. Without that, logs grow
without bound and eventually fill the disk - the most common way a small VPS dies.

### Health

| Endpoint | Use |
| --- | --- |
| `/health/live` | Liveness. No dependency checks, deliberately |
| `/health/ready` | Readiness. 503 when PostgreSQL or Redis is down |
| `/health` | Human-readable summary |

Point external monitoring at `/health/ready`.

### Common problems

**Backend will not start** - almost always failed config validation. The error
names every problem:

```bash
docker compose -f docker-compose.prod.yml logs backend | head -30
```

**502 from Nginx** - the backend is not healthy yet, or migrations failed:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs migrate
```

**No emails** - check `GMAIL_CREDENTIALS_B64` is set (unset means log-only, which
is the development default and a common production oversight). A failure logs
Google's own wording, including `invalid_grant` for a revoked refresh token and
an insufficient-scope message for a token without `gmail.send`:

```bash
docker compose -f docker-compose.prod.yml logs backend | grep -i "email"
```

**`invalid_grant`** - Google has rejected the refresh token itself, so the value is
dead rather than misconfigured and no restart or retry recovers it. Mint a new one
with `uv run python scripts/mint_gmail_token.py` and redeploy the secret. Then fix
the cause, because a replacement token dies the same way: most often the OAuth
consent screen is still in **Testing**, where Google expires every refresh token
after 7 days - publish the app to stop it. Otherwise the token was revoked from the
account's third-party access, the account password changed, the OAuth client was
deleted or recreated, or the host clock has drifted far enough for Google to reject
the assertion (`timedatectl status`).

**"Session is no longer valid" immediately after signing in** - the token epoch
was bumped, or the client and server clocks disagree. Check `timedatectl`.

### Scaling

```bash
# More API replicas on the same host
docker compose -f docker-compose.prod.yml up -d --scale backend=4
```

Nginx resolves the service name to every replica, so no config change is needed.
Beyond one host, the ordered next steps are: move PostgreSQL to managed hosting
with a read replica, put PgBouncer in front of it, add Redis Sentinel, and move
static assets to a CDN.

---

## 8. Pre-flight checklist

- [ ] `.env` has real secrets; `chmod 600`
- [ ] `ENVIRONMENT=production`, `DEBUG=false`
- [ ] `CORS_ORIGINS` and `ALLOWED_HOSTS` name the real domain, no wildcards
- [ ] `ENCRYPTION_KEY` set (2FA secrets are encrypted at rest)
- [ ] TLS certificate issued; HTTP redirects to HTTPS
- [ ] `GMAIL_CREDENTIALS_B64` and `GMAIL_SENDER` set, and a test email received
- [ ] Nightly backups scheduled **and a restore rehearsed**
- [ ] Backups replicated off the machine
- [ ] `ufw` allows only 22, 80, 443
- [ ] PostgreSQL and Redis not published to the host (`docker compose ps` shows no
      host ports for them)
- [ ] `/docs` returns 404 in production
- [ ] External monitoring on `/health/ready`
- [ ] SSH key-only authentication; password login disabled
- [ ] First owner account created

The restore rehearsal is the one people skip, and it is the one that matters.

<!-- related:start -->

---

## Related reading

- [Security](security.md) - what to verify is switched on before opening a port
- [Database](database.md) - backup and restore mechanics in detail
- [Development](development.md) - the local stack this mirrors

[All documentation](README.md)
<!-- related:end -->
