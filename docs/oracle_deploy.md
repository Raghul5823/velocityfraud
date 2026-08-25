# Oracle Cloud Deploy Runbook (Wk 14–15)

Deploys VelocityFraud to **Oracle Cloud Free Tier Ampere A1 (arm64)** VMs:
- **vf-demo** — runs the full stack (system under test)
- **vf-loadgen** — 2nd VM, Wk 15 only, drives the 10k tx/min scale test

All container images are confirmed multi-arch (arm64), so no image changes are
needed. Python deps have aarch64 wheels.

---

## 0. Prerequisites (one-time)

- Oracle Cloud account (Always Free tier)
- An SSH key pair for the VMs

## 1. Provision vf-demo

Oracle console → **Compute → Instances → Create instance**:
- Name: `vf-demo`
- Image: **Ubuntu 24.04** (or 22.04)
- Shape: **VM.Standard.A1.Flex** — **4 OCPU / 24 GB** (fits Always-Free)
- Add your SSH public key
- Create. Note the **public IP**.

## 2. Networking (choose ONE)

**Option A — SSH tunnel (recommended, nothing exposed publicly):**
From your laptop, tunnel the ports you need:
```bash
ssh -i <key> -L 9092:localhost:9092 -L 8000:localhost:8000 \
    -L 5000:localhost:5000 -L 8081:localhost:8081 ubuntu@<vf-demo-ip>
```

**Option B — open ports** (only if the load-gen VM must reach Kafka directly):
Add ingress rules in the subnet's Security List for the ports you need
(e.g. 9092 from the vf-loadgen private IP only). Prefer private-subnet traffic.

## 3. Install Docker + uv + git on the VM

```bash
sudo apt-get update && sudo apt-get install -y git curl
# Docker Engine + compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

## 4. Get the code + data

```bash
git clone https://github.com/Raghul5823/velocityfraud.git
cd velocityfraud
```
Copy the artifacts that are NOT in git (from your laptop, via scp):
```bash
# models (small) + processed feature splits + a data sample for the replayer
scp -i <key> -r models data/processed ubuntu@<vf-demo-ip>:~/velocityfraud/
scp -i <key> data/raw/train_transaction.csv ubuntu@<vf-demo-ip>:~/velocityfraud/data/raw/
scp -i <key> .env ubuntu@<vf-demo-ip>:~/velocityfraud/
```
(The 683 MB CSV is the slow copy; everything else is small.)

## 5. Bring up the infra

```bash
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml ps        # all healthy?
uv sync --dev                                          # installs aarch64 wheels
```

## 6. Create topics + apply DB migrations

```bash
# topics (bash equivalent of scripts/create-topics.ps1)
for t in transactions.raw transactions.scored transactions.enriched \
         transactions.scored.groq transactions.feedback; do
  docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --create --if-not-exists \
    --topic $t --bootstrap-server localhost:9092 --partitions 3 --replication-factor 1
done
uv run python -m velocityfraud.db          # applies all migrations
```

## 7. Run the pipeline

Use separate terminals (or `tmux`/`nohup ... &`):
```bash
uv run python -m velocityfraud.replayer          # producer
uv run python -m velocityfraud.scorer            # fast-path scorer
uv run python -m velocityfraud.sink              # Kafka -> Postgres
OMP_NUM_THREADS=1 uv run uvicorn velocityfraud.api:app --host 0.0.0.0 --port 8000 --workers 4
```

## 8. Smoke test (deploy-from-clean-clone)

```bash
curl -s localhost:8000/health          # {"status":"ok","model_loaded":true,...}
curl -s -X POST localhost:8000/score -H 'content-type: application/json' \
     -d '{"event_id":"smoke","amount":125.99,"merchant_name":"W-MERCHANT-gmail.com","mcc":"5411","card_token":"c1"}'
```
Expect a JSON body with a `decision`. That's the Wk-14 "pipeline running on
vf-demo" deliverable.

---

## 9. Wk 15 — Scale test (vf-loadgen)

1. Provision **vf-loadgen** (same Ampere A1 shape, same region/subnet).
2. Install k6 (arm64) + the repo's `perf/` folder:
   ```bash
   # k6 arm64
   curl -L https://github.com/grafana/k6/releases/download/v0.55.0/k6-v0.55.0-linux-arm64.tar.gz | tar xz
   ```
3. Point k6 at vf-demo's private IP and run the sustained certificate:
   ```bash
   ./k6 run -e BASE_URL=http://<vf-demo-private-ip>:8000 -e DURATION=30m perf/k6-score.js
   ```
   Target: **10k tx/min (167/s), p95 < 200 ms fast-path**. Also run Locust
   (`perf/locustfile.py`) for the concurrent-user view. Capture the summaries as
   the **throughput certificate** (Item 7).

---

## Notes / gotchas

- **Free-tier capacity:** Ampere A1 can be hard to get in busy regions. If
  provisioning fails, retry in another Availability Domain or use the
  `~₹350` Hetzner CAX11 (arm64) contingency line from the proposal.
- **Redis co-located** on vf-demo means the blocklist round-trips are sub-ms
  (unlike the local dev box's Docker-Desktop NAT), so the full path — not just
  the ML-only path — should hold the latency budget.
- **Memory:** 24 GB is ample for Kafka(2g) + Postgres + Redis + MLflow + the
  Python services.
