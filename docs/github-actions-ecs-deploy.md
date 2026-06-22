# GitHub Actions ECS auto deploy

This project did not have GitHub Actions before. The workflow in
`.github/workflows/deploy-ecs.yml` deploys every push to `main` to the Aliyun ECS.

## What it does

1. GitHub receives a push to `main`.
2. GitHub Actions packages the checked-out code.
3. GitHub Actions uploads the package to the ECS by SSH.
4. The ECS runs `scripts/deploy_server.sh`.
5. The script installs backend dependencies, builds the frontend, restarts FastAPI with systemd, and reloads Nginx.

The ECS does not need GitHub credentials for the normal Actions deploy path.

## Required GitHub secrets

Open GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret.

Create these secrets:

```text
ECS_HOST=47.110.37.81
ECS_USER=root
ECS_PORT=22
DEPLOY_PATH=/opt/temu_listing_workbench
ECS_SSH_PRIVATE_KEY=<private key that can SSH into the ECS>
```

`ECS_USER`, `ECS_PORT`, and `DEPLOY_PATH` have defaults, but setting them makes the deployment explicit.

## Create the SSH key

On your local machine:

```bash
ssh-keygen -t ed25519 -C "github-actions-temu" -f temu_actions_ed25519
```

Put the public key into the ECS:

```bash
cat temu_actions_ed25519.pub
```

Copy the output, then on the ECS:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Paste the public key into `authorized_keys`.

Put the private key into the GitHub secret `ECS_SSH_PRIVATE_KEY`:

```bash
cat temu_actions_ed25519
```

## First-time ECS setup

Run this once on the ECS:

```bash
apt update
apt install -y git curl nginx python3 python3-venv python3-pip
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
```

Create the production env file on the ECS. Do not commit it to Git:

```bash
mkdir -p /opt/temu_listing_workbench
nano /opt/temu_listing_workbench/.env
```

Example keys:

```env
POSTGRES_DATABASE_URL=postgresql://temu_app:<password>@pgm-bp10sp109p8t006r.pg.rds.aliyuncs.com:5432/temu_workbench
DATABASE_URL=postgresql://temu_app:<password>@pgm-bp10sp109p8t006r.pg.rds.aliyuncs.com:5432/temu_workbench
VISUAL_QUEUE_REDIS_ENABLED=0
VISUAL_USER_CONCURRENCY_LIMIT=1
```

Add your OSS and AI channel environment variables here if the backend still depends on them from `.env`.

## Run deployment

Push to `main`, or open GitHub -> Actions -> Deploy ECS -> Run workflow.

After it finishes, open:

```text
http://47.110.37.81/
```

Backend checks:

```bash
systemctl status temu-workbench
journalctl -u temu-workbench -n 100 --no-pager
nginx -t
```
