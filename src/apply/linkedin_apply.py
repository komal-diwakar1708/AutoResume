"""
LinkedIn Easy Apply automation using Playwright.

Authentication strategy:
─────────────────────────────────────────────────────────────────────────────
Chrome blocks DevTools remote debugging on its DEFAULT user-data-dir
  (error: "DevTools remote debugging requires a non-default data directory").
So we cannot drive the real profile directly.

However, if we COPY the profile to a new directory, Chrome is happy to
launch with debugging.  The one remaining pitfall is that Playwright silently
injects --use-mock-keychain and --password-store=basic, which disable the
macOS Keychain — so Chrome can't decrypt the session cookies it copied.

Fix: pass ignore_default_args to skip those two flags.  Then Chrome uses the
real macOS Keychain, decrypts the copied Cookies file, and LinkedIn accepts
the session.

Workflow:
  1. `python main.py --extract-chrome-cookies`
       Copies Chrome's Default/Cookies (+ WAL/SHM + Local Storage) into
       data/chrome_profile/Default/, then verifies the LinkedIn session.

  2. `python main.py`  (normal run)
       Each Easy Apply opens Chrome with the copied profile (headless).

  3. Session expires → repeat step 1.
"""

import json
import logging
import os
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.apply.form_filler import get_work_authorization

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────

DATA_DIR         = Path(__file__).parent.parent.parent / "data"
CHROME_DEFAULT   = Path.home() / "Library/Application Support/Google/Chrome/Default"
CHROME_USER_DATA = Path.home() / "Library/Application Support/Google/Chrome"
# Copied profile lives here — Playwright uses this as user_data_dir
PROFILE_DIR      = DATA_DIR / "chrome_profile"
# Sub-directory that holds the actual profile files
PROFILE_DEFAULT  = PROFILE_DIR / "Default"
STATE_PATH       = DATA_DIR / "linkedin_state.json"   # kept for CLI compat

LINKEDIN_FEED      = "https://www.linkedin.com/feed/"
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"

# ── Playwright launch config ───────────────────────────────────────────────

# Playwright injects these by default; they disable macOS Keychain so Chrome
# cannot decrypt cookies.  We remove them so the real Keychain is used.
SKIP_ARGS = ["--use-mock-keychain", "--password-store=basic"]

EXTRA_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    # Move the window off-screen so it doesn't cover the user's work, but
    # keep it headed so LinkedIn doesn't detect a headless fingerprint.
    "--window-position=2000,2000",
    "--window-size=1280,800",
]

# ── Profile files to copy from Chrome's Default/ directory ─────────────────

COPY_FILES = [
    "Cookies", "Cookies-wal", "Cookies-shm",
    "Preferences",
]
COPY_DIRS = [
    "Local Storage",
]

# Root-level Chrome files (live in user_data_dir, not Default/)
COPY_ROOT_FILES = [
    "Local State",   # Chrome needs this to init encryption keys correctly
]


# ── Helper functions ────────────────────────────────────────────────────────

def _chrome_is_running() -> bool:
    """Return True if Google Chrome is currently open."""
    r = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
    return r.returncode == 0


def _is_logged_in_url(url: str) -> bool:
    """True when the URL path indicates an authenticated LinkedIn page."""
    path = urlparse(url).path.rstrip("/")
    return any(path.startswith(f"/{x}") for x in ("feed", "mynetwork", "jobs", "in"))


