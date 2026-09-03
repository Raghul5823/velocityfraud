# Cloud Deployment Runbook — Wk 14/15 (Deploy + Scale Test)

> **Status:** ✅ Complete — Wk14 (deploy) and Wk15 (scale test) both certified, servers cleaned up.
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)
> **Proposal reference:** §7 Timeline, Wk 14 ("Deploy to `vf-demo`") and Wk 15 ("Provision `vf-loadgen`, sustained 10K tx/min scale test, k6 + Locust load report").
> **Session date:** 2026-09-01/02 (single continuous session, ~03:00 start to ~03:31 finish local time on the cloud portion)

> **Purpose of this doc:** unlike the `LAYER_N_*.md` docs (which document *what the code does*), this doc documents *how the cloud deployment was actually operated* — the reasoning, the real commands run, the mistakes made and fixed, and the decisions taken along the way. It doubles as (a) evidence for the RFP deliverable and (b) a from-scratch learning reference, since this was the author's first cloud deployment.

---

## 1. Why Cloud At All (not just localhost)

Everything before this point — pytest, k6, Locust, chaos/backpressure tests — ran on localhost and is already evidence-complete. Cloud adds exactly one thing localhost cannot prove: that the pipeline runs correctly on **infrastructure that isn't the developer's own machine**, reachable over the **public internet**, under **sustained external load from a genuinely separate machine**. That is what "deploy to production-like infra" and "scale test" mean as distinct deliverables from "it works on my laptop."

## 2. The Decision Journey (the honest version)

