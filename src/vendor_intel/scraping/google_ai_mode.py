"""Google AI Mode (``udm=50``) as a free, no-API-key generative backend.

Drives the generative tab of Google Search through a stealth-patched browser
and returns the rendered answer text. Used as the LLM backend for the
ChatGPT-expand discovery steps (recall / discover / extract / verify / fill).

Deliberately self-contained: the only non-stdlib import is ``patchright``,
so this file can be lifted into another project as-is.

Not a metered API — there is no token accounting, no temperature and no
system role. ``model``/``max_tokens``/``temperature`` are accepted by the
adapter functions and ignored, which is what makes it a drop-in swap.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

MAX_URL_CHARS = 7800  # Google 400s past ~8 KB of request line

_DEFAULT_DELAY = 10.0
_JITTER = 5.0

CAPTCHA_MARKERS = (
    "unusual traffic",
    "detected unusual traffic",
    "/sorry/index",
    "our systems have detected",
)

# Observed live: "You've reached the request limit for AI responses at the
# moment. Try again in a little while."
#
# This is a genuine per-IP quota on AI Mode answers, NOT a CAPTCHA and NOT a
# refusal. Clearing cookies or rebuilding the profile does nothing — the
# quota follows the IP — and rewording the prompt does nothing either. Only
# waiting helps, so it is classified as rate limiting and gets the long
# cool-off rather than an immediate retry.
QUOTA_MARKERS = (
    "reached the request limit for ai responses",
    "request limit for ai responses",
    "try again in a little while",
)

REFUSAL_MARKERS = (
    "no response available for this search",
    "try asking something else",
    "i can't help with that",
    "couldn't generate a response",
    # Observed live: AI Mode renders a normal page whose only content is
    # "Something went wrong, and an AI response wasn't generated." It is
    # neither a CAPTCHA nor a real answer, so without this marker the page
    # parses to zero companies and looks like a genuinely empty market.
    "something went wrong",
    "an ai response wasn't generated",
    "an ai response was not generated",
)

# Google's "no answer" error page, in any of its wordings. Unlike the generic
# refusal phrases above these never appear in a real answer, so they are
# matched anywhere on the page (the page text includes the echoed prompt).
NO_ANSWER_MARKERS = (
    "the content wasn't generated",
    "the content was not generated",
    "an ai response wasn't generated",
    "an ai response was not generated",
)

# A run that keeps hitting "something went wrong" on prompts that used to
# work is usually a soured session (stale cookies / a flagged profile)
# rather than a bad prompt. After this many consecutive soft failures the
# session is rebuilt: cookies cleared, browser relaunched.
_SOFT_FAILURES_BEFORE_RESET = 2

# Unsolved CAPTCHAs in one run before the profile is archived and rebuilt.
# Individual CAPTCHAs are normal on bundled Chromium; a sustained wall is a
# soured profile. Measured: a scoring pass hit 31 in a row and left 3 of every
# 4 companies unscored, because nothing escalated past "solve it in the
# browser window". Five is high enough not to fire on ordinary noise.
_CAPTCHAS_BEFORE_PROFILE_RESET = 5

# Consecutive "no AI response generated" pages before the WHOLE profile is
# archived and the browser reopened on a fresh one. At 2 the session is only
# rebuilt (cookies cleared, browser relaunched); if the pages keep coming
# after that, the profile itself is soured and needs the same treatment a
# quota page gets.
# Block pages (sign-in wall / "Verifying your request") that a reset did NOT clear
# before the session gives up: past this, Google has flagged the IP, not the profile.
_MAX_FLAGGED_BLOCKS = int(os.getenv("GOOGLE_AI_MODE_MAX_FLAGGED_BLOCKS") or "6")
_SOFT_FAILURES_BEFORE_PROFILE_RESET = 3

# Browser-death messages from patchright: the page/context/browser is gone,
# so retrying on it can never work -- the browser must be reopened.
_BROWSER_GONE_MARKERS = (
    "has been closed",
    "browser has disconnected",
    "target closed",
    "connection closed",
    "browser closed",
)


def _max_resets_per_query() -> int:
    """Profile resets one query may trigger (quota / no-answer / crash)
    before giving up on it. GOOGLE_AI_MODE_MAX_RESETS, default 3."""
    try:
        return max(0, int(_env("GOOGLE_AI_MODE_MAX_RESETS", "3") or 3))
    except ValueError:
        return 3


def _quota_cool_off(reset_number: int) -> float:
    """Seconds to wait on a fresh profile after the Nth quota reset of one
    query: base x N (120 s, 240 s, 360 s by default). A quota is partly tied
    to the soured profile (a fresh one often answers at once) and partly to
    the IP, which only time clears -- so each further reset waits longer.
    GOOGLE_AI_MODE_QUOTA_COOLOFF sets the base; default 0 (owner 2026-10-11:
    no cool-off, only reset the profile, browser and cookies)."""
    try:
        base = float(_env("GOOGLE_AI_MODE_QUOTA_COOLOFF", "0") or 0)
    except ValueError:
        base = 0.0
    return max(0.0, base) * max(1, reset_number)

# --- machine-wide back-off ---------------------------------------------------
#
# Google's "Try again later" block follows the IP, not the browser. With 10 browsers on one
# IP, each resetting its own profile and retrying a minute later, the machine kept hitting
# Google every few seconds and the block never lifted: overnight 2026-11-07, 100+ resets per
# browser and almost nothing saved in 30 minutes across 10 markets. So a block seen by ANY
# browser now pauses EVERY browser on the machine, through one shared file, and the pause
# doubles with each further block (60 s, 2, 4, 8, 16, 30 min) until Google answers again;
# one good answer anywhere clears it. OFF by default since 2026-11-15 (owner): it parked every
# window on about:blank; each browser now waits out its own CAPTCHA. GOOGLE_AI_MODE_IP_BACKOFF=60 turns it on.
_IP_BACKOFF_RESET_AFTER = 1800.0  # a block more than 30 min after the last starts over


def _ip_backoff_base() -> float:
    try:
        return max(0.0, float(os.getenv("GOOGLE_AI_MODE_IP_BACKOFF") or "0"))
    except ValueError:
        return 0.0


def _ip_backoff_max() -> float:
    try:
        return max(0.0, float(os.getenv("GOOGLE_AI_MODE_IP_BACKOFF_MAX") or "1800"))
    except ValueError:
        return 1800.0


def _ip_backoff_path() -> Path:
    override = (os.getenv("GOOGLE_AI_MODE_IP_BACKOFF_FILE") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "data" / "ai_mode_ip_backoff.json"


def _ip_backoff_read() -> dict:
    try:
        data = json.loads(_ip_backoff_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 -- missing, half-written, anything: no back-off
        return {}


def _ip_backoff_write(data: dict) -> None:
    path = _ip_backoff_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 -- another browser holds it; its write is as good
        pass


_IP_BACKOFF_PROBE = 300.0   # how long one browser's test search may take


def _ip_backoff_note_block() -> float:
    """Record a Google block; returns the pause (s) every browser now waits.

    Blocks while a pause is on do not raise the level again: ten browsers hitting
    the same block at once are one block, and counting them as ten sent the pause
    straight to its maximum (owner 2026-11-09)."""
    base = _ip_backoff_base()
    if base <= 0:
        return 0.0
    now = time.time()
    data = _ip_backoff_read()
    # Start over only when the last pause ended more than 30 min ago -- measured from
    # its END, or a 30-minute pause always "started over" at 1 minute.
    since_end = now - max(float(data.get("until") or 0), float(data.get("updated") or 0))
    level = int(data.get("level") or 0) if since_end < _IP_BACKOFF_RESET_AFTER else 0
    # Blocks that land while the pause is still on (queries already in flight when it
    # began) are the same block; a block on the test search AFTER the pause ended is a
    # new one and doubles the pause. A fixed 2-minute burst window kept the pause at
    # 1 minute forever, since every 1-minute pause ended inside it (owner 2026-11-09).
    new_block = not (level and now < float(data.get("until") or 0))
    if not new_block:
        # Same burst: the pause already set stands. Extending it here would also let
        # searches still in flight from an OLD IP stretch the short settle after a switch.
        return float(data.get("until") or 0) - now
    level += 1
    wait = min(_ip_backoff_max(), base * (2 ** min(level - 1, 10)))
    until = max(float(data.get("until") or 0), now + wait)
    _ip_backoff_write({"level": level, "until": until, "updated": now})
    # With a VPN configured (ip_rotate), a new block switches the machine to a fresh IP
    # instead of waiting it out: the pause above is written FIRST so every other browser
    # stops while the switch runs, then cut to a short settle once the new IP is up. One
    # browser then tests Google (the probe in _ip_backoff_wait); blocked again -> next IP.
    try:
        from vendor_intel.scraping import ip_rotate  # noqa: PLC0415
        if ip_rotate.enabled() and ip_rotate.rotate(reason=f"Google block (level {level})"):
            settle = _float_env_safe("GOOGLE_AI_MODE_ROTATE_SETTLE", 15.0)
            _ip_backoff_write({"level": 1, "until": time.time() + settle,
                               "updated": time.time()})
            return settle
    except Exception as err:  # noqa: BLE001 -- a failed switch must never stop the run
        print(f"  [ai-mode] IP switch failed: {err}", flush=True)
    return wait


def _float_env_safe(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def _captcha_wait() -> float:
    """Seconds a browser stays on a CAPTCHA / block page for it to be solved -- by
    captcha-raptor or by hand in the window -- before its cookies or profile are reset
    (owner 2026-11-14: "take time to solve captcha, do not close the browser instantly").
    GOOGLE_AI_MODE_CAPTCHA_WAIT, default 120; 0 = reset at once (the old behaviour)."""
    return max(0.0, _float_env_safe("GOOGLE_AI_MODE_CAPTCHA_WAIT", 120.0))


def _ip_backoff_note_ok() -> None:
    """Google answered: clear the shared pause (only written when one is set)."""
    if _ip_backoff_base() <= 0:
        return
    data = _ip_backoff_read()
    if data.get("level") or float(data.get("until") or 0) > time.time() or data.get("probe_until"):
        _ip_backoff_write({"level": 0, "until": 0, "updated": time.time()})


def _ip_backoff_active() -> bool:
    if _ip_backoff_base() <= 0:
        return False
    data = _ip_backoff_read()
    return bool(data.get("level")) and (float(data.get("until") or 0) > time.time()
                                        or float(data.get("probe_until") or 0) > time.time())


def _ip_backoff_wait() -> None:
    """Sleep while the machine-wide pause is set, then let ONE browser test Google.

    When the pause ends, the first browser to get here claims the test search
    (probe_until); every other browser keeps waiting until that search either
    answers (note_ok clears the pause, all resume) or is blocked (note_block sets a
    new pause). Before, all ten searched at once, all ten were blocked and the pause
    jumped back to 30 minutes (owner 2026-11-09)."""
    if _ip_backoff_base() <= 0:
        return
    told = False
    me = f"{os.getpid()}-{threading.get_ident()}"
    while True:
        data = _ip_backoff_read()
        now = time.time()
        left = float(data.get("until") or 0) - now
        if left > 0:
            if not told:
                print(f"  [ai-mode] Google is blocking this machine: every browser pauses "
                      f"{left / 60:.0f} min before the next query", flush=True)
                told = True
            time.sleep(min(left, 30.0))
            continue
        if not data.get("level"):
            return                      # no pause (or a good answer cleared it)
        probe_until = float(data.get("probe_until") or 0)
        if probe_until > now and data.get("probe_by") != me:
            time.sleep(15.0)            # another browser is testing Google
            continue
        if data.get("probe_by") != me or probe_until <= now:
            _ip_backoff_write({**data, "probe_until": now + _IP_BACKOFF_PROBE, "probe_by": me})
            time.sleep(1.0)
            if _ip_backoff_read().get("probe_by") != me:
                continue                # another browser claimed it first
            print("  [ai-mode] pause over: this browser tests Google first, the others wait",
                  flush=True)
        return


def _sorry_cool_off(reset_number: int) -> float:
    """Seconds to wait on a fresh profile after Google's /sorry/ block.
    GOOGLE_AI_MODE_SORRY_COOLOFF (default 60) x the reset number: the block is
    tied to the IP, so a fresh profile only helps once the IP has rested."""
    try:
        base = float(os.getenv("GOOGLE_AI_MODE_SORRY_COOLOFF") or "60")
    except ValueError:
        base = 60.0
    return max(0.0, base) * max(1, reset_number)


_READY_MARKER = "ai mode response is ready"


# --- Proton VPN server switching (scripts/vpn_switch.py, scripts/vpn_guard.py) ---
# Owner 2026-11-17, ported from distributor-intelligence (PROTON_VPN_AUTO_SWITCH.md).
# One guard per PC drives the Proton VPN app; these hooks make every browser
# take part. Shared folder VPN_DIR (default data/vpn; set it to the other
# project's folder when both run, the VPN is machine-wide):
#   PAUSE      -- a switch is in progress: close this browser and wait;
#   state.json -- "switches" = number of completed switches: a browser last used
#                 under an older number starts on a fresh profile (new IP, new visitor);
#   blocks.log -- one line per Google block, which the guard scores to decide a switch.
# With no guard running none of these files change, so nothing here does anything.
def _vpn_dir() -> Path:
    # VPN_DIR usually lives only in .env, which not every pipeline step loads; read it from there, or the
    # blocks / PAUSE go to a folder the guard does not watch (owner 2026-11-18: no switch for 7 hours).
    if not os.getenv("VPN_DIR"):
        try:
            from dotenv import dotenv_values  # noqa: PLC0415
            val = dotenv_values(Path(__file__).resolve().parents[3] / ".env").get("VPN_DIR")
            if val:
                os.environ["VPN_DIR"] = val
        except Exception:  # noqa: BLE001
            pass
    return Path(os.getenv("VPN_DIR") or (Path(__file__).resolve().parents[3] / "data" / "vpn"))


def vpn_report_block(kind: str) -> None:
    """One line per Google block for vpn_guard: signin, verify, captcha, no_answer."""
    try:
        d = _vpn_dir()
        d.mkdir(parents=True, exist_ok=True)
        with (d / "blocks.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.0f} {os.getpid()} {kind}\n")
    except Exception:  # noqa: BLE001 -- reporting must never break a query
        pass


def _vpn_generation() -> int:
    try:
        return int(json.loads((_vpn_dir() / "state.json").read_text(encoding="utf-8")).get("switches", 0))
    except Exception:  # noqa: BLE001
        return -1


_VPN_PAUSE_MAX = 900.0  # a crashed guard's PAUSE file must not freeze the run forever


class AiModeCaptcha(RuntimeError):
    """Google served /sorry/ — rate limited. Waiting helps."""


class AiModeRefusal(RuntimeError):
    """The model declined to answer. Retrying now with a reworded prompt helps;
    waiting does not."""


class AiModeUnavailable(RuntimeError):
    """Backend disabled, patchright missing, or an empty answer for no
    identifiable reason."""


# --- configuration ---------------------------------------------------------


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Master switch — ON by default: the discovery steps always run on AI
    Mode, with no API fallback.

    Tests force it off via the autouse fixture in tests/conftest.py, so a
    missed mock fails on an assertion instead of driving a real browser.
    """
    return _env_bool("GOOGLE_AI_MODE_ENABLED", True)


