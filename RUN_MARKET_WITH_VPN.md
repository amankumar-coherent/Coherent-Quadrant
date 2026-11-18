# How to run any market with the VPN switch

This guide shows how to run any market through the Coherent Quadrant pipeline
while the Proton VPN switches servers on its own, so Google's blocks do not stall
the run. The same steps work for every market and country; nothing is set up per
market.

For the whole pipeline see `CLAUDE.md`. For the full step reference see
`PIPELINE_CHATGPT_EXPAND.md`.

---

## 1. Why the VPN switch

Google blocks by IP address. When many browsers run on one IP, Google shows
"Sign in to continue", "Verifying your request" or a CAPTCHA, and the run slows
or stops. The VPN guard moves the PC to a new Proton VPN server:

- every `VPN_ROTATE_MIN` minutes (default 20), even with no blocks, and
- sooner when blocks build up: a block score reaches `VPN_SCORE_LIMIT`, or
  2 browsers hit a sign-in or verify wall within 3 minutes.

During a switch every pipeline browser pauses. The guard disconnects, connects
to the next country and checks that the IP really changed. The browsers then
resume on fresh profiles. The run does not need to be restarted.

---

## 2. One-time setup

### 2.1 Project

```bat
setup.bat
```

This creates `.venv`, installs `requirements.txt` (which includes `pywinauto`,
needed for the VPN switch) and the bundled Chromium, and creates `.env`. Fill in
`.env` as shown in `CLAUDE.md` section 3, at minimum:

```
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<key>
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
GOOGLE_AI_MODE_ENABLED=true
GOOGLE_AI_MODE_HEADLESS=false
GOOGLE_AI_MODE_QUERY_DELAY=10
```

Check the browser setup:

```bat
.venv\Scripts\python.exe -m vendor_intel.scraping.google_ai_mode doctor
```

It should list `Free AI ReCaptcha Solver by Raptor` under loaded extensions.

### 2.2 Proton VPN app

