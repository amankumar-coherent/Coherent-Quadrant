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

_READY_MARKER = "ai mode response is ready"


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


def _query_delay() -> float:
    try:
        return float(_env("GOOGLE_AI_MODE_QUERY_DELAY", "10") or 10)
    except ValueError:
        return _DEFAULT_DELAY


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

        args = ["--profile-directory=Default"]
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
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(**launch)
        except Exception as err:  # noqa: BLE001
            # "Opening in existing browser session" = a browser from a killed
            # run still holds the profile lock. Retrying without clearing it
            # fails every time, so the market ends at 0 companies. Clear the
            # lock and launch once more.
            if "existing browser session" not in str(err).lower():
                raise
            print(
                "  [ai-mode] profile is locked by a previous browser — "
                "clearing it and retrying",
                flush=True,
            )
            _kill_orphan_browsers(profile)
            self._ctx = self._pw.chromium.launch_persistent_context(**launch)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        print(
            f"  [ai-mode] browser ready ({self.channel or 'chromium'}, "
            f"headless={headless}, profile={profile})",
            flush=True,
        )
        if self.extensions:
            self.verify_extensions()

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

    def _wait_for_captcha_clear(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._page.wait_for_timeout(2000)
            if "/sorry/" not in (self._page.url or ""):
                return True  # solved -> caller MUST re-issue the query
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

            while attempts_left > 0:
                attempts_left -= 1
                self._pace()
                try:
                    self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                except Exception as err:  # noqa: BLE001
                    # AI Mode client-side-redirects (&sei=) right after load,
                    # which can interrupt the navigation wait. Benign.
                    if "interrupted by another navigation" not in str(err).lower():
                        self._last_query_at = time.monotonic()
                        if attempts_left <= 0:
                            raise AiModeUnavailable(f"navigation failed: {err}") from err
                        continue

                if "/sorry/" in (self._page.url or ""):
                    self.captcha_count += 1
                    self.last_captcha_at = time.monotonic()
                    print(
                        f"  [ai-mode] CAPTCHA ({self.captcha_count} this run) — "
                        "solve it in the browser window",
                        flush=True,
                    )
                    if captcha_left > 0 and self._wait_for_captcha_clear():
                        captcha_left -= 1
                        attempts_left += 1  # the solve must not cost a retry
                        continue
                    # A CAPTCHA STORM is a soured profile, not bad luck.
                    # Observed while scoring: 31 CAPTCHAs in one run, every
                    # scoring query walled, 3 of 4 companies left unscored.
                    # The quota path already recovers by starting on a clean
                    # profile — sustained CAPTCHAs need exactly the same
                    # treatment, and without it the run keeps burning
                    # companies and producing nothing.
                    if (
                        self.captcha_count >= _CAPTCHAS_BEFORE_PROFILE_RESET
                        and attempts_left > 0
                    ):
                        self.reset_profile(reason="captchas")
                        self.captcha_count = 0
                        continue
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
                    self.captcha_count += 1
                    self.last_captcha_at = time.monotonic()
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
                    self.quota_hits += 1
                    self.last_captcha_at = time.monotonic()
                    # Archive the profile and try once on a clean one before
                    # giving up. Observed on this project: after a quota page,
                    # a fresh profile answered immediately and CAPTCHAs fell
                    # from 7 to 1, while cookie-clearing alone did not recover
                    # it. The limit is partly tied to the soured profile, not
                    # only to the IP.
                    if attempts_left > 0:
                        self.reset_profile(reason="quota")
                        continue
                    raise AiModeCaptcha(
                        "AI response request limit reached for this IP "
                        f"({self.quota_hits} this run) — only waiting helps"
                    )
                # Guard the refusal check with a length limit so a long real
                # answer that happens to contain the phrase is not discarded.
                if len(text) < 600 and any(m in low for m in REFUSAL_MARKERS):
                    self.soft_failures += 1
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
                    return text
            raise AiModeUnavailable("empty answer from AI Mode")

    def reset_profile(self, *, reason: str = "quota", cool_off: float = 120.0) -> None:
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
            f"  [ai-mode] {reason} — archiving profile and starting clean "
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
                path.rename(path.with_name(f"{path.name}_{reason}_{stamp}"))
        except Exception as err:  # noqa: BLE001
            # A locked file must not kill the run — the fresh browser will
            # simply reuse the old profile and the caller still cools off.
            print(f"  [ai-mode] could not archive profile: {err}", flush=True)
        self.soft_failures = 0
        self.quota_hits = 0
        time.sleep(cool_off)
        self._ensure_browser()

    def reset_session(self) -> None:
        """Clear cookies and relaunch the browser.

        Google can sour a session: the same prompt shape that worked minutes
        ago starts returning "Something went wrong, and an AI response wasn't
        generated." Dropping the cookies and rebuilding the context recovers
        it without losing the warm profile on disk (history, which is what
        makes the profile look human, survives).
        """
        self.resets += 1
        print(
            f"  [ai-mode] {self.soft_failures} consecutive no-answer pages — "
            f"clearing cookies and relaunching browser (reset #{self.resets})",
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
        self.soft_failures = 0
        # A soured session usually comes with rate limiting, so give the IP a
        # breather before the fresh browser starts querying.
        time.sleep(60)
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


def ask(prompt: str, **kw: Any) -> str:
    """Send one prompt to AI Mode. Safe to call from sync or async code."""
    if not enabled():
        raise AiModeUnavailable("GOOGLE_AI_MODE_ENABLED is false")
    return _in_worker(lambda: session().ask(prompt, **kw))


# --- reply parsing ---------------------------------------------------------

_ARRAY_START_RE = re.compile(r'\[\s*\{\s*"[A-Za-z_]')
_OBJECT_START_RE = re.compile(r'\{\s*"[A-Za-z_]')


def parse_json_answer(raw: str, *, require_key: str | None = None) -> Any:
    """Pull JSON out of a rendered AI Mode answer.

    Three defences: strip Google's UI footer, strip a stray ``json`` language
    tag, and skip the model's echo of the prompt's own empty JSON template.
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
    return parse_json_answer(chat(guarded, user, **kw), require_key=require_key)


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