def _profile_dir() -> str:
    return _env("GOOGLE_AI_MODE_PROFILE_DIR", "data/ai_mode_chrome_profile")


# --- CAPTCHA-solver extensions ---------------------------------------------
#
# An extension only helps when Google renders a *solvable* reCAPTCHA widget.
# captcha-raptor injects only into */recaptcha/* URLs, so on the /sorry/ page
# reporting "Cannot contact reCAPTCHA" no widget loads and there is nothing to
# match. That block is prevented by pacing, never solved by an extension.

# Chrome's own component extensions always run, so a bare service-worker
# count is never zero and cannot prove our extension loaded.
_COMPONENT_EXTENSION_IDS = frozenset(
    {
        "mhjfbmdgcfjbbpaeojofohoefgiehjai",  # Chrome PDF Viewer
        "nkeimhogjdpnpccoofpliimaahmaaome",  # Google Hangouts
        "fignfifoniblkonapihmkfakmlgkbkcf",  # Google Network Speech
    }
)

# Repo layouts that keep manifest.json in a subfolder. Staging a copy under
# one of these names would collide with the next repo using the same layout,
# so the parent directory name is used instead.
_GENERIC_DIR_NAMES = frozenset(
    {"extension", "extensions", "src", "public", "dist", "build"}
)


def unpacked_extension_id(path: str) -> str:
    """Chrome's ID for an unpacked extension: SHA-256 of the absolute path,
    first 16 bytes, each nibble mapped ``0-f -> a-p``.

    Path-dependent, so it changes if the staged folder moves — always derive
    it rather than comparing against a hardcoded literal. Windows hashes the
    path as UTF-16LE with the drive letter uppercased.
    """
    raw = str(Path(path).resolve())
    if os.name == "nt":
        if len(raw) > 1 and raw[1] == ":":
            raw = raw[0].upper() + raw[1:]
        digest = hashlib.sha256(raw.encode("utf-16-le")).hexdigest()
    else:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return "".join(chr(ord("a") + int(c, 16)) for c in digest[:32])