1. Install the Proton VPN app for Windows (a Plus plan, so all countries are
   available) at its default location,
   `C:\Program Files\Proton\VPN\`.
2. Sign in to the app.
3. In the app settings, turn the **Kill switch OFF**. With the kill switch on,
   the internet drops during a switch and the IP check fails.
4. Leave the app running. The guard clicks its window itself (Windows UI
   Automation), so it needs no Administrator rights. It must run in the
   **same Windows session** as the app (your normal logged-in desktop, not a
   remote service account).

### 2.3 Optional `.env` settings

The defaults suit most runs. Add any of these to `.env` to change them:

| Setting | Default | Meaning |
|---|---|---|
| `VPN_DIR` | `data/vpn` | Folder for the pause flag, switch state and block log. **Every project that runs at the same time on this PC must use the same folder** (for example the distributor-intelligence `data/vpn`), so one switch pauses all their browsers |
| `VPN_ROTATE_MIN` | 20 | Scheduled switch every N minutes (0 = off) |
| `VPN_SCORE_LIMIT` | 30 | Block score that triggers a switch (sign-in 3, verify 2, no answer 1, CAPTCHA 0.5, counted over the last 10 min) |
| `VPN_WALL_BROWSERS` | 2 | This many browsers on a sign-in / verify wall ... |
| `VPN_WALL_WINDOW_MIN` | 3 | ... within this many minutes switches at once |
| `VPN_RECENT_IP_HOURS` | 24 | An IP used in the last N hours is rejected; the guard tries another server |
| `VPN_PAUSE_WAIT_SEC` | 180 | How long a switch waits for browsers to close before closing them itself |

---

## 3. Run a market

You need two terminals, both opened in the project folder.

### Terminal 1: start the VPN guard

```bat
.venv\Scripts\python.exe scripts\vpn_guard.py
```

- If the VPN is not connected, the guard connects it first.
- Only one guard runs per PC. A second guard sees the first one and exits, so
  starting it again is safe.
- Leave this terminal open for the whole run. Its log is `logs\vpn_switch.log`.

### Terminal 2: run the market

One market:

```bat
.venv\Scripts\python.exe scripts\run_quadrant_pipeline.py --market "Global Smart Ring Market" --country global --keep 120 --slots 41-50
```

- `--market`: the market name. For a single country, leave out "Global", for
  example `--market "Smart Ring Market" --country india`.
- `--country`: `global` or a country name (`india`, `germany`, `japan`, ...).
- `--keep 120`: finish with 120 verified companies (20 on the chart + 100 in
  Other Noticeable Players).
- `--slots 41-50`: 10 browsers. Use fewer (for example `41-45`) on a slow PC.

Several markets at once (one browser per market):

```bat
.venv\Scripts\python.exe scripts\run_markets_parallel.py --markets-file queries\my_markets.txt --workers 10 --keep 120
```

`queries\my_markets.txt` holds one market per line, with an optional country:

```
Global Smart Ring Market
Smart Ring Market | india
Fire Insurance Market | mozambique
```

Every step saves its work. If a run stops, run the same command again and it
continues where it stopped.

The run ends with a **VERIFY** block. Every line must read `[PASS]`. The report
is in `output\chatgpt_expand\<market>_<country>\`.

---

## 4. Check the VPN while a run is going

```bat
.venv\Scripts\python.exe scripts\vpn_switch.py --status
```

Shows the current connection, IP and the last switches.

Switch by hand (pauses the browsers the same way the guard does):

```bat
.venv\Scripts\python.exe scripts\vpn_switch.py --switch
.venv\Scripts\python.exe scripts\vpn_switch.py --switch --country DE
```

Connect if not connected:

```bat
.venv\Scripts\python.exe scripts\vpn_switch.py --connect
```

Files to look at:

| File | What it shows |
|---|---|
| `logs\vpn_switch.log` | Every switch: pause, disconnect, new country, new IP, resume |
| `data\vpn\blocks.log` | Every Google block a browser hit (time, process, kind) |
| `data\vpn\state.json` | Switch count, countries and IPs used recently |
| `data\vpn\PAUSE` | Exists only while a switch is in progress |

Do not commit `data\vpn\`. It holds your IP history.

---

## 5. Running overnight

Start the guard first, then the market through the supervisor and watchdog
described in `CLAUDE.md` section 6 ("Running a market unattended"). The guard
handles IP blocks. The watchdog handles disk space and closes browsers stuck on
walls. The supervisor restarts a run that crashes or stalls.

---

## 6. Troubleshooting

| Problem | What to do |
|---|---|
| Browsers stay paused and never resume | A switch stopped half-way. Check `logs\vpn_switch.log`. If no switch is running, delete `data\vpn\PAUSE` (or the `PAUSE` file in your `VPN_DIR`) |
| Guard cannot find the Proton window | Open the Proton VPN app and sign in. Run the guard in the same desktop session as the app, not over a service or a different user |
| Switch fails with "IP did not change" or no internet | Turn the Kill switch OFF in Proton. Then run `vpn_switch.py --connect` |
| The guard exits with "another vpn_guard is already running" | Expected: one guard per PC. If none is actually running, close leftover Python windows and start it again |
| Still many blocks after switches | Lower the number of browsers (`--slots 41-45`, `--workers 5`) or raise `GOOGLE_AI_MODE_QUERY_DELAY` in `.env` (for example to 15) |
| Two projects running together pause at different times | Set the same `VPN_DIR` in both projects' `.env` |
| You want to run without the VPN | Do not start `vpn_guard.py`. The pipeline runs the same way, it just waits out blocks instead of switching |

---

## 7. Alternative: WireGuard configs instead of the Proton app

If you have WireGuard config files (`*.conf`, one per server) instead of the
Proton app, the built-in IP switch in `src\vendor_intel\scraping\ip_rotate.py`
can be used. Run this once from an **Administrator** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_vpn_switch.ps1 -Configs C:\path\to\wireguard_configs
```

Then add to `.env`:

```
GOOGLE_AI_MODE_WIREGUARD_CONFIGS=C:\path\to\wireguard_configs
```

The pipeline then moves to the next config when Google blocks it, with no guard
needed. Check it with:

```bat
.venv\Scripts\python.exe -m vendor_intel.scraping.ip_rotate status
```

Use either the Proton app guard or WireGuard, not both at once.
