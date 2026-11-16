# VelocityFraud Live Demo Console

A local control panel for the live demo. It runs each demo step on the Hetzner server with one click and streams the output into one screen.

## Start

Double-click **Start Demo Console.cmd**. The console opens at http://127.0.0.1:8765. Keep its black window open during the demo.

## First use after a snapshot restore

1. Open **Settings**, enter the new server IP, and press **Save**.
2. Press **Test connection**.
3. If the output mentions *REMOTE HOST IDENTIFICATION HAS CHANGED*, press **Forget old host key**, then **Test connection** again.

## Running order

| When | Step |
|---|---|
| Once, after creating the load server | Enter its IP in **Settings > Load server IPv4**, then run **P5 Load server setup** (2–4 minutes). |
| 10:15 and 10:45 | **P1 Readiness check**. Every line must read OK. |
| 10:45, after P1 | **P6 Load server readiness check** |
| Before 11:00 | Docker Desktop running with the **velocityfraud-dev** containers (vf-redis, vf-postgres, vf-kafka) on this laptop. Step **1.0** needs them. |
| 11:00, first click | **1.0** starts the 122 tests in the background (about 5 minutes); **5.8** shows the result in Act 5. |
| Before 10:30 | **P2 Secure tunnel**, then **P3 Power BI** |
| Optional | **P4 Groq connection check**. It makes 1–2 calls and stops itself. |
| 11:00 | Acts 1 to 5. Use **Run next**, or click any step. Groq runs live only in Act 3: **3.1** starts it, run **3.2** and then **3.3** straight away to stop it. If 3.3 is missed, Groq stops by itself after 3 minutes. **5.4** (k6) and **5.5** (Locust) each send load from the separate load server for 60 seconds; let each finish before the next step. |
| After the demo | Delete the load server in the Hetzner Console. |

## Safety rules built in

- Only the steps in `steps.py` can run. There is no free-text command box.
- Only one step runs at a time, and the buttons lock while it runs.
- These steps always ask before running:
  - steps that change services
  - steps that use Gemini or Groq quota
- These steps ask before a second run, because they create records:
  - 4.1 Appeal
  - 4.3 Feedback
- These steps refuse to start a duplicate:
  - Groq start
  - failover
  - standby restore
  - restarts
  - tunnel
  - Power BI
- The console listens on 127.0.0.1 only, and needs a per-launch token.
- Every run is appended to `logs/console-YYYY-MM-DD.log`. Send that file when asking for help with an error.

## Files

| File | Purpose |
|---|---|
| `server.py` | Local server: runs steps over SSH and serves the page |
| `steps.py` | The demo catalogue: every command, talking point and caution |
| `index.html` | The console screen |
| `settings.json`, `state.json` | Created at runtime: server IP and step marks |

Validate the catalogue at any time with `python server.py --selftest`. It runs `bash -n` on every remote script.