def managed_chrome_blocks_extensions() -> bool:
    """True when enterprise policy makes Chrome silently ignore
    ``--load-extension``.

    Measured on Chrome 152: with any ``ExtensionInstall*`` policy present,
    real Chrome refuses sideloaded unpacked extensions while bundled
    Chromium honours the flag.
    """
    if os.name != "nt":
        return False
    try:
        import winreg  # noqa: PLC0415
    except ImportError:  # pragma: no cover - non-Windows
        return False
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"SOFTWARE\Policies\Google\Chrome") as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    if winreg.EnumKey(key, i).startswith("ExtensionInstall"):
                        return True
                for i in range(winreg.QueryInfoKey(key)[1]):
                    if winreg.EnumValue(key, i)[0].startswith("ExtensionInstall"):
                        return True
        except OSError:
            continue
    return False


def resolve_channel(extensions: list[str]) -> str | None:
    """Chromium (``None``) when extensions are wanted and managed Chrome would
    ignore them, else real Chrome.

    This is a deliberate trade-off: Chromium is CAPTCHA'd noticeably more
    often than real Chrome, so it is only chosen when extensions require it.
    """
    requested = _env("GOOGLE_AI_MODE_BROWSER", "chrome").lower()
    if requested == "chromium":
        return None
    # Real Chrome silently ignores --load-extension under enterprise policy,
    # and the registry probe can miss setups it does not know about. When an
    # extension is genuinely wanted, Chromium is the only build that honours
    # the flag, so prefer it whenever extensions are configured.
    if extensions and (
        managed_chrome_blocks_extensions()
        or _env_bool("GOOGLE_AI_MODE_FORCE_CHROMIUM", True)
    ):
        return None
    return requested or "chrome"


def _kill_orphan_browsers(profile_dir: str) -> int:
    """Kill browser processes still holding `profile_dir`, return how many.

    Playwright's close() is not always enough — a crashed or force-killed run
    leaves a Chromium holding the profile lock. The next launch then fails
    with "Opening in existing browser session", which took a whole market to
    0 companies in 0 minutes because every AI Mode call errored.

    Best effort by design: failing to kill a stray browser must never stop a
    run, so every error is swallowed.
    """
    marker = str(Path(profile_dir).name)
    if not marker:
        return 0
    killed = 0
    try:
        import subprocess

        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or "
                "Name='msedge.exe'\" | Where-Object { $_.CommandLine -like "
                f"'*{marker}*' }} | Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True, text=True, timeout=30,
        )
        for line in (out.stdout or "").split():
            if line.strip().isdigit():
                subprocess.run(
                    ["taskkill", "/F", "/PID", line.strip()],
                    capture_output=True, timeout=15,
                )
                killed += 1
    except Exception:  # noqa: BLE001
        return killed
    if killed:
        print(f"  [ai-mode] killed {killed} orphaned browser process(es)", flush=True)
        time.sleep(3)  # let Windows release the file handles
    return killed


def profile_dir_for(channel: str | None) -> str:
    """Chromium needs its own profile — Chrome and Chromium have incompatible
    profile state and cookie encryption, so sharing one corrupts it."""
    base = _profile_dir()
    return base if channel else f"{base}_chromium"


def staging_root(profile_dir: str) -> Path:
    """Sibling of the profile, never a child: inside, a profile reset would
    have to move the extensions out and back, and Chrome/Chromium profiles
    cannot share the directory."""
    base = Path(profile_dir)
    return base.parent / f"{base.name}_extensions"


def install_extension(source: str, profile_dir: str = "") -> bool:
    """Copy an unpacked extension next to the profile so it persists.

    ``--load-extension`` is a command-line-only load that Chrome never
    records in the profile, so it vanishes on any profile rebuild. Copying
    (rather than referencing a download folder) means the original can be
    moved or deleted without breaking the automation profile.
    """
    src = Path(source.strip().strip('"'))
    if not (src / "manifest.json").is_file():
        nested = src / "extension"  # captcha-raptor's layout
        if not (nested / "manifest.json").is_file():
            print(
                f"  [ai-mode] no manifest.json in {src} or {src / 'extension'} — "
                "point at the folder CONTAINING manifest.json",
                flush=True,
            )
            return False
        src = nested

    name = src.name
    if name.lower() in _GENERIC_DIR_NAMES:
        name = src.parent.name or name

    dest = staging_root(profile_dir or _profile_dir()) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)
    print(f"  [ai-mode] installed extension: {dest}", flush=True)
    return True


def bundled_extensions_root() -> Path:
    """``extensions/`` at the repo root — unpacked extensions shipped WITH the
    codebase (captcha-raptor), so a fresh clone loads them with no setup."""
    return Path(__file__).resolve().parents[3] / "extensions"


def _bundled_extensions() -> list[Path]:
    """Every ``extensions/<name>/`` (or ``extensions/<name>/extension/``) that
    holds a manifest.json. Off with GOOGLE_AI_MODE_BUNDLED_EXTENSIONS=false."""
    if not _env_bool("GOOGLE_AI_MODE_BUNDLED_EXTENSIONS", True):
        return []
    root = bundled_extensions_root()
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        for cand in (child, child / "extension"):
            if (cand / "manifest.json").is_file():
                found.append(cand)
                break
    return found


def _manifest_name(path: str | Path) -> str:
    try:
        return str(json.loads((Path(path) / "manifest.json").read_text(encoding="utf-8"))
                   .get("name") or "").strip().lower()
    except Exception:  # noqa: BLE001
        return ""


def installed_extensions(profile_dir: str = "") -> list[str]:
    """Staged extensions, the ones bundled in the repo's ``extensions/``
    folder, plus any explicitly listed in ``GOOGLE_AI_MODE_EXTENSIONS``
    (``;``-separated). The same extension (by manifest name) loads once."""
    paths: list[str] = []
    root = staging_root(profile_dir or _profile_dir())
    if root.is_dir():
        paths += [
            str(child.resolve())
            for child in sorted(root.iterdir())
            if (child / "manifest.json").is_file()
        ]
    loaded = {_manifest_name(p) for p in paths}
    for cand in _bundled_extensions():
        name = _manifest_name(cand)
        if name and name in loaded:
            continue  # already staged next to the profile — don't load twice
        paths.append(str(cand.resolve()))
        loaded.add(name)
    for raw in _env("GOOGLE_AI_MODE_EXTENSIONS").split(";"):
        candidate = Path(raw.strip().strip('"'))
        if not raw.strip():
            continue
        if not (candidate / "manifest.json").is_file():
            nested = candidate / "extension"
            if (nested / "manifest.json").is_file():
                candidate = nested
            else:
                print(
                    f"  [ai-mode] skipping {candidate} — no manifest.json",
                    flush=True,
                )
                continue
        resolved = str(candidate.resolve())
        if resolved not in paths:
            paths.append(resolved)
    return paths


def _proxy_for(profile: str) -> str:
    """GOOGLE_AI_MODE_PROXY: one proxy for every browser, or a comma list shared out by
    the slot number in the profile path (slot 41 -> list[41 % n]), so several proxies give
    the browsers several IPs. Empty = direct connection."""
    proxies = [p.strip() for p in (_env("GOOGLE_AI_MODE_PROXY") or "").split(",") if p.strip()]
    if not proxies:
        return ""
    m = re.search(r"ai_mode_batch_(\d+)", profile or "")
    return proxies[(int(m.group(1)) if m else 0) % len(proxies)]


def _query_delay() -> float:
    try:
        return float(_env("GOOGLE_AI_MODE_QUERY_DELAY", "10") or 10)
    except ValueError:
        return _DEFAULT_DELAY


def _mark_profile_exited_cleanly(profile: Path) -> None:
    """Clear Chromium's crash flag so a relaunch shows no "Restore pages?" bubble, and
    drop the saved startup tabs. Best-effort: an unreadable Preferences file is left alone."""
    prefs = Path(profile) / "Default" / "Preferences"
    if not prefs.is_file():
        return
    try:
        data = json.loads(prefs.read_text(encoding="utf-8", errors="replace"))
        prof = data.setdefault("profile", {})
        prof["exit_type"] = "Normal"
        prof["exited_cleanly"] = True
        session = data.setdefault("session", {})
        session["restore_on_startup"] = 5      # open the New Tab Page, never the old tabs
        session["startup_urls"] = []
        prefs.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError, AttributeError):
        return


