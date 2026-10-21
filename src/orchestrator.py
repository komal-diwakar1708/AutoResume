"""
Main pipeline orchestrator.

Sequence for each run:
  1. Search all enabled sources → list[JobPosting]
  2. Filter + score → keep jobs above min_match_score, deduplicate vs DB
  3. For each new job (up to apply_limit_per_run):
     a. Generate personalised cover letter (OpenAI / fallback template)
     b. Attempt auto-apply (LinkedIn Easy Apply → Indeed Quick Apply)
     c. Find recruiter email (Hunter.io / description scrape)
     d. Send personalised email to recruiter
     e. Record everything in SQLite
  4. Print summary stats
"""

import logging
import time
from datetime import datetime
from typing import Optional

from src.search.base import JobPosting
from src.search.filter import filter_and_score
from src.db import tracker
from src.ai.cover_letter import generate_cover_letter
from src.apply.linkedin_apply import LinkedInApplier
from src.apply.indeed_apply import IndeedApplier
from src.email.finder import find_recruiter_email
from src.email.sender import send_recruiter_email

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.sources_cfg = config.get("sources", {})
        self.apply_limit = config.get("apply_limit_per_run", 10)
        self.email_outreach_enabled = config.get("email_outreach", {}).get("enabled", True)
        self._linkedin_applier: Optional[LinkedInApplier] = None
        self._indeed_applier: Optional[IndeedApplier] = None
        # Set after pre-flight; if False, LinkedIn applies are skipped
        self._linkedin_ready: Optional[bool] = None

    def run(self) -> dict:
        """Execute one full pipeline run. Returns a summary dict."""
        logger.info("=" * 60)
        logger.info("AutomateResume pipeline starting at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("=" * 60)

        tracker.init_db()

        # ── Step 1: Search ────────────────────────────────────────────────
        all_postings = self._search_all_sources()
        logger.info("Total raw results: %d", len(all_postings))

        # ── Step 2: Filter + Score ────────────────────────────────────────
        matched = filter_and_score(all_postings, self.config)
        logger.info("Matched jobs (after filter): %d", len(matched))

        # ── Step 3: Save matched jobs to DB ───────────────────────────────
        newly_inserted = 0
        for job in matched:
            if tracker.upsert_job(job.to_dict()):
                newly_inserted += 1
        logger.info("New jobs saved to DB: %d", newly_inserted)

        # ── Step 4: Process jobs — generate cover letters, queue for manual apply ──
        apply_count = 0
        attempt_count = 0
        email_count = 0
        manual_required = 0

        for job_posting in matched:
            if attempt_count >= self.apply_limit:
                logger.info("Processing limit (%d) reached — stopping", self.apply_limit)
                break

            attempt_count += 1
            job = job_posting.to_dict()
            logger.info(
                "\n[%d/%d] %s @ %s (score=%.2f, source=%s)",
                attempt_count, min(len(matched), self.apply_limit),
                job["title"], job["company"], job["match_score"], job["source"]
            )

            # Generate cover letter
            cover_letter = generate_cover_letter(
                job_title=job["title"],
                company=job["company"],
                job_description=job.get("description", ""),
                config=self.config,
            )

            # Queue as manual_required with cover letter saved
            manual_required += 1
            tracker.update_status(
                job["id"],
                "manual_required",
                cover_letter=cover_letter,
                notes="Open the job report to apply manually.",
            )

            # Recruiter email outreach
            if self.email_outreach_enabled:
                recruiter_email = find_recruiter_email(job)
                if recruiter_email:
                    success = send_recruiter_email(
                        to_email=recruiter_email,
                        job=job,
                        cover_letter=cover_letter,
                        config=self.config,
                    )
                    if success:
                        email_count += 1
                        tracker.update_status(
                            job["id"],
                            "emailed",
                            emailed_at=datetime.now().isoformat(),
                            recruiter_email=recruiter_email,
                        )

        # ── Summary ───────────────────────────────────────────────────────
        summary = {
            "total_found": len(all_postings),
            "total_matched": len(matched),
            "newly_inserted": newly_inserted,
            "applied": apply_count,
            "emailed": email_count,
            "manual_required": manual_required,
            "db_stats": tracker.get_stats(),
        }
        self._print_summary(summary)

        # Generate HTML job report
        try:
            from src.report import generate_report
            report_path = generate_report()
            logger.info("Job report saved → %s", report_path)
            logger.info("Opening report in browser...")
            import subprocess
            subprocess.run(["open", str(report_path)], check=False)
        except Exception as exc:
            logger.warning("Could not generate report: %s", exc)

        return summary

    def _search_all_sources(self) -> list[JobPosting]:
        postings: list[JobPosting] = []

        if self.sources_cfg.get("jsearch", True):
            postings.extend(self._safe_search("jsearch"))

        if self.sources_cfg.get("linkedin", True):
            postings.extend(self._safe_search("linkedin"))

        if self.sources_cfg.get("indeed", True):
            postings.extend(self._safe_search("indeed"))

        if self.sources_cfg.get("seek", True):
            postings.extend(self._safe_search("seek"))

        if self.sources_cfg.get("stepstone", True):
            postings.extend(self._safe_search("stepstone"))

        if self.sources_cfg.get("mycareersfuture", True):
            postings.extend(self._safe_search("mycareersfuture"))

        if self.sources_cfg.get("efinancialcareers", False):
            postings.extend(self._safe_search("efinancialcareers"))

        if self.sources_cfg.get("wantedly", False):
            postings.extend(self._safe_search("wantedly"))

        # Global URL-level dedup across all sources
        seen: set[str] = set()
        unique: list[JobPosting] = []
        for p in postings:
            if p.url not in seen:
                seen.add(p.url)
                unique.append(p)

        return unique

    def _safe_search(self, source: str) -> list[JobPosting]:
        """Run a searcher, returning empty list on any failure."""
        try:
            searcher = self._get_searcher(source)
            if searcher is None:
                return []
            results = searcher.search_all()
            logger.info("[%s] Returned %d results", source, len(results))
            return results
        except Exception as exc:
            logger.error("[%s] Search failed: %s", source, exc)
            return []

    def _get_searcher(self, source: str):
        if source == "jsearch":
            from src.search.jsearch import JSearchSearcher
            return JSearchSearcher(self.config)
        elif source == "linkedin":
            from src.search.linkedin import LinkedInSearcher
            return LinkedInSearcher(self.config)
        elif source == "indeed":
            from src.search.indeed import IndeedSearcher
            return IndeedSearcher(self.config)
        elif source == "seek":
            from src.search.seek import SeekSearcher
            return SeekSearcher(self.config)
        elif source == "stepstone":
            from src.search.stepstone import StepStoneSearcher
            return StepStoneSearcher(self.config)
        elif source == "mycareersfuture":
            from src.search.mycareersfuture import MyCareersFutureSearcher
            return MyCareersFutureSearcher(self.config)
        elif source == "efinancialcareers":
            from src.search.efinancialcareers import EFinancialCareersSearcher
            return EFinancialCareersSearcher(self.config)
        elif source == "wantedly":
            from src.search.wantedly import WantedlySearcher
            return WantedlySearcher(self.config)
        return None

    def _preflight_linkedin(self, matched: list[JobPosting]) -> None:
        """
        Run LinkedIn auth bootstrap ONCE if any LinkedIn job is queued.
        Caches result so per-job applies don't re-prompt.
        """
        has_linkedin = any(
            (p.source == "linkedin" or "linkedin.com" in (p.url or ""))
            for p in matched[: self.apply_limit]
        )
        if not has_linkedin:
            self._linkedin_ready = False
            return

        if self._linkedin_applier is None:
            self._linkedin_applier = LinkedInApplier(self.config)

        logger.info("Pre-flight: verifying LinkedIn session (one-time check)...")
        self._linkedin_ready = self._linkedin_applier.ensure_authenticated()

        if self._linkedin_ready:
            logger.info("LinkedIn session ready.")
        else:
            logger.warning(
                "LinkedIn session unavailable — LinkedIn jobs will be queued for manual apply. "
                "Run `python main.py --linkedin-login` to fix."
            )

    def _attempt_apply(self, job: dict, cover_letter: str) -> dict:
        """Try LinkedIn Easy Apply first, then Indeed Quick Apply."""
        source = job.get("source", "")
        url = job.get("url", "")
        is_linkedin = source == "linkedin" or "linkedin.com" in url
        is_indeed = source == "indeed" or "indeed.com" in url

        if is_linkedin:
            if not self._linkedin_ready:
                return {
                    "success": False,
                    "status": "manual_required",
                    "notes": f"LinkedIn session not available. Apply manually at: {url}",
                }
            if self._linkedin_applier is None:
                self._linkedin_applier = LinkedInApplier(self.config)
            return self._linkedin_applier.apply(job, cover_letter)

        if is_indeed:
            if self._indeed_applier is None:
                self._indeed_applier = IndeedApplier(self.config)
            return self._indeed_applier.apply(job, cover_letter)

        # Sources without auto-apply support (JSearch aggregator, Seek, StepStone)
        return {
            "success": False,
            "status": "manual_required",
            "notes": f"Auto-apply not implemented for source '{source}'. Apply manually at: {url}",
        }

    def _print_summary(self, summary: dict) -> None:
        logger.info("\n" + "=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)
        logger.info("Jobs found (all sources):  %d", summary["total_found"])
        logger.info("Jobs matched (filtered):   %d", summary["total_matched"])
        logger.info("New jobs added to DB:       %d", summary["newly_inserted"])
        logger.info("Applications submitted:    %d", summary["applied"])
        logger.info("Recruiter emails sent:     %d", summary["emailed"])
        logger.info("Manual review required:    %d", summary["manual_required"])
        logger.info("\nAll-time DB stats:")
        for status, count in summary["db_stats"].items():
            logger.info("  %-20s %d", status, count)
        logger.info("=" * 60)

        try:
            from tabulate import tabulate
            rows = [[s, c] for s, c in summary["db_stats"].items()]
            print("\n" + tabulate(rows, headers=["Status", "Count"], tablefmt="rounded_outline"))
        except ImportError:
            pass