The proposal (Risk #6) named Oracle Cloud Always Free (Ampere A1, ARM) as primary, with **Hetzner CAX11 (ARM) as the explicitly pre-approved fallback** if Oracle had regional capacity issues.

| Step | What happened | Outcome |
|---|---|---|
| 1 | Signed up for Oracle Cloud, added a payment card for verification (a small hold, standard practice) | Card verification hold went through, but the account never reached "ready" state — provisioning appears stuck |
| 2 | Per the proposal's own Risk #6, pivoted to **Hetzner** as the named contingency | Signed up successfully |
| 3 | Hetzner flagged the new account as "increased risk" (routine for new international accounts) and required identity verification | Resolved via **passport document verification** (no credit card required for this step) — approved within minutes |
| 4 | Attempted to provision the ARM (CAX) server line the proposal specified, for ARM-to-ARM parity with `vf-loadgen` | **CAX11/21/31/41 all showed "not available"** across Nuremberg, Falkenstein, and Helsinki — genuine Hetzner-side ARM capacity shortage, not a configuration error |
| 5 | Fell back one layer further than the proposal anticipated: **x86 ("Regular Performance" line, always in stock)** | Both servers provisioned successfully on x86 |

**Why this is still valid, not a shortcut:** VelocityFraud's Docker images are multi-arch (all 6 images support both `arm64` and `amd64`). The deployed *behaviour* is architecture-independent; only the "same-silicon" framing from the proposal's Risk #6 needs this honest footnote. Deployment (Wk14) and the scale-test throughput certificate (Wk15) are unaffected.

## 3. Server Architecture (as actually provisioned)

| Server | Role | Spec (actual) | Location | Public IPv4 | Lifetime |
|---|---|---|---|---|---|
| `vf-demo` | System under test — full stack: Kafka, Postgres, Redis, MLflow, Apicurio, Kafka-UI, FastAPI scoring API | Hetzner **CPX32** — 4 vCPU (x86/AMD), 8 GB RAM, 160 GB SSD, Ubuntu 26.04 | Helsinki (eu-central) | `2.29.1.199` | ~3 hours |
| `vf-loadgen` | Load generator only (Wk 15) — runs k6 + Locust **against** `vf-demo`'s public IP over the public internet, from a genuinely separate machine so results aren't contaminated by shared CPU | Hetzner **CPX22** — 2 vCPU (x86/AMD), 4 GB RAM, 80 GB SSD, Ubuntu 26.04 | Helsinki (eu-central) — same location as `vf-demo`, for a fast network path | `204.168.142.84` | ~2 hours |

**Why two separate servers, not one:** if the load generator and the system-under-test shared one machine, the load generator's own CPU usage would starve the scorer and *contaminate* the latency numbers — you'd be measuring contention, not real throughput. This is Proposal Risk #5's exact concern, resolved by design. `vf-loadgen` is deliberately smaller (2 vCPU is plenty — it only fires HTTP requests, it never runs the stack itself).

## 4. Why SSH (and why a key, not a password)

**SSH (Secure Shell)** is how you get a command-line session on a remote Linux machine over an encrypted connection — the cloud-server equivalent of sitting at the machine's own keyboard.

- **Why a key pair instead of a password:** a password can be guessed/brute-forced over the internet; an SSH key pair cannot be practically brute-forced (ED25519 keys are 256-bit). Hetzner injects the **public** key into the server at creation time; only the matching **private** key (which never leaves your laptop) can open a session. This is why the SSH key had to be generated *before* creating the server, and pasted into the server-creation form.
- **The key pair used for both servers** (generated once, reused — same key works for any server it's attached to at creation):

  | | |
  |---|---|
  | Private key | `C:\Users\raghul.sridhar\.ssh\hetzner-key` (stays on your laptop — never share) |
  | Public key | `C:\Users\raghul.sridhar\.ssh\hetzner-key.pub` |
  | Fingerprint | `SHA256:jRtZ6NB+8/AdvLAhC5QfDl3JcBn0EfhO1H/bA1f0s/o` |
  | Type | ED25519 |

- **How the connection actually works:** `ssh -i <keyfile> root@<public IP>`. The `-i` flag tells the SSH client which private key to offer. The server checks it against the public key it was given at creation — if they match, the session opens with no password prompt.

## 5. Division of Responsibility (as actually followed)

| Task | Who | Why |
|---|---|---|
| Create `vf-demo` / `vf-loadgen`, delete both at the end | 🧑 Human, in the Hetzner browser console | Claude Code has no browser-automation tool — anything click-based in a web UI has to be done by hand. Also the right safety boundary: irreversible/billable actions stay under explicit human control |
| Install Docker, transfer code/model/secrets, bring up the stack, run smoke tests, run the scale tests | 🤖 Claude, via `ssh`/`scp` executed directly from a terminal | Once an IP + SSH key exist, this is command-line work Claude's Bash tool can run and observe output from directly |
| **Screenshots** | 🧑 Human, deliberately, at explicit checkpoints | A conscious choice mid-session: even though Claude could execute and observe commands directly, every terminal command in this deployment was run **by the human, in their own standalone PowerShell window** (not through the AI tool panel), specifically so the evidence screenshots show genuine first-person operation rather than an AI tool's interface |

## 6. Command Log — exactly what was run, in order

### Phase 0 — SSH key generation (local machine)

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/hetzner-key" -N '' -C "hetzner-vf-demo"
```
Result: key pair at `~/.ssh/hetzner-key` / `~/.ssh/hetzner-key.pub`, fingerprint `SHA256:jRtZ6NB+8/AdvLAhC5QfDl3JcBn0EfhO1H/bA1f0s/o`.

### Phase 0.5 — Gotcha: Windows had no SSH client in a plain terminal

Running `ssh -V` in a fresh PowerShell window failed with `"ssh" is not recognized`. **Root cause:** the Windows OpenSSH Client optional feature wasn't installed, and even after installing it, a *stale PATH* problem persisted — Explorer (and everything launched from the Start Menu) caches the system PATH at login and doesn't see updates until specifically refreshed.

**Fix, in order of what was tried:**
1. Install the feature (needs an elevated/admin PowerShell window):
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
   ```
2. A plain new window still failed — confirmed the binary existed but PATH hadn't refreshed:
   ```powershell
   Test-Path "C:\Windows\System32\OpenSSH\ssh.exe"   # returned True
   ```
3. A full computer restart *still* didn't fix it on this machine (an unusual case — normally a restart is sufficient). Root-caused to the User-level PATH environment variable itself not containing the OpenSSH folder, even though it should have been added automatically. **Final fix** — add it directly and permanently, avoiding the classic `setx` truncation bug by using .NET's environment API instead:
   ```powershell
   $old = [Environment]::GetEnvironmentVariable('Path', 'User')
   [Environment]::SetEnvironmentVariable('Path', "$old;C:\Windows\System32\OpenSSH\", 'User')
   ```
4. New window → `ssh -V` → `OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2` — confirmed working.

**Lesson:** don't assume a fresh terminal window means a fresh PATH. Windows caches environment variables at the process-tree level (inherited from Explorer at login), not read live from the registry on every new window.

### Phase 1 — Server creation (Hetzner browser console, manual)

`vf-demo`: Type=CPX32, Architecture=x86 (AMD, "Regular Performance" line — ARM/CAX was sold out on every EU location tried), Location=Helsinki, Image=Ubuntu 26.04, Networking=IPv4+IPv6, SSH key=hetzner-key, Name=vf-demo → **Create & Buy now**. Result: running, public IPv4 `2.29.1.199`.

### Phase 2 — Install Docker, git, uv on `vf-demo`

Connect:
```bash
ssh -i "$env:USERPROFILE\.ssh\hetzner-key" root@2.29.1.199
```
(First connection prompts `The authenticity of host ... can't be established ... Are you sure you want to continue connecting (yes/no)?` — type `yes`. This is SSH verifying the server's host key on first contact; it's remembered afterward.)

Install Docker (official Docker CE repo, not the older `docker.io` Ubuntu package):
```bash
apt-get update -y && apt-get install -y ca-certificates curl git \
  && install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
  && chmod a+r /etc/apt/keyrings/docker.asc \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
  && apt-get update -y \
  && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```
Result: `docker --version` → `29.7.2`, `git --version` → `2.53.0`.

Install `uv` (Python's project/package manager the scoring API needs at runtime, separate from Docker):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env && uv --version
```
Result: `uv 0.12.8`.

### Phase 3 — Transfer code + model + secrets

Clone the repo (public HTTPS clone, no auth needed for a public GitHub repo):
```bash
git clone https://github.com/Raghul5823/velocityfraud.git && cd velocityfraud && ls
```

The trained model (`models/xgboost_v1.pkl`, 4.4 MB) and `.env` (API keys) are **git-ignored by design** — they never touch GitHub, so they have to be copied directly, laptop → server. Run **from a separate local PowerShell window** (not the SSH session — this reads local files):
```powershell
scp -i "$env:USERPROFILE\.ssh\hetzner-key" "...\velocityfraud\models\xgboost_v1.pkl" root@2.29.1.199:/root/velocityfraud/models/
scp -i "$env:USERPROFILE\.ssh\hetzner-key" "...\velocityfraud\.env" root@2.29.1.199:/root/velocityfraud/.env
```
Both confirmed 100% transferred.

Install the exact Python environment the project needs (reads `pyproject.toml`/`uv.lock`, including pulling the right Python interpreter version itself if needed):
```bash
uv sync
```

### Phase 4 — Bring up the stack

```bash
cd infra && docker compose up -d && cd ..
docker ps --format "table {{.Names}}\t{{.Status}}"
```
All 6 containers came up healthy: `vf-kafka`, `vf-postgres`, `vf-redis` (health-checked), `vf-apicurio`, `vf-kafka-ui`, `vf-mlflow`.

Create the 5 Kafka topics (`transactions.raw`, `.scored`, `.enriched`, `.scored.groq`, `.feedback`) via `kafka-topics.sh --create --if-not-exists` for each, then apply the 4 Postgres migrations in order:
```bash
for f in infra/migrations/*.sql; do echo "Applying $f"; docker exec -i vf-postgres psql -U vf -d velocityfraud < "$f"; done
```
All 4 (`001_init.sql`, `002_appeals.sql`, `003_groq_scoring.sql`, `004_feedback.sql`) applied cleanly.

Start the scoring API **detached**, so it survives after this SSH command returns:
```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
nohup uv run uvicorn velocityfraud.api:app --host 0.0.0.0 --port 8000 --workers 2 > api.log 2>&1 &
curl -s http://localhost:8000/health
```
Result: `{"status":"ok","model_loaded":true,"champion":"xgboost_v1.pkl","redis_alive":true,...}`.

**Why `nohup ... &` here (a lighter-weight cousin of `screen`, used later):** without it, the API process is a child of the SSH shell and dies the instant that shell exits or disconnects. `nohup` (no hang-up) makes it ignore that signal, and `&` backgrounds it so the terminal is immediately free for the next command.

### Phase 5 — Smoke test (Wk14 proof)

```bash
curl -s -X POST http://localhost:8000/score -H "Content-Type: application/json" -d '{...a realistic transaction...}' | python3 -m json.tool
```
Result: a genuine live decision — `"decision": "ALLOW"`, `"fraud_score": 0.413...`, `"scoring_latency_ms": 40.6`, champion model `xgboost_v1.pkl` — proving the full pipeline (API → Redis blocklist → XGBoost) works end-to-end on the cloud VM. **This is the Wk14 deliverable, satisfied.**

### Phase 6 — `vf-loadgen` provisioning + scale test (Wk15)

`vf-loadgen` created: CPX22, Helsinki (same region), Ubuntu 26.04, same SSH key, IPv4 `204.168.142.84`.

Install k6 (from Grafana's official apt repo — not in Ubuntu's default repos):
```bash
curl -s https://dl.k6.io/key.gpg | gpg --dearmor | tee /usr/share/keyrings/k6-archive-keyring.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | tee /etc/apt/sources.list.d/k6.list
apt-get update -y && apt-get install -y k6   # -> k6 v2.2.0
```

Install Locust in a **lightweight, separate venv** (deliberately not the full `uv sync` of the whole ML project — a load generator only needs `locust` + `requests`, not XGBoost/torch/transformers):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
uv venv loadgen-env && source loadgen-env/bin/activate && uv pip install locust   # -> locust 2.46.4
```

Transfer the two test scripts from the laptop (same `scp` pattern as Phase 3, targeting `vf-loadgen`'s IP instead):
```powershell
scp -i "$env:USERPROFILE\.ssh\hetzner-key" "...\perf\k6-score.js" root@204.168.142.84:/root/
scp -i "$env:USERPROFILE\.ssh\hetzner-key" "...\perf\locustfile.py" root@204.168.142.84:/root/
```

**Stage A — 3-minute validation run** (fail fast before committing to 30 minutes):
```bash
k6 run -e BASE_URL=http://2.29.1.199:8000 -e RATE_PER_SEC=167 -e DURATION=180s k6-score.js
```
Result: 30,994 requests, 0% failed, throughput ~9,786/min, p95 = 26.40ms. One non-fatal error appeared: `ERRO ... could not open 'perf/k6-summary.json': no such file or directory` — see "Gotcha" below.

**Gotcha — the k6 JSON-summary save error, and why it didn't invalidate the test:** the script's `handleSummary()` function writes the printed results a *second* time to a JSON file at the **relative path** `perf/k6-summary.json`. On the laptop, that path always existed because the whole project folder was present; on `vf-loadgen`, only the single script file was copied to `/root/`, so `perf/` didn't exist yet. The file-save step runs *after* the entire test has already completed and printed its real results — so the actual test data was never at risk, only a bonus artifact-save step failed. Fixed for the real run with:
```bash
mkdir -p perf
```

**Live capacity check during Stage A**, on `vf-demo` in parallel:
```bash
docker stats --no-stream      # containers: all under 5% CPU, ~1.5GB / 7.5GB RAM used
top -bn1 | head -15           # 97.8% idle system-wide during the short test
```
Verdict: enormous headroom, current API config (2 uvicorn workers) sufficient for the full 30-minute run.

**Stage B — the real 30-minute certificate**, run inside `screen` for resilience against SSH/network drops (the session had one earlier disconnect that killed an in-progress command — this specifically guards against that happening to a 30-minute test):
```bash
apt-get install -y screen
screen -S k6full
k6 run -e BASE_URL=http://2.29.1.199:8000 -e RATE_PER_SEC=167 -e DURATION=30m k6-score.js
# then Ctrl+A, D to detach — the test keeps running on the server independent of the SSH session
# reattach anytime with: screen -r k6full
```

**Why `screen` and not just `nohup` here:** `nohup` alone would have kept the process alive, but k6's live interactive progress bar only renders when attached to a real terminal (a "TTY"). `screen` creates a persistent virtual terminal on the server itself, so k6 still thinks it has a live TTY even after detaching — meaning the nice live progress bar is still there to reattach and see (and screenshot), which a plain `nohup`-redirected-to-a-file approach would have lost.

**Result — the official Wk15 throughput certificate:**
```
total requests   : 301,535
throughput       : 166.6 req/s  (~9,996/min — within 0.04% of the exact 10,000/min proposal target)
failed           : 0.00%
latency p95      : 56.69 ms   (proposal SLO: <200 ms — beaten by ~3.5x)
latency p99      : 98.45 ms
latency max      : 362.72 ms
```

**Capacity monitoring methodology used throughout the 30-minute run:** three independent, cross-checking sources were sampled at intervals (start, ~15 min, ~25 min):
1. `docker stats --no-stream` on `vf-demo` — shows only containerised services (Kafka/Postgres/Redis/etc.)
2. `top -bn1 | head -15` on `vf-demo` — shows the *native* processes too, critically including the two `uvicorn` API worker processes, which don't appear in `docker stats` since they run outside Docker
3. Hetzner's own **Graphs** tab (CPU/Disk/Network) on both servers — an independent, provider-generated view, not something either the deployment or Claude produced, so it's the strongest single piece of evidence. It showed a clean, sudden, sustained step-change in CPU/network exactly at the load-test start timestamp, and an equally clean drop the instant it ended — visually proving the load was real and matched the terminal timestamps precisely.

At peak, `vf-demo` ran at roughly **50-80% total CPU** (out of 4 vCPUs) with **~5GB RAM still free** — real, substantial load, with meaningful headroom still in reserve.

**Locust confirmation run** (closing the proposal's "k6 + Locust" pairing — a deliberate, separate second tool/methodology, not a duplicate of the k6 test):
```bash
source loadgen-env/bin/activate
locust -f locustfile.py --headless -u 100 -r 20 -t 3m --host http://2.29.1.199:8000 --csv=perf/locust_cloud
```
Result: 56,035 requests, 0% failures, avg 286ms, p95 = 420ms, throughput ~311.5 req/s (~18,690/min). Locust's concurrent-user model (100 simultaneous simulated users) is a deliberately different load shape from k6's fixed-arrival-rate model — together they stress the API in two genuinely different ways, which is the actual reason the proposal names both tools rather than just picking one.

### Phase 7 — Cleanup and final billing verification

Before deleting, the Hetzner Console's **Usage** tab (`console.hetzner.com/usage`) and its **"Generate preview"** itemized invoice were checked — both are read-only views, generating a preview costs nothing and commits to nothing:

```
Server cpx32 "vf-demo"      : 3h usage  -> $0.20
Server cpx22 "vf-loadgen"   : 2h usage  -> $0.07
IPv4 x2                     : negligible -> $0.00
TOTAL                       : $0.28  (~₹24)
```

**Confirms the billing model directly:** Hetzner Cloud bills a **flat hourly rate per server size**, not by CPU intensity — running the full 30-minute maximum-throughput certificate cost exactly the same per-hour rate as if the server had sat idle. The only usage-based line item (bandwidth beyond the 20TB/month included allowance) was never remotely approached.

Both servers deleted via the Hetzner console (**Delete** on each server's page, manual, deliberate). Confirmed via the Servers list returning to "You don't have any servers yet."

## 7. Key Lessons From This Deployment

1. **A "new terminal window" is not a guarantee of a fresh environment variable state on Windows** — PATH can be stale even after a full restart in unusual cases; the reliable fix is setting it directly via `[Environment]::SetEnvironmentVariable`, not just retrying restarts.
2. **Always check which machine a prompt belongs to before pasting a command.** `root@vf-demo:...#` (or `vf-loadgen`) means a Linux bash command; `PS C:\...>` means Windows PowerShell — bash syntax (`for f in ...; do ... done`) will hard-error in PowerShell and vice versa. One SSH disconnect mid-session led to exactly this mistake.
3. **Long-running commands over SSH need to be detached from the SSH session itself**, not just backgrounded — `screen` (preserves the interactive TTY, so live progress is still visible on reattach) or `nohup ... &` (simpler, but loses the interactive display) depending on whether you need to watch it live later.
4. **A short validation run before a long one is worth the extra few minutes** — it caught nothing wrong here, but it also gave a safe, cheap opportunity to check real capacity headroom (`docker stats`/`top`) before committing to the full 30-minute test.
5. **A relative file path in a script is an assumption about the working directory** — the k6 JSON-summary save error was entirely due to `perf/k6-summary.json` assuming a project-root working directory that only existed on the laptop, not on the minimal file transfer done to `vf-loadgen`.
6. **Cloud billing (on Hetzner, at least) is time-based, not usage-intensity-based** — running a server at 5% CPU or 90% CPU for one hour costs the same. The only variable cost lever is bandwidth beyond the included allowance, which a short test never approaches.
7. **A provider's own monitoring (Hetzner's Graphs tab) is stronger evidence than self-reported logs** — it's an independent, third-party-generated confirmation that the load actually happened, at the exact times the terminal output claims.
8. **Docker Desktop's Windows host-networking is not representative of production latency, and should never be used as a certified result.** Re-running the local k6 test (2026-09-02) against the API via `host.docker.internal` produced `p95≈2000ms` / `max≈49.7s` — a ~40x regression from the cloud-certified `p95=56.69ms` — regardless of API worker count (tested at both 1 and 4 workers, near-identical failure both times, ruling out worker count as the cause). This points squarely at the k6-container-to-Windows-host network path (WSL2/Hyper-V NAT under sustained concurrent load), a known Docker-Desktop-for-Windows limitation — the same class of issue `api.py`'s `SKIP_BLOCKLIST` comment already documents for Redis round-trips on this machine. **Decision: do not present this number as evidence of anything; the cloud run remains the sole authoritative Wk15 latency certificate.** Chasing a clean local number further was judged not worth the time once two different worker configurations both failed identically.

A local Locust re-run (native process, no Docker network hop, so immune to the issue above) confirmed **0% failures across 2,967 requests** — a genuinely valid stability result — but still showed `p95≈930ms`, ~15x slower than the cloud certificate. Root cause this time is different: this one Windows laptop was simultaneously running the full 6-container Docker stack, 4 API worker processes, and Locust itself, all sharing the same CPU cores — the cloud test avoided this entirely with two dedicated, purpose-built VMs. Same decision: the 0% failure rate is usable evidence, the latency number is not.

## 8. Final Results Summary

| Deliverable | Target (proposal) | Actual result | Status |
|---|---|---|---|
| Wk14 — deploy to cloud VM | Pipeline running on `vf-demo` | Full 6-container stack + API live on Hetzner CPX32; smoke-tested `/score` returned a real decision | ✅ |
| Wk15 — sustained 10K tx/min, 30 min, k6 | p95 < 200ms | 301,535 requests, 0% failed, p95 = 56.69ms, ~9,996 req/min | ✅ |
| Wk15 — Locust confirmation | k6 + Locust load report | 56,035 requests, 0% failed, p95 = 420ms, ~18,690 req/min | ✅ |
| Budget (₹800 ceiling, contingency-funded) | Minimal spend | **$0.28 (~₹24) total**, both servers, entire session | ✅ |
| Evidence | — | 20 screenshots + this command log, cross-corroborated by Hetzner's own Activities/Usage/Graphs pages | ✅ |