def build_url(prompt: str) -> str:
    """AI Mode search URL. Truncates loudly rather than letting Google 400."""
    text = prompt.strip()
    url = (
        "https://www.google.com/search"
        f"?q={urllib.parse.quote_plus(text)}&udm=50&hl=en"
    )
    if len(url) <= MAX_URL_CHARS:
        return url
    # Binary-search the longest prefix that fits once percent-encoded.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        trial = (
            "https://www.google.com/search"
            f"?q={urllib.parse.quote_plus(text[:mid])}&udm=50&hl=en"
        )
        if len(trial) <= MAX_URL_CHARS:
            lo = mid
        else:
            hi = mid - 1
    print(
        f"  [ai-mode] WARNING prompt truncated {len(text)} -> {lo} chars "
        f"to stay under the {MAX_URL_CHARS}-char URL limit",
        flush=True,
    )
    return (
        "https://www.google.com/search"
        f"?q={urllib.parse.quote_plus(text[:lo])}&udm=50&hl=en"
    )


# --- browser session (one per process, reused) ------------------------------

_EXTRACT_JS = """
() => {
  const main = document.querySelector('main') || document.body;
  const links = Array.from(main.querySelectorAll('a[href^="http"]'))
    .filter(a => !(a.getAttribute('href') || '').includes('google.com'));
  const originals = links.map(a => a.textContent);
  for (const a of links) {
    a.textContent = `${a.textContent.trim()} (${a.getAttribute('href')})`;
  }
  const hidden = main.querySelectorAll('script, style');
  const display = Array.from(hidden).map(el => el.style.display);
  hidden.forEach(el => { el.style.display = 'none'; });
  const text = main.innerText || '';
  hidden.forEach((el, i) => { el.style.display = display[i]; });
  links.forEach((a, i) => { a.textContent = originals[i]; });
  return text;
}
"""


