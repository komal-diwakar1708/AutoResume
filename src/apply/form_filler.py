"""
Generic AI-assisted form filler for employer ATS pages.

Used as a last-resort for job applications that don't have Easy Apply
but have a relatively simple HTML form on the company's own site.

Approach:
  - Find all visible input/textarea/select fields
  - Use field labels and names to infer what value to fill
  - Fall back to personal config values
"""

import logging
import random
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Cities/keywords that indicate a job is based in India
INDIA_LOCATIONS = {
    "india", "bengaluru", "bangalore", "pune", "mumbai", "delhi",
    "hyderabad", "chennai", "kolkata", "noida", "gurgaon", "gurugram",
    "ahmedabad", "jaipur", "kochi", "chandigarh",
}

# Common field name/label → config key mappings
# Note: "work_authorization" is handled separately via get_work_authorization()
FIELD_MAPPINGS: list[tuple[list[str], str]] = [
    (["first", "fname", "firstname", "given"],           "first_name"),
    (["last", "lname", "lastname", "surname", "family"], "last_name"),
    (["email", "e-mail"],                                "email"),
    (["phone", "mobile", "telephone", "tel"],            "phone"),
    (["linkedin", "linkedin_url", "linkedin profile"],   "linkedin_url"),
    (["portfolio", "website", "personal site"],          "portfolio_url"),
    (["location", "city", "current location"],           "current_location"),
    (["years", "experience", "yoe"],                     "years_of_experience"),
    (["notice", "notice period", "availability"],        "notice_period"),
]


def get_work_authorization(job_location: str, personal: dict) -> str:
    """
    Return the correct work authorization answer based on the job's location.
    - India-based jobs: candidate is an Indian citizen, no visa needed.
    - All other countries: visa sponsorship is required.
    """
    auth = personal.get("work_authorization", {})

    # Backward compat — if still a plain string, return it as-is
    if isinstance(auth, str):
        return auth

    location_lower = job_location.lower()
    if any(city in location_lower for city in INDIA_LOCATIONS):
        return auth.get("india", "Indian Citizen — authorized to work")
    return auth.get("international", "Requires Visa Sponsorship")


class GenericFormFiller:
    def __init__(self, config: dict, job_location: str = ""):
        self.personal = config.get("personal", {})
        self.resume_path = Path(config.get("resume_path", "resume/resume.pdf")).resolve()
        self.work_auth = get_work_authorization(job_location, self.personal)

    def fill(self, page, cover_letter: str = "") -> bool:
        """
        Fill all detectable form fields on the current page.
        Returns True if at least one field was filled.
        """
        filled_count = 0

        try:
            # Text/email/tel inputs
            inputs = page.query_selector_all(
                "input[type='text'], input[type='email'], input[type='tel'], input[type='number']"
            )
            for inp in inputs:
                if self._fill_input(page, inp):
                    filled_count += 1
                    time.sleep(random.uniform(0.2, 0.5))

            # File inputs (resume upload)
            file_inputs = page.query_selector_all("input[type='file']")
            for fi in file_inputs:
                if self.resume_path.exists():
                    try:
                        fi.set_input_files(str(self.resume_path))
                        filled_count += 1
                        time.sleep(random.uniform(0.8, 1.5))
                    except Exception as exc:
                        logger.debug("File upload failed: %s", exc)

            # Textareas (cover letter, additional info)
            textareas = page.query_selector_all("textarea")
            for ta in textareas:
                if not ta.input_value() and cover_letter:
                    try:
                        ta.fill(cover_letter[:2000])
                        filled_count += 1
                        time.sleep(random.uniform(0.3, 0.7))
                    except Exception:
                        pass

            # Yes/No radios — default to "Yes"
            radios = page.query_selector_all("input[type='radio']")
            for radio in radios:
                val = (radio.get_attribute("value") or "").lower()
                if val in ["yes", "true", "1"] and not radio.is_checked():
                    try:
                        radio.click()
                        filled_count += 1
                        time.sleep(random.uniform(0.2, 0.4))
                    except Exception:
                        pass

        except Exception as exc:
            logger.error("[form_filler] Error: %s", exc)

        logger.info("[form_filler] Filled %d fields", filled_count)
        return filled_count > 0

    def _fill_input(self, page, inp) -> bool:
        """Try to fill a single input based on its label/name/placeholder."""
        try:
            if inp.input_value():
                return False  # Already filled

            identifier = " ".join(filter(None, [
                inp.get_attribute("name") or "",
                inp.get_attribute("id") or "",
                inp.get_attribute("placeholder") or "",
                self._get_label_text(page, inp),
            ])).lower()

            # Work authorization is location-aware — handle separately
            auth_keywords = ["authorization", "work auth", "visa", "eligible to work", "right to work"]
            if any(kw in identifier for kw in auth_keywords):
                if self.work_auth:
                    inp.fill(self.work_auth)
                    return True

            for keywords, config_key in FIELD_MAPPINGS:
                if any(kw in identifier for kw in keywords):
                    value = str(self.personal.get(config_key, ""))
                    if value:
                        inp.fill(value)
                        return True

        except Exception as exc:
            logger.debug("[form_filler] Input fill error: %s", exc)
        return False

    def _get_label_text(self, page, inp) -> str:
        """Find the <label> associated with this input."""
        try:
            input_id = inp.get_attribute("id")
            if input_id:
                label = page.query_selector(f"label[for='{input_id}']")
                if label:
                    return label.inner_text().lower()
        except Exception:
            pass
        return ""