def _human_delay(min_s: float = 1.5, max_s: float = 3.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _fail(reason: str) -> dict:
    logger.warning("[linkedin_apply] %s", reason)
    return {"success": False, "status": "manual_required", "notes": reason}


def _copy_profile() -> bool:
    """
    Copy Chrome's Default profile files into PROFILE_DIR/Default/.
    Chrome must be closed before calling this.
    Returns True on success.
    """
    if not CHROME_DEFAULT.exists():
        logger.error("[linkedin] Chrome Default profile not found at %s", CHROME_DEFAULT)
        return False

    PROFILE_DEFAULT.mkdir(parents=True, exist_ok=True)

    ok = False
    for fname in COPY_FILES:
        src = CHROME_DEFAULT / fname
        if src.exists():
            shutil.copy2(src, PROFILE_DEFAULT / fname)
            logger.debug("[linkedin] Copied %s", fname)
            if fname == "Cookies":
                ok = True

    for dname in COPY_DIRS:
        src = CHROME_DEFAULT / dname
        dst = PROFILE_DEFAULT / dname
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            logger.debug("[linkedin] Copied dir %s", dname)

    # Root-level files (user_data_dir root, not inside Default/)
    for fname in COPY_ROOT_FILES:
        src = CHROME_USER_DATA / fname
        dst = PROFILE_DIR / fname
        if src.exists():
            shutil.copy2(src, dst)
            logger.debug("[linkedin] Copied root %s", fname)

    if not ok:
        logger.error("[linkedin] Cookies file not found in Chrome profile")
    return ok


# ── Main class ──────────────────────────────────────────────────────────────

class LinkedInApplier:
    def __init__(self, config: dict):
        self.config = config
        self.personal = config.get("personal", {})
        self.resume_path = Path(config.get("resume_path", "resume/resume.pdf")).resolve()
        self.email = os.getenv("LINKEDIN_EMAIL", "")
        self.password = os.getenv("LINKEDIN_PASSWORD", "")
        self._auth_status: Optional[bool] = None

    # ── Public API ────────────────────────────────────────────────────────

    def ensure_authenticated(self) -> bool:
        """Check that the copied profile exists and Chrome is not running."""
        if self._auth_status is not None:
            return self._auth_status

        if not PROFILE_DEFAULT.exists() or not (PROFILE_DEFAULT / "Cookies").exists():
            logger.warning(
                "[linkedin] No copied profile found. "
                "Run: python main.py --extract-chrome-cookies"
            )
            self._auth_status = False
            return False

        if _chrome_is_running():
            logger.error(
                "[linkedin] Chrome is open — please quit Chrome (Cmd+Q) before running the bot."
            )
            self._auth_status = False
            return False

        self._auth_status = True
        return True

    @staticmethod
    def extract_from_chrome() -> bool:
        """
        Copy Chrome's profile to PROFILE_DIR, then verify the LinkedIn session.
        Chrome MUST be closed before calling this.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("  Playwright not installed.")
            return False

        if not CHROME_DEFAULT.exists():
            print(f"  Chrome profile not found at {CHROME_DEFAULT}")
            print("  Make sure Google Chrome is installed.")
            return False

        if _chrome_is_running():
            print("\n  Chrome is currently open.")
            print("  Please quit Chrome first (Cmd+Q while Chrome is focused),")
            print("  then re-run:  python main.py --extract-chrome-cookies")
            return False

        print("\n  Copying Chrome profile...")
        if not _copy_profile():
            print("  Failed to copy Chrome profile. Is Chrome installed?")
            return False
        print("  Profile copied. Verifying LinkedIn session...\n")

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    str(PROFILE_DIR),
                    channel="chrome",
                    headless=False,          # headed — avoids LinkedIn bot-detection
                    ignore_default_args=SKIP_ARGS,
                    args=EXTRA_ARGS,
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                try:
                    page.goto(LINKEDIN_FEED, wait_until="domcontentloaded", timeout=30000)
                    _human_delay(2, 3)
                    url = page.url
                    ok = _is_logged_in_url(url)
                    if ok:
                        print("  Session valid — LinkedIn feed loaded.")
                        print("  Run `python main.py` to start applying.\n")
                        DATA_DIR.mkdir(exist_ok=True)
                        (DATA_DIR / ".linkedin_verified").write_text("ok")
                    else:
                        print(f"  Session invalid. LinkedIn redirected to: {url}")
                        print("  Open Chrome, log into LinkedIn, quit Chrome, then re-run.")
                    return ok
                finally:
                    context.close()
        except Exception as exc:
            logger.error("[linkedin] Verification error: %s", exc)
            print(f"\n  Error: {exc}")
            return False

    def save_cookies_interactively(self) -> bool:
        """CLI hook for --linkedin-login (kept for backward compat)."""
        return self.extract_from_chrome()

    @staticmethod
    def import_cookies_from_file(raw_cookies_path: str) -> bool:
        """Import LinkedIn cookies from a JSON file (Cookie-Editor export format)."""
        src = Path(raw_cookies_path)
        if not src.exists():
            print(f"  File not found: {src}")
            return False
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  Could not parse JSON: {exc}")
            return False
        if not isinstance(raw, list):
            print("  Expected a JSON array from Cookie-Editor export.")
            return False

        cookies = []
        for c in raw:
            name = c.get("name", "")
            domain = c.get("domain", "")
            if not name or "linkedin" not in domain:
                continue
            same_site = c.get("sameSite", "None")
            if same_site not in ("Strict", "Lax", "None"):
                same_site = "None"
            cookies.append({
                "name": name,
                "value": c.get("value", ""),
                "domain": domain,
                "path": c.get("path", "/"),
                "expires": float(c.get("expirationDate", c.get("expires", -1)) or -1),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": same_site,
            })

        if not cookies:
            print("  No LinkedIn cookies found. Export from https://www.linkedin.com")
            return False

        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2))
        names = {c["name"] for c in cookies}
        print(f"\n  Imported {len(cookies)} cookies (li_at present: {'li_at' in names})")
        print("  For best results use --extract-chrome-cookies instead.\n")
        return True

    def apply(self, job: dict, cover_letter: str) -> dict:
        """Attempt LinkedIn Easy Apply using the copied Chrome profile."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return _fail("Playwright not installed")

        if not self.ensure_authenticated():
            return _fail(
                "No valid LinkedIn session. Run: python main.py --extract-chrome-cookies"
            )

        result = {"success": False, "status": "manual_required", "notes": ""}

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    str(PROFILE_DIR),
                    channel="chrome",
                    headless=False,          # headed — avoids LinkedIn bot-detection
                    ignore_default_args=SKIP_ARGS,
                    args=EXTRA_ARGS,
                    viewport={"width": 1280, "height": 800},
                )
                page = context.new_page()
                try:
                    page.goto(job["url"], wait_until="domcontentloaded", timeout=60000)
                    _human_delay()

                    if any(x in page.url for x in ("login", "authwall", "checkpoint", "challenge")):
                        logger.warning("[linkedin] Session expired — re-run --extract-chrome-cookies")
                        self._auth_status = None
                        return _fail(
                            "LinkedIn session expired. Run: python main.py --extract-chrome-cookies"
                        )

                    easy_apply_btn = (
                        page.query_selector("button.jobs-apply-button[aria-label*='Easy Apply']")
                        or page.query_selector("button[aria-label*='Easy Apply']")
                    )
                    if not easy_apply_btn:
                        result["notes"] = "No Easy Apply button — external application required"
                        return result

                    easy_apply_btn.click()
                    _human_delay(2, 4)

                    job_location = job.get("location", "")
                    for step in range(10):
                        if not self._handle_modal_step(page, cover_letter, job_location):
                            result["notes"] = f"Stopped at modal step {step + 1}"
                            return result

                        submit_btn = page.query_selector("button[aria-label='Submit application']")
                        if submit_btn:
                            submit_btn.click()
                            _human_delay(2, 3)
                            result["success"] = True
                            result["status"] = "applied"
                            result["notes"] = f"Easy Apply submitted: {job['title']} @ {job['company']}"
                            logger.info("Applied: %s @ %s", job["title"], job["company"])
                            return result

                        next_btn = (
                            page.query_selector("button[aria-label='Continue to next step']")
                            or page.query_selector("button[aria-label='Review your application']")
                        )
                        if next_btn:
                            next_btn.click()
                            _human_delay(1, 3)
                        else:
                            result["notes"] = "Could not find Next or Submit button"
                            return result

                    result["notes"] = "Exceeded max modal steps"

                except Exception as exc:
                    logger.error("[linkedin_apply] Error: %s", exc)
                    result["notes"] = str(exc)
                finally:
                    context.close()

        except Exception as exc:
            logger.error("[linkedin_apply] Browser launch error: %s", exc)
            result["notes"] = str(exc)

        return result

    # ── Session verification ──────────────────────────────────────────────

    def _verify_session(self) -> bool:
        """Verify LinkedIn session using the copied profile."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    str(PROFILE_DIR),
                    channel="chrome",
                    headless=False,          # headed — avoids LinkedIn bot-detection
                    ignore_default_args=SKIP_ARGS,
                    args=EXTRA_ARGS,
                )
                page = context.new_page()
                try:
                    page.goto(LINKEDIN_FEED, wait_until="domcontentloaded", timeout=30000)
                    _human_delay(1, 2)
                    url = page.url
                    valid = _is_logged_in_url(url)
                    if valid:
                        logger.info("[linkedin] Session verified (URL=%s)", url)
                    else:
                        logger.warning("[linkedin] Session invalid, redirected to: %s", url)
                    return valid
                finally:
                    context.close()
        except Exception as exc:
            logger.error("[linkedin] Session verification error: %s", exc)
            return False

    def _bootstrap_session(self) -> bool:
        """Alias kept for backward compat."""
        return self.extract_from_chrome()

    # ── Modal step handling ──────────────────────────────────────────────

    def _handle_modal_step(self, page, cover_letter: str, job_location: str = "") -> bool:
        try:
            _human_delay(1, 2)

            phone = page.query_selector("input[id*='phoneNumber']")
            if phone and not phone.input_value():
                p = self.personal.get("phone", "")
                if p:
                    phone.fill(p)
                    _human_delay(0.5, 1)

            resume_upload = page.query_selector("input[type='file']")
            if resume_upload and self.resume_path.exists():
                resume_upload.set_input_files(str(self.resume_path))
                _human_delay(1, 2)

            for label_text in ["cover letter", "additional information", "message"]:
                textarea = page.query_selector(f"textarea[name*='{label_text}']")
                if not textarea:
                    for lbl in page.query_selector_all("label"):
                        if label_text.lower() in (lbl.inner_text() or "").lower():
                            fid = lbl.get_attribute("for")
                            if fid:
                                textarea = page.query_selector(f"#{fid}")
                            break
                if textarea:
                    if not textarea.input_value():
                        textarea.fill(cover_letter[:2000])
                    _human_delay(0.5, 1)
                    break

            work_auth = get_work_authorization(job_location, self.personal)
            for auth_label in ["work authorization", "right to work", "eligible to work", "visa"]:
                for lbl in page.query_selector_all("label"):
                    if auth_label in (lbl.inner_text() or "").lower():
                        fid = lbl.get_attribute("for")
                        if fid:
                            inp = page.query_selector(f"#{fid}")
                            if inp and not inp.input_value():
                                inp.fill(work_auth)
                                _human_delay(0.3, 0.6)
                        break

            for radio in page.query_selector_all("input[type='radio'][value='Yes']"):
                if not radio.is_checked():
                    radio.click()
                    _human_delay(0.3, 0.7)

            for ni in page.query_selector_all("input[type='text'][id*='numeric']"):
                if not ni.input_value():
                    ni.fill(str(self.personal.get("years_of_experience", "5")))
                    _human_delay(0.3, 0.5)

            return True
        except Exception as exc:
            logger.error("[linkedin_apply] Modal step error: %s", exc)
            return False

    def _try_auto_fill_login(self, page) -> None:
        """Legacy stub — not used."""
        pass