class AiModeSession:
    """One warm browser, one query at a time.

    Launch costs seconds and a cold profile draws CAPTCHAs, so the context is
    created once and reused for the whole run.
    """

    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._page = None
        self._lock = threading.Lock()
        self._last_query_at = 0.0
        self.captcha_count = 0
        self.last_captcha_at = 0.0  # a solve does NOT clear this
        self.extensions: list[str] = []
        self.channel: str | None = None
        # Consecutive "no AI response generated" pages. A good answer resets
        # it; crossing _SOFT_FAILURES_BEFORE_RESET rebuilds the session.
        self.soft_failures = 0
        # Consecutive block pages (sign-in wall / "Verifying your request") that a
        # session or profile reset did NOT clear. A good answer resets it. When Google
        # has flagged the IP rather than the profile, every fresh profile is blocked
        # too, so resetting cannot help and the session must stop instead of churning
        # (owner 2026-10-29, Japan Fashion E-Commerce: 183 sign-in walls, 371 CAPTCHAs
        # and 3 usable answers in 47 minutes, looping to "reset #44", while every
        # archived profile ate disk).
        self.flagged_blocks = 0
        self.resets = 0
        # AI-response quota pages ("reached the request limit"). Tracked
        # separately from CAPTCHAs because the remedy differs: a CAPTCHA can
        # be solved, a quota can only be waited out.
        self.quota_hits = 0

    # -- lifecycle --

    def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        try:
            from patchright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as err:  # pragma: no cover - env dependent
            raise AiModeUnavailable(
                "patchright is not installed — `pip install patchright`. "
                "Plain playwright is NOT a substitute: it gets an instant CAPTCHA."
            ) from err

        headless = _env_bool("GOOGLE_AI_MODE_HEADLESS", False)
        self.extensions = installed_extensions()
        self.channel = resolve_channel(self.extensions)
        profile = profile_dir_for(self.channel)

        # No "Restore pages?" bubble (owner 2026-11-15, screenshot): a killed browser leaves
        # exit_type="Crashed" in Preferences and the bubble sat on every relaunched window.
        # Same fix as the distributor-intelligence pipeline: mark the profile clean, and
        # never offer or replay a previous session.
        _mark_profile_exited_cleanly(Path(profile))
        args = [
            "--profile-directory=Default",
            "--hide-crash-restore-bubble",
            "--disable-session-crashed-bubble",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=InfiniteSessionRestore",
        ]
        if self.extensions:
            # One comma-joined flag, not one flag per path.
            args.append("--load-extension=" + ",".join(self.extensions))
            # Deliberately NOT --disable-extensions-except: it disables every
            # extension the profile installed itself, which makes
            # chrome://extensions look empty and "Load unpacked" appear broken.
            if self.channel is None and _env("GOOGLE_AI_MODE_BROWSER", "chrome").lower() != "chromium":
                print(
                    "  [ai-mode] managed Chrome ignores --load-extension — "
                    "using bundled Chromium so the extension loads "
                    "(expect more CAPTCHAs than real Chrome)",
                    flush=True,
                )

        self._pw = sync_playwright().start()
        launch: dict[str, Any] = {
            "user_data_dir": profile,
            # MV3 service workers are unreliable headless, and a CAPTCHA can
            # only be solved in a visible window.
            "headless": headless,
            "viewport": {"width": 1280, "height": 900},
            "args": args,
        }
        if self.channel:
            launch["channel"] = self.channel
        proxy = _proxy_for(profile)
        if proxy:
            # Search from another IP (e.g. a local SOCKS5 proxy in front of a VPN server)
            # when Google blocks the machine's own address.
            launch["proxy"] = {"server": proxy}
            print(f"  [ai-mode] searching through proxy {proxy}", flush=True)
        try:
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**launch)
            except Exception as err:  # noqa: BLE001
                # "Opening in existing browser session" = a browser from a killed
                # run still holds the profile lock; "Target ... has been closed" =
                # the new browser died at start-up (same cause, or a damaged
                # profile). Retrying without clearing it fails every time, so
                # the market ends at 0 companies. Clear the lock and launch once more.
                msg = str(err).lower()
                if "existing browser session" not in msg and "has been closed" not in msg:
                    raise
                print(
                    "  [ai-mode] browser could not start on this profile "
                    "(locked or closed at start-up) — clearing it and retrying",
                    flush=True,
                )
                _kill_orphan_browsers(profile)
                self._ctx = self._pw.chromium.launch_persistent_context(**launch)
        except BaseException:
            # A failed launch must not leave Playwright running: the next
            # sync_playwright().start() then fails with "Sync API inside the
            # asyncio loop" on every later query (owner 2026-10-14: a whole
            # market scored 0 of 117 companies in two hours this way).
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = self._ctx = self._page = None
            raise
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._close_extra_tabs()
        print(
            f"  [ai-mode] browser ready ({self.channel or 'chromium'}, "
            f"headless={headless}, profile={profile})",
            flush=True,
        )
        if self.extensions:
            self.verify_extensions()

    def _close_extra_tabs(self) -> None:
        """One tab per browser. A relaunched profile can restore its old tabs, and an
        extension can open its own; those stay open, keep loading Google pages and
        draw extra CAPTCHAs (owner 2026-10-14: "in one browser many tabs open")."""
        for page in list(getattr(self._ctx, "pages", None) or []):
            if page is self._page:
                continue
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    # -- extension verification (ground truth, not a worker count) --

    def our_workers(self) -> list[str]:
        """Worker/background URLs belonging to OUR extensions, by derived ID."""
        want = {unpacked_extension_id(p) for p in self.extensions} - {""}
        urls = [w.url for w in (self._ctx.service_workers or [])]
        urls += [p.url for p in (getattr(self._ctx, "background_pages", None) or [])]
        return [
            u
            for u in urls
            if any(i in u for i in want)
            and not any(c in u for c in _COMPONENT_EXTENSION_IDS)
        ]

    def verify_extensions(self, *, timeout: float = 8.0) -> bool:
        """Confirm the extension actually loaded, read from Chrome itself.

        A bare ``len(service_workers)`` is a false positive — Chrome's own
        component extensions always run, and one of them (network speech) was
        once reported as proof a never-loaded extension was "active".
        """
        listed: list[str] = []
        page = None
        try:
            page = self._ctx.new_page()
            page.goto(
                "chrome://extensions-internals/", wait_until="load", timeout=20_000
            )
            entries = json.loads(page.inner_text("body"))
            listed = [
                f"{e.get('name')} [{e.get('location')}]"
                for e in entries
                if e.get("location") != "COMPONENT"
            ]
        except Exception as err:  # noqa: BLE001
            print(f"  [ai-mode] could not read extensions-internals: {err}", flush=True)
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

        # MV3 workers register lazily — a 2 s check produces false negatives.
        deadline = time.monotonic() + timeout
        workers: list[str] = []
        while time.monotonic() < deadline:
            workers = self.our_workers()
            if workers:
                break
            self._page.wait_for_timeout(500)

        if listed or workers:
            print(
                f"  [ai-mode] extensions loaded: {listed or '(none listed)'} "
                f"| our workers: {len(workers)}",
                flush=True,
            )
            return True
        print(
            "  [ai-mode] WARNING extension is genuinely NOT installed "
            f"(derived ids: {[unpacked_extension_id(p) for p in self.extensions]}). "
            "Note an extension cannot clear 'Cannot contact reCAPTCHA' anyway — "
            "pacing prevents that block.",
            flush=True,
        )
        return False

    # -- Proton VPN switching --

    def _vpn_hooks(self) -> None:
        """Before every query: wait out a VPN server switch with the browser closed,
        then start on a fresh profile once per completed switch."""
        pause = _vpn_dir() / "PAUSE"
        if pause.exists():
            print("  [ai-mode] VPN server switch in progress -- closing this browser and waiting", flush=True)
            self.close()
            start = time.monotonic()
            while pause.exists() and time.monotonic() - start < _VPN_PAUSE_MAX:
                time.sleep(5)
            print("  [ai-mode] VPN switch finished -- resuming", flush=True)
        gen = _vpn_generation()
        if gen < 0:
            return
        profile = Path(profile_dir_for(self.channel))
        marker = profile / ".vpn_gen"
        try:
            seen = int(marker.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            seen = None
        if seen == gen:
            return
        # A profile used before this switch (or before the VPN was tracked) is the old
        # visitor on the old IP: start clean. A planned rotation, not a failure.
        if seen is not None or (profile / "Default").exists():
            self.reset_profile(reason=f"vpn{gen}")
            self.resets = max(0, self.resets - 1)
            self.flagged_blocks = 0
        try:
            profile.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(gen), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        for closer in (
            getattr(self._ctx, "close", None),
            getattr(self._pw, "stop", None),
        ):
            if closer:
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass
        self._pw = self._ctx = self._page = None

    # -- pacing --

    def _pace(self) -> None:
        target = _query_delay() + random.uniform(0, _JITTER)
        elapsed = time.monotonic() - self._last_query_at
        if self._last_query_at and elapsed < target:
            time.sleep(target - elapsed)

    # -- answer waiting --

    def _wait_for_answer(self, timeout: float = 90.0) -> None:
        """Completion signal: ready-marker, else text that stops growing.

        Never gate on answer length — doing so made every short answer spin
        for the full timeout (~94 s instead of ~5 s).
        """
        page = self._page
        deadline = time.monotonic() + timeout
        last = -1
        stable = 0
        while time.monotonic() < deadline:
            try:
                if _READY_MARKER in (page.inner_text("body") or "").lower():
                    return
            except Exception:  # noqa: BLE001
                pass
            try:
                n = len((page.locator("main").first.inner_text(timeout=1000) or "").strip())
            except Exception:  # noqa: BLE001
                n = 0
            stable = stable + 1 if n > 0 and n == last else 0
            if stable >= 2:
                return
            last = n
            page.wait_for_timeout(1500)

    def _flagged_page_showing(self) -> str:
        """The name of the block page Google is showing, or "" for a normal page.

        Neither of these is a reCAPTCHA, so the solver does nothing with them and the
        session is treated as flagged: cookies cleared and the browser relaunched,
        then a full profile reset.

        * "Verifying your request ... Continue" -- seen when many browsers share one IP.
        * "Sign in to continue / Sign in to verify you're a human and see more results."
          -- Google's sign-in wall (owner 2026-10-29, Japan Fashion E-Commerce). A
          signed-out scraping profile can never satisfy it, so without this the query
          just returned the wall's text and the run stalled on it.
        """
        try:
            body = (self._page.inner_text("body", timeout=3000) or "").lower()
        except Exception:  # noqa: BLE001
            return ""
        if "verifying your request" in body:
            return "Verifying your request"
        if "sign in to verify" in body:
            return "Sign in to verify you're a human"
        # "Sign in to continue" alone also appears inside ordinary results, so only a
        # page that is nothing BUT the wall counts.
        if "sign in to continue" in body and len(body.strip()) < 400:
            return "Sign in to continue"
        return ""

    def _fresh_before_giving_up(self, *, new_profile: bool = False) -> None:
        """This query is out of resets: leave a FRESH browser for the next one.

        Raising used to leave the browser parked on the block page with the soured
        profile, so the step's next query (or its retry) started in the same blocked
        session (owner 2026-11-07: a blocked or unsolved browser must always be reset
        and reopened automatically). No cool-off here: the next query's own pacing and
        the step's retry spacing already wait."""
        try:
            # A new profile only after a usage-limit page, which is partly tied to the
            # profile; a block page keeps the warm profile (owner 2026-11-15).
            if new_profile:
                self.reset_profile(reason="quota")
            else:
                self.reopen_browser(reason="giving up on this query")
            self.captcha_count = 0
        except Exception:  # noqa: BLE001 -- giving up must never fail differently
            pass

    def _sorry_is_hard_block(self) -> bool:
        """True when the /sorry/ page is Google's "Try again later" block, which
        no solver can clear (owner's screenshot 2026-11-06), as opposed to a
        solvable image-grid reCAPTCHA."""
        try:
            body = (self._page.inner_text("body", timeout=3000) or "").lower()
        except Exception:  # noqa: BLE001
            return False
        return "try again later" in body

    def _wait_for_captcha_clear(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(2000)
            if "/sorry/" not in (self._page.url or ""):
                return True  # solved -> caller MUST re-issue the query
        return False

    def _wait_for_block_page_clear(self, what: str, timeout: float) -> bool:
        """Keep the browser OPEN on a block page for up to ``timeout`` seconds so the
        CAPTCHA can be solved (captcha-raptor, or by hand in the window), instead of
        clearing cookies at once. A "Continue" button (the "Verifying your request"
        interstitial) is pressed once, as a person would. True = the page cleared and
        the caller re-issues the query on the same session."""
        if timeout <= 0:
            return False
        print(f"  [ai-mode] {what} -- waiting up to {int(timeout)} s for it to be solved "
              "before resetting the browser", flush=True)
        pressed = False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if not pressed:
                    btn = self._page.get_by_role("button", name="Continue")
                    if btn.count():
                        btn.first.click(timeout=3000)
                        pressed = True
                self._page.wait_for_timeout(3000)
                if "/sorry/" not in (self._page.url or "") and not self._flagged_page_showing():
                    print(f"  [ai-mode] {what} cleared -- re-issuing the query", flush=True)
                    return True
            except Exception as err:  # noqa: BLE001
                if any(m in str(err).lower() for m in _BROWSER_GONE_MARKERS):
                    return False  # window closed: the reset path reopens it
                time.sleep(2)
        return False

    # -- the one public call --

    def ask(self, prompt: str, *, retries: int = 2, captcha_rounds: int = 2) -> str:
        """Send one prompt, return the rendered answer text.

        CAPTCHA rounds get their own allowance so a solve does not consume the
        retry budget.
        """
        with self._lock:
            self._ensure_browser()
            url = build_url(prompt)
            attempts_left = max(1, retries)
            captcha_left = max(0, captcha_rounds)
            # Automatic recoveries (profile reset / browser reopen) this ONE
            # query may use. Like CAPTCHA solves, a recovery does not cost a
            # retry: the retry after it runs on a fresh browser.
            resets_left = _max_resets_per_query()
            quota_resets = 0
            sorry_resets = 0  # fresh profiles after a /sorry/ block, this query
            verify_left = 3  # "Verifying your request" interstitials cleared per query
            noanswer_left = 3  # "content wasn't generated" pages recovered per query

            while attempts_left > 0:
                attempts_left -= 1
                self._vpn_hooks()
                self._pace()
                # The browser stays OPEN through a machine-wide pause (owner 2026-11-15: "do not
                # close the browser instantly"); closing every window on each pause left the
                # run looking dead and threw away a session that was still usable. The
                # window says why it waits -- a bare about:blank looked like a hang.
                if _ip_backoff_active():
                    self._show_pause_page()
                _ip_backoff_wait()
                try:
                    self._ensure_browser()
                    self._close_extra_tabs()
                    self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                except Exception as err:  # noqa: BLE001
                    msg = str(err).lower()
                    # AI Mode client-side-redirects (&sei=) right after load,
                    # which can interrupt the navigation wait. Benign.
                    if "interrupted by another navigation" not in msg:
                        self._last_query_at = time.monotonic()
                        # The browser crashed or was closed: retrying on the
                        # dead page can never work, so reopen it first.
                        if any(m in msg for m in _BROWSER_GONE_MARKERS) and resets_left > 0:
                            resets_left -= 1
                            self.reopen_browser(reason="browser closed/crashed")
                            attempts_left += 1
                            continue
                        if attempts_left <= 0:
                            raise AiModeUnavailable(f"navigation failed: {err}") from err
                        continue

                flagged = self._flagged_page_showing() if verify_left > 0 else ""
                # Every block page -- the sign-in wall too -- gets the CAPTCHA wait first
                # (owner 2026-11-15, after comparing with the distributor-intelligence
                # pipeline, which waits and keeps its warm profiles and is rarely blocked).
                # The sign-in wall: close the browser AT ONCE, delete its profile and
                # cookies, open a fresh one (owner 2026-11-15, screenshot, final call).
                # Nothing on that page can be solved, so no wait.
                if flagged.startswith("Sign in"):
                    vpn_report_block("signin")
                    self.captcha_count += 1
                    self.last_captcha_at = time.monotonic()
                    if resets_left > 0:
                        resets_left -= 1
                        self.reset_profile(reason="signin")
                        attempts_left += 1
                        continue
                    self._fresh_before_giving_up(new_profile=True)
                    raise AiModeCaptcha("Google sign-in wall on fresh profiles")
                if (flagged
                        and self._wait_for_block_page_clear(f"Google '{flagged}' page",
                                                            _captcha_wait())):
                    attempts_left += 1  # solved: same browser, no retry spent
                    continue
                if flagged:
                    # The session is flagged: clear cookies and relaunch the
                    # browser (twice), then a full profile reset; re-issue the
                    # query each time without costing a retry.
                    verify_left -= 1
                    self.captcha_count += 1
                    vpn_report_block("verify")
                    _ip_backoff_note_block()
                    self.flagged_blocks += 1
                    self.last_captcha_at = time.monotonic()
                    if self.flagged_blocks >= _MAX_FLAGGED_BLOCKS:
                        # Fresh profiles are blocked too: this is the IP, not the
                        # cookies. Stop so the step's own handling takes over rather
                        # than resetting for hours and making no progress.
                        self._fresh_before_giving_up()
                        self.flagged_blocks = 0
                        raise AiModeUnavailable(
                            f"Google is blocking this machine: {self.flagged_blocks} "
                            f"'{flagged}' pages that a browser reset did not clear. "
                            "Use fewer browsers, a longer GOOGLE_AI_MODE_QUERY_DELAY, "
                            "or wait for the block to lift."
                        )
                    # Cookies KEPT, same profile (owner 2026-11-15): a cookie-less session is
                    # what Google sends to the "Sign in to verify" wall, so clearing cookies
                    # made the wall come back. The distributor-intelligence pipeline never
                    # clears them and saw no sign-in walls on the same IP the same night.
                    self._reopen_after_block(_sorry_cool_off(3 - verify_left))
                    attempts_left += 1
                    continue

                if "/sorry/" in (self._page.url or ""):
                    self.captcha_count += 1
                    self.last_captcha_at = time.monotonic()
                    # Google's "unusual traffic / Try again later" block (owner
                    # 2026-11-06): close this browser, start it on a FRESH profile
                    # after a short cool-off and re-issue the query. Waiting on the
                    # page for a solve was pointless -- captcha-raptor cannot solve
                    # /sorry/ (see the note on CAPTCHA-solver extensions) -- and left
                    # the browser parked on the block for minutes. The cool-off grows
                    # with each reset of this query because the block follows the IP.
                    # An image-grid reCAPTCHA on the page CAN be solved by the
                    # extension, so it gets a short chance first; the "Try again
                    # later" variant has nothing to solve and resets at once.
                    # Every /sorry/ page now gets the full CAPTCHA wait before the browser
                    # is reset (owner 2026-11-14), also the "Try again later" variant: the
                    # window stays open so it can be solved by hand.
                    if (captcha_left > 0
                            and self._wait_for_block_page_clear("Google /sorry/ CAPTCHA page",
                                                                _captcha_wait())):
                        captcha_left -= 1
                        attempts_left += 1  # the solve must not cost a retry
                        continue
                    # Not solved: only now does it count as a block that pauses every
                    # browser (a solved CAPTCHA must not stop the others).
                    vpn_report_block("captcha")
                    _ip_backoff_note_block()
                    if resets_left > 0:
                        resets_left -= 1
                        sorry_resets += 1
                        self._reopen_after_block(_sorry_cool_off(sorry_resets))
                        attempts_left += 1
                        continue
                    # A CAPTCHA STORM is a soured profile, not bad luck.
                    # Observed while scoring: 31 CAPTCHAs in one run, every
                    # scoring query walled, 3 of 4 companies left unscored.
                    # The quota path already recovers by starting on a clean
                    # profile — sustained CAPTCHAs need exactly the same
                    # treatment, and without it the run keeps burning
                    # companies and producing nothing.
                    # No fresh profile after a CAPTCHA streak any more (owner 2026-11-15):
                    # fresh profiles were CAPTCHA'd MORE, not less. The warm profile stays.
                    self._fresh_before_giving_up()
                    self._last_query_at = time.monotonic()
                    raise AiModeCaptcha(
                        f"rate limited by Google ({self.captcha_count} CAPTCHAs this run)"
                    )

                self._wait_for_answer()
                try:
                    text = self._page.evaluate(_EXTRACT_JS) or ""
                except Exception:  # noqa: BLE001
                    try:
                        text = self._page.locator("main").first.inner_text() or ""
                    except Exception:  # noqa: BLE001
                        text = ""
                self._last_query_at = time.monotonic()

                low = text.lower()
                if any(m in low for m in CAPTCHA_MARKERS):
                    vpn_report_block("captcha")
                    self.captcha_count += 1
                    _ip_backoff_note_block()
                    self.last_captcha_at = time.monotonic()
                    if resets_left > 0:   # same block, shown without the /sorry/ URL
                        resets_left -= 1
                        sorry_resets += 1
                        self._reopen_after_block(_sorry_cool_off(sorry_resets))
                        attempts_left += 1
                        continue
                    self._fresh_before_giving_up()
                    raise AiModeCaptcha("blocked page text (unusual traffic)")
                # AI-response quota. Checked BEFORE the refusal markers: it
                # is rate limiting, so it needs the long cool-off, not an
                # immediate reworded retry. Cookies/profile resets do not
                # clear it — the quota follows the IP.
                # No length guard here, unlike the refusal check below. The
                # extracted text is the WHOLE page — nav chrome plus the
                # echoed prompt — which is comfortably over 600 chars, so the
                # old guard meant a quota page was never detected: it logged
                # "JSON parse OK", returned no companies, and the rounds loop
                # counted it as an empty market. These phrases cannot occur in
                # a genuine answer, so matching them anywhere is safe.
                if any(m in low for m in QUOTA_MARKERS):
                    vpn_report_block("no_answer")
                    self.quota_hits += 1
                    _ip_backoff_note_block()
                    self.last_captcha_at = time.monotonic()
                    # Archive the profile and try once on a clean one before
                    # giving up. Observed on this project: after a quota page,
                    # a fresh profile answered immediately and CAPTCHAs fell
                    # from 7 to 1, while cookie-clearing alone did not recover
                    # it. The limit is partly tied to the soured profile, not
                    # only to the IP.
                    # Escalating: each further reset of this query waits
                    # longer on the fresh profile (see _quota_cool_off).
                    if resets_left > 0:
                        resets_left -= 1
                        quota_resets += 1
                        self.reset_profile(
                            reason="quota", cool_off=_quota_cool_off(quota_resets)
                        )
                        attempts_left += 1
                        continue
                    self._fresh_before_giving_up(new_profile=True)
                    raise AiModeCaptcha(
                        "AI response request limit reached for this IP "
                        f"({self.quota_hits} this run) — only waiting helps"
                    )
                # "Something went wrong and the content wasn't generated." This
                # error page carries the echoed question, so with a long prompt
                # it is far over the 600-char refusal guard below and used to
                # pass as an answer (then fail to parse, retried in the same
                # soured browser). These phrases never occur in a real answer:
                # match anywhere and recover at once -- cookies cleared and the
                # browser relaunched (twice), then a full profile reset; the
                # query is re-issued each time without costing a retry.
                if noanswer_left > 0 and any(m in low for m in NO_ANSWER_MARKERS):
                    noanswer_left -= 1
                    vpn_report_block("no_answer")
                    self.soft_failures += 1
                    if noanswer_left >= 1:
                        self.reset_session(reason="'content wasn't generated' page")
                    else:
                        self.reset_profile(reason="noanswer")
                    attempts_left += 1
                    continue
                # Guard the refusal check with a length limit so a long real
                # answer that happens to contain the phrase is not discarded.
                if len(text) < 600 and any(m in low for m in REFUSAL_MARKERS):
                    self.soft_failures += 1
                    # Escalating recovery for "AI response wasn't generated":
                    #   1st  -> reword and retry
                    #   2nd  -> clear cookies + relaunch the browser
                    #   3rd+ -> archive the whole profile, reopen on a fresh one
                    # The streak spans queries (a good answer clears it), so a
                    # soured profile is replaced instead of failing query
                    # after query.
                    if (
                        self.soft_failures >= _SOFT_FAILURES_BEFORE_PROFILE_RESET
                        and resets_left > 0
                    ):
                        resets_left -= 1
                        self.reset_profile(reason="noanswer")
                        attempts_left += 1
                        url = build_url(prompt)
                        continue
                    if attempts_left > 0:
                        # Repeated soft failures on prompts that worked
                        # before point at a soured session, not a bad
                        # prompt — clear cookies and relaunch before the
                        # next attempt.
                        if self.soft_failures >= _SOFT_FAILURES_BEFORE_RESET:
                            self.reset_session()
                        print("  [ai-mode] no answer generated — rewording", flush=True)
                        url = build_url("Answer concisely. " + prompt.strip())
                        continue
                    raise AiModeRefusal(
                        "AI Mode did not generate a response "
                        f"({self.soft_failures} soft failures this run)"
                    )
                if text.strip():
                    self.soft_failures = 0  # a good answer clears the streak
                    self.flagged_blocks = 0  # Google is answering again
                    _ip_backoff_note_ok()
                    return text
            raise AiModeUnavailable("empty answer from AI Mode")

    def reset_profile(self, *, reason: str = "quota", cool_off: float = 0.0) -> None:
        """Hard reset: archive the whole profile directory, not just cookies.

        `reset_session` keeps the on-disk profile, which is right for a merely
        soured session. A quota page needs more: measured on this project,
        moving the profile aside and starting from a clean one restored
        answers immediately, where cookie-clearing alone did not.

        The old profile is renamed rather than deleted, so a run can be
        inspected afterwards and nothing is destroyed.
        """
        self.resets += 1
        # Use the channel this session actually launched with. Calling
        # resolve_channel() bare raised TypeError inside the reset path, and
        # because the caller treats any exception as "AI Mode unavailable"
        # it silently cost 56 companies their score.
        target = profile_dir_for(self.channel)
        print(
            f"  [ai-mode] {reason} — closing the browser, deleting its profile and starting clean "
            f"(reset #{self.resets})",
            flush=True,
        )
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._ctx = self._page = None
        # close() can leave the browser process alive, and it keeps a lock on
        # the profile directory. The rename then fails, and worse, the NEXT
        # market cannot launch at all: "Opening in existing browser session"
        # ended a market at 0 companies in 0 minutes.
        _kill_orphan_browsers(target)
        try:
            path = Path(target)
            if path.exists():
                stamp = time.strftime("%H%M%S")
                moved = path.with_name(f"{path.name}_{reason}_{stamp}")
                path.rename(moved)
                # Deleted, not kept (owner 2026-11-06): kept archives are never
                # read again and filled the disk -- 5,000+ of them, a 20-market
                # run killed by "No space left on device". The rename frees the
                # profile path at once; the delete runs in the background so the
                # fresh browser does not wait for it. A folder that cannot be
                # deleted keeps its archive-style name, so the watchdog's
                # cleaner still removes it later.
                # GOOGLE_AI_MODE_KEEP_ARCHIVED_PROFILES=true keeps them.
                if (os.getenv("GOOGLE_AI_MODE_KEEP_ARCHIVED_PROFILES") or "").lower()                         not in ("1", "true", "yes"):
                    threading.Thread(target=shutil.rmtree, args=(moved,),
                                     kwargs={"ignore_errors": True}, daemon=True).start()
        except Exception as err:  # noqa: BLE001
            # A locked file must not kill the run — the fresh browser will
            # simply reuse the old profile and the caller still cools off.
            print(f"  [ai-mode] could not reset profile folder: {err}", flush=True)
        self.soft_failures = 0
        self.quota_hits = 0
        time.sleep(cool_off)
        self._ensure_browser()

    def reset_session(self, *, reason: str = "") -> None:
        """Clear cookies and relaunch the browser.

        Google can sour a session: the same prompt shape that worked minutes
        ago starts returning "Something went wrong, and an AI response wasn't
        generated." Dropping the cookies and rebuilding the context recovers
        it without losing the warm profile on disk (history, which is what
        makes the profile look human, survives).
        """
        self.resets += 1
        why = reason or f"{self.soft_failures} consecutive no-answer pages"
        print(
            f"  [ai-mode] {why} — clearing cookies and relaunching browser (reset #{self.resets})",
            flush=True,
        )
        try:
            if self._ctx is not None:
                self._ctx.clear_cookies()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._ctx = self._page = None
        # The no-answer streak is deliberately NOT cleared here: if the pages
        # keep coming after this relaunch, the streak reaching
        # _SOFT_FAILURES_BEFORE_PROFILE_RESET is what escalates to a full
        # profile reset. A good answer or reset_profile() clears it.
        # No cool-off (owner 2026-10-11): a stuck browser is reset -- cookies
        # cleared, browser relaunched -- and goes straight back to work.
        self._ensure_browser()

    def _show_pause_page(self) -> None:
        """Put a short notice in the window while every browser waits out a Google block."""
        if self._page is None:
            return
        try:
            until = float(_ip_backoff_read().get("until") or 0)
            when = time.strftime("%H:%M", time.localtime(until)) if until else "shortly"
            self._page.set_content(
                "<html><head><title>Paused: Google block</title></head>"
                "<body style='font:20px sans-serif;margin:60px;color:#333'>"
                "<h2>Waiting: Google is limiting searches from this network</h2>"
                f"<p>Every browser pauses until about <b>{when}</b>, then this window "
                "searches again by itself. Nothing is stuck; do not close it.</p></body></html>",
                timeout=5000)
        except Exception:  # noqa: BLE001 -- a notice must never break the query
            pass

    def _reopen_after_block(self, cool_off: float) -> None:
        """An unsolved block page: wait, then reopen the browser on the SAME profile
        (cookies and history kept) -- never a brand-new profile (owner 2026-11-15)."""
        if cool_off > 0:
            print(f"  [ai-mode] block not solved -- waiting {cool_off:.0f} s, then the same "
                  "browser profile is reopened", flush=True)
            time.sleep(cool_off)
        self.reopen_browser(reason="Google block page")

    def reopen_browser(self, *, reason: str = "browser closed") -> None:
        """Close whatever is left of the browser and open a fresh one on the
        SAME profile. For a crashed or externally closed browser, where the
        profile itself is fine and only the process is gone."""
        self.resets += 1
        print(f"  [ai-mode] {reason} — reopening the browser (reset #{self.resets})",
              flush=True)
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._ctx = self._page = None
        # A half-dead process keeps the profile lock and the relaunch would
        # fail with "Opening in existing browser session".
        _kill_orphan_browsers(profile_dir_for(self.channel))
        time.sleep(5)
        self._ensure_browser()

    def status(self) -> str:
        if not self.captcha_count:
            return "no sign of blocking (0 CAPTCHAs this run)"
        ago = time.monotonic() - self.last_captcha_at
        return (
            f"{self.captcha_count} CAPTCHAs this run, last {ago:.0f}s ago"
        )


_SESSION: AiModeSession | None = None
_SESSION_LOCK = threading.Lock()

# Patchright's SYNC api cannot be driven from a thread that is running an
# asyncio event loop ("It looks like you are using Playwright Sync API inside
# the asyncio loop"). The pipeline is async, so every browser call is funnelled
# into ONE dedicated worker thread that owns the browser and never runs a loop.
# A single worker also enforces the one-query-at-a-time rule the backend needs
# anyway.
_WORKER: Any = None
_WORKER_LOCK = threading.Lock()


def _worker() -> Any:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER is None:
            from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

            _WORKER = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="ai-mode-browser"
            )
        return _WORKER


def _in_worker(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a browser call on the dedicated thread and wait for the result."""
    if threading.current_thread().name.startswith("ai-mode-browser"):
        return fn(*args, **kwargs)  # already on it — do not deadlock
    return _worker().submit(fn, *args, **kwargs).result()


def session() -> AiModeSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = AiModeSession()
        return _SESSION


def close_session() -> None:
    global _SESSION, _WORKER
    with _SESSION_LOCK:
        if _SESSION is not None:
            try:
                _in_worker(_SESSION.close)
            except Exception:  # noqa: BLE001
                pass
            _SESSION = None
    with _WORKER_LOCK:
        if _WORKER is not None:
            _WORKER.shutdown(wait=False)
            _WORKER = None


def reset_live_browser(reason: str) -> bool:
    """Fresh profile, cookies and browser for the browser THIS process opened,
    run on the browser's own thread (patchright objects are bound to it: a
    reset from another thread left every later query failing with "Cannot
    switch to a different thread"). No live browser -> nothing is touched, so
    a caller faking a block never archives a real profile. True if reset."""
    with _SESSION_LOCK:
        sess = _SESSION
    if sess is None or sess._ctx is None:
        return False
    _in_worker(lambda: sess.reset_profile(reason=reason))
    return True


def ask(prompt: str, **kw: Any) -> str:
    """Send one prompt to AI Mode. Safe to call from sync or async code."""
    if not enabled():
        raise AiModeUnavailable("GOOGLE_AI_MODE_ENABLED is false")
    return _in_worker(lambda: session().ask(prompt, **kw))


# --- reply parsing ---------------------------------------------------------

_ARRAY_START_RE = re.compile(r'\[\s*\{\s*"[A-Za-z_]')
_OBJECT_START_RE = re.compile(r'\{\s*"[A-Za-z_]')


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def parse_json_answer(raw: str, *, require_key: str | None = None, prompt: str = "") -> Any:
    """Pull JSON out of a rendered AI Mode answer.

    Three defences: strip Google's UI footer, strip a stray ``json`` language
    tag, and skip the model's echo of the prompt's own JSON template. With
    ``prompt`` given, a structure copied verbatim from the prompt is never
    taken as the answer even when its example values are filled in: when AI
    Mode replies in prose, the echoed question bubble is the only JSON on the
    page, and its example values would otherwise be read as the verdict.
    """
    text = (raw or "").replace("Use code with caution.", "")
    text = text.replace("```json", "").replace("```", "")
    stripped = text.lstrip()
    if stripped[:4].lower() == "json":
        text = stripped[4:]

    # AI Mode ECHOES the question, so a naive find("[") locks onto the
    # prompt's own empty JSON template and yields zero results. Slice FROM
    # each marker, never past it (an off-by-one here drops the first item of
    # every batch), and prefer the longest structure so a wrapper object is
    # not reduced to its inner list. Candidates that carry no actual values
    # are rejected outright, which is what discards the echoed template
    # whether it appears before or after the real answer.
    starts: list[int] = [m.start() for m in _ARRAY_START_RE.finditer(text)]
    starts += [m.start() for m in _OBJECT_START_RE.finditer(text)]
    candidates: list[str] = []
    for start in sorted(set(starts), reverse=True):
        blob = _balanced_slice(text, start)
        if blob:
            candidates.append(blob)
    # A longer candidate encloses a shorter one, so the outermost structure is
    # tried first.
    candidates.sort(key=len, reverse=True)
    echoed = _squash(prompt)
    if echoed:
        candidates = [c for c in candidates if _squash(c) not in echoed]
    fallback: Any = None
    for blob in candidates:
        for attempt in (blob, re.sub(r"\s*\n\s*", " ", blob)):
            try:
                data = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if require_key:
                if isinstance(data, dict) and data.get(require_key):
                    if _has_values(data[require_key]):
                        return data
                    fallback = fallback if fallback is not None else data
                    continue
                if isinstance(data, list) and data:
                    if _has_values(data):
                        return {require_key: data}
                    fallback = fallback if fallback is not None else {require_key: data}
                continue
            if _has_values(data):
                return data
            fallback = fallback if fallback is not None else data
    if fallback is not None:
        return fallback
    raise json.JSONDecodeError("no JSON object found in AI Mode answer", text[:200], 0)


def _balanced_slice(text: str, start: int) -> str:
    """Slice one JSON structure starting at ``start``, matching brackets.

    ``rfind`` on the closing bracket over-reaches when the answer is followed
    by an echoed template, swallowing both into one unparseable blob.
    """
    opener = text[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1] if ch == closer else ""
    # Truncated mid-structure: close it off so json can still try.
    return text[start:] + closer * max(0, depth)


def _has_values(data: Any) -> bool:
    """True when a parsed structure carries at least one real value.

    An echoed prompt template parses cleanly but every field is blank, so
    emptiness is what separates it from a genuine answer.
    """
    if isinstance(data, dict):
        return any(_has_values(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_values(v) for v in data)
    if isinstance(data, str):
        return bool(data.strip())
    return data is not None


# --- OpenAI-shaped adapter -------------------------------------------------

_BLANK_PREFERRED = (
    "An empty string is CORRECT and preferred whenever you do not genuinely "
    "know a value. NEVER construct an email from a domain. NEVER build a "
    "LinkedIn URL from a person's name. NEVER invent a phone number. "
    "A wrong value is much worse than an empty one."
)


def chat(system: str, user: str, **_ignored: Any) -> str:
    """``model``, ``max_tokens`` and ``temperature`` are accepted and IGNORED —
    AI Mode is a web UI, not a metered API. Keeping them in the signature is
    what makes this a true drop-in swap."""
    sys_text = (system or "").strip()
    user_text = (user or "").strip()
    prompt = f"{sys_text}\n\n{user_text}" if sys_text else user_text
    text = ask(prompt)
    if not text:
        raise AiModeUnavailable("AI Mode returned nothing")
    return text


def chat_json(
    system: str,
    user: str,
    *,
    require_key: str | None = None,
    **kw: Any,
) -> Any:
    guarded = (system or "").strip()
    if guarded:
        guarded = f"{guarded}\n\n{_BLANK_PREFERRED}"
    return parse_json_answer(chat(guarded, user, **kw), require_key=require_key,
                             prompt=f"{guarded}\n\n{(user or '').strip()}")


# --- CLI: install / verify an extension, or send one prompt -----------------


def _cli(argv: list[str]) -> int:
    usage = (
        "usage:\n"
        "  python -m vendor_intel.scraping.google_ai_mode install <folder>\n"
        "  python -m vendor_intel.scraping.google_ai_mode doctor\n"
        "  python -m vendor_intel.scraping.google_ai_mode ask <prompt...>\n"
    )
    if not argv:
        print(usage)
        return 2
    cmd, rest = argv[0], argv[1:]

    # The pipeline scripts load .env themselves; run stand-alone, this CLI must
    # too, or `doctor` reports defaults instead of what a real run will use
    # (e.g. GOOGLE_AI_MODE_EXTENSIONS). Variables already set keep priority.
    try:
        from dotenv import load_dotenv  # noqa: PLC0415

        load_dotenv(bundled_extensions_root().parent / ".env")
    except ImportError:
        pass

    if cmd == "install":
        if not rest:
            print(usage)
            return 2
        return 0 if install_extension(rest[0]) else 1

    if cmd == "doctor":
        exts = installed_extensions()
        channel = resolve_channel(exts)
        print(f"patchright installed : {_patchright_version() or 'NO — pip install patchright'}")
        print(f"managed Chrome policy: {managed_chrome_blocks_extensions()}")
        print(f"extensions staged    : {exts or '(none)'}")
        print(f"derived ids          : {[unpacked_extension_id(p) for p in exts]}")
        print(f"browser to be used   : {channel or 'chromium (bundled)'}")
        print(f"profile dir          : {profile_dir_for(channel)}")
        print(f"staging root         : {staging_root(_profile_dir())}")
        if not enabled():
            print("\nGOOGLE_AI_MODE_ENABLED is false — set it to true to use the backend.")
            return 0
        if not exts:
            print("\nNo extension staged. Pacing is what prevents blocks anyway;")
            print("an extension cannot clear 'Cannot contact reCAPTCHA'.")
            return 0
        sess = session()
        try:
            sess._ensure_browser()
            return 0 if sess.verify_extensions() else 1
        finally:
            close_session()

    if cmd == "ask":
        if not rest:
            print(usage)
            return 2
        try:
            print(ask(" ".join(rest)))
            return 0
        except (AiModeCaptcha, AiModeRefusal, AiModeUnavailable) as err:
            print(f"{type(err).__name__}: {err}")
            return 1
        finally:
            close_session()

    print(usage)
    return 2


def _patchright_version() -> str:
    try:
        import patchright  # noqa: PLC0415

        return getattr(patchright, "__version__", "yes")
    except ImportError:
        return ""


if __name__ == "__main__":
    import sys

    raise SystemExit(_cli(sys.argv[1:]))
