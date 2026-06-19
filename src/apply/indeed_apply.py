"""
Indeed Quick Apply automation using Playwright.

Flow:
  1. Log in to Indeed (credentials from .env)
  2. Navigate to the job posting URL
  3. Click "Apply now" / "Easily Apply" button
  4. Fill the application form (resume, contact details, screening questions)
  5. Submit

Limitations:
  - Indeed's apply flow varies significantly per employer.
  - Complex multi-page forms or employer-hosted forms fall back to manual_required.
  - Indeed may redirect to external employer ATS — handled by detecting same-origin.
"""

import logging
import os
import random
import time
from pathlib import Path
from typing import Optional

from src.apply.form_filler import get_work_authorization

logger = logging.getLogger(__name__)

INDEED_LOGIN_URL = "https://secure.indeed.com/account/login"


class IndeedApplier:
    def __init__(self, config: dict):
        self.config = config
        self.personal = config.get("personal", {})
        self.resume_path = Path(config.get("resume_path", "resume/resume.pdf")).resolve()
        self.email = os.getenv("INDEED_EMAIL", "")
        self.password = os.getenv("INDEED_PASSWORD", "")

    def apply(self, job: dict, cover_letter: str) -> dict:
        """
        Attempt to Quick Apply to an Indeed job.

        Args:
            job: dict with keys: url, title, company, id
            cover_letter: pre-generated cover letter text

        Returns:
            dict with keys: success (bool), status (str), notes (str)
        """
        if not self.email or not self.password:
            return _fail("Indeed credentials not set in .env")

        # Detect placeholder values left over from .env.example
        if "your_" in self.password.lower() or "placeholder" in self.password.lower():
            return _fail("Indeed password looks like a placeholder — update INDEED_PASSWORD in .env")

        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError:
            return _fail("Playwright not installed")

        result = {"success": False, "status": "manual_required", "notes": ""}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            stealth_sync(page)

            try:
                # ── Login ──────────────────────────────────────────────────
                if not self._login(page):
                    return _fail("Indeed login failed")

                # ── Navigate to job ────────────────────────────────────────
                page.goto(job["url"], wait_until="domcontentloaded", timeout=30000)
                _human_delay()

                # ── Find Apply button ──────────────────────────────────────
                apply_btn = (
                    page.query_selector("button[id='indeedApplyButton']")
                    or page.query_selector("a[id='applyButtonLinkContainer']")
                    or page.query_selector("button[data-testid='indeedApplyButton']")
                    or page.query_selector("span.indeed-apply-widget button")
                )

                if not apply_btn:
                    result["notes"] = "No Indeed Quick Apply button found — external apply"
                    result["status"] = "manual_required"
                    return result

                apply_btn.click()
                _human_delay(2, 4)

                # ── Detect if we stayed on Indeed or got redirected ────────
                if "indeed.com" not in page.url:
                    result["notes"] = "Redirected to external employer ATS"
                    result["status"] = "manual_required"
                    return result

                # ── Fill application form ──────────────────────────────────
                for step in range(8):
                    self._fill_form_step(page, cover_letter, job.get("location", ""))

                    # Check for submission confirmation
                    if self._check_submitted(page):
                        result["success"] = True
                        result["status"] = "applied"
                        result["notes"] = f"Indeed Quick Apply submitted for {job['title']} @ {job['company']}"
                        logger.info("Applied: %s @ %s via Indeed", job["title"], job["company"])
                        return result

                    # Try to advance
                    if not self._click_next_or_submit(page):
                        result["notes"] = f"Stopped at form step {step + 1}"
                        return result

                    _human_delay(1, 3)

            except Exception as exc:
                logger.error("[indeed_apply] Error: %s", exc)
                result["notes"] = str(exc)
            finally:
                browser.close()

        return result

    def _login(self, page) -> bool:
        try:
            page.goto(INDEED_LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
            _human_delay()

            email_input = page.query_selector("input[name='__email']") or page.query_selector("input[type='email']")
            if email_input:
                email_input.fill(self.email)
                _human_delay(0.5, 1)

            page.keyboard.press("Enter")
            _human_delay(1, 2)

            password_input = page.query_selector("input[name='__password']") or page.query_selector("input[type='password']")
            if password_input:
                password_input.fill(self.password)
                _human_delay(0.5, 1)
                page.keyboard.press("Enter")
                _human_delay(3, 5)

            return "indeed.com" in page.url and "login" not in page.url

        except Exception as exc:
            logger.error("[indeed] Login error: %s", exc)
            return False

    def _fill_form_step(self, page, cover_letter: str, job_location: str = "") -> None:
        """Fill visible form fields on current step."""
        try:
            # Name fields
            for field_name in ["applicant.name", "firstName", "first_name"]:
                el = page.query_selector(f"input[name='{field_name}']")
                if el and not el.input_value():
                    el.fill(self.personal.get("first_name", ""))
                    _human_delay(0.3, 0.6)

            for field_name in ["applicant.lastName", "lastName", "last_name"]:
                el = page.query_selector(f"input[name='{field_name}']")
                if el and not el.input_value():
                    el.fill(self.personal.get("last_name", ""))
                    _human_delay(0.3, 0.6)

            # Phone
            phone_el = page.query_selector("input[name*='phone']") or page.query_selector("input[type='tel']")
            if phone_el and not phone_el.input_value():
                phone_el.fill(self.personal.get("phone", ""))
                _human_delay(0.3, 0.6)

            # Resume upload
            file_input = page.query_selector("input[type='file']")
            if file_input and self.resume_path.exists():
                file_input.set_input_files(str(self.resume_path))
                _human_delay(1, 2)

            # Cover letter / message
            textarea = page.query_selector("textarea[name*='cover']") or page.query_selector("textarea")
            if textarea and not textarea.input_value():
                textarea.fill(cover_letter[:2000])
                _human_delay(0.5, 1)

            # Work authorization — location-aware
            work_auth = get_work_authorization(job_location, self.personal)
            for auth_name in ["workAuthorization", "work_authorization", "visa", "eligibility"]:
                el = page.query_selector(f"input[name*='{auth_name}']")
                if el and not el.input_value():
                    el.fill(work_auth)
                    _human_delay(0.3, 0.6)

            # Yes/No selects — default to "Yes" for basic eligibility questions
            selects = page.query_selector_all("select")
            for sel in selects:
                options = sel.query_selector_all("option")
                for opt in options:
                    if opt.inner_text().strip().lower() in ["yes", "true", "1"]:
                        sel.select_option(value=opt.get_attribute("value") or "")
                        _human_delay(0.2, 0.5)
                        break

        except Exception as exc:
            logger.debug("[indeed_apply] Form fill error: %s", exc)

    def _click_next_or_submit(self, page) -> bool:
        for label in ["Continue", "Next", "Submit", "Apply", "Review"]:
            try:
                btn = page.query_selector(f"button:has-text('{label}')")
                if btn and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    return True
            except Exception:
                pass
        return False

    def _check_submitted(self, page) -> bool:
        success_indicators = [
            "application submitted",
            "applied successfully",
            "your application has been sent",
            "thank you for applying",
        ]
        try:
            body_text = page.inner_text("body").lower()
            return any(phrase in body_text for phrase in success_indicators)
        except Exception:
            return False


def _human_delay(min_s: float = 1.5, max_s: float = 3.5) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _fail(reason: str) -> dict:
    logger.warning("[indeed_apply] %s", reason)
    return {"success": False, "status": "manual_required", "notes": reason}
