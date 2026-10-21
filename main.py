#!/usr/bin/env python3
"""
AutomateResume — Automated Job Application System
==================================================
Usage:
  python main.py                  # Run once immediately
  python main.py --schedule       # Run now + repeat every N hours (set in settings.yaml)
  python main.py --stats          # Show application stats only
  python main.py --list-jobs      # Print all tracked jobs
  python main.py --manual         # List jobs that need manual review/apply
  python main.py --linkedin-login # Save LinkedIn cookies (run this FIRST before main run)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import schedule
import time
import yaml
from dotenv import load_dotenv

# ── Setup paths ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Load .env secrets ─────────────────────────────────────────────────────────
load_dotenv(ROOT / ".env")

# ── Logging setup ─────────────────────────────────────────────────────────────
log_dir = ROOT / "logs"
log_dir.mkdir(exist_ok=True)

try:
    import colorlog
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
        datefmt="%H:%M:%S",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        }
    ))
except ImportError:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

file_handler = logging.FileHandler(log_dir / "automate_resume.log")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler, file_handler],
)
logger = logging.getLogger("automate_resume")


def load_config() -> dict:
    config_path = ROOT / "config" / "settings.yaml"
    if not config_path.exists():
        logger.error("Config not found: %s", config_path)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def run_pipeline(config: dict) -> None:
    from src.orchestrator import Orchestrator
    orchestrator = Orchestrator(config)
    orchestrator.run()


def show_stats() -> None:
    from src.db import tracker
    tracker.init_db()
    stats = tracker.get_stats()
    if not stats:
        print("No jobs tracked yet. Run the pipeline first.")
        return
    try:
        from tabulate import tabulate
        rows = [[s.upper(), c] for s, c in sorted(stats.items())]
        total = sum(stats.values())
        rows.append(["TOTAL", total])
        print("\n" + tabulate(rows, headers=["Status", "Count"], tablefmt="rounded_outline"))
    except ImportError:
        for status, count in stats.items():
            print(f"  {status:<25} {count}")


def list_jobs(status_filter: str = None) -> None:
    from src.db import tracker
    tracker.init_db()
    jobs = tracker.get_all_jobs() if not status_filter else tracker.get_jobs_by_status(status_filter)
    if not jobs:
        print(f"No jobs found{' with status: ' + status_filter if status_filter else ''}.")
        return
    try:
        from tabulate import tabulate
        rows = [
            [
                j["title"][:40],
                j["company"][:25],
                j["location"][:20],
                j["source"],
                f"{j['match_score']:.2f}",
                j["status"],
                (j["created_at"] or "")[:10],
            ]
            for j in jobs
        ]
        print("\n" + tabulate(
            rows,
            headers=["Title", "Company", "Location", "Source", "Score", "Status", "Found"],
            tablefmt="rounded_outline"
        ))
    except ImportError:
        for j in jobs:
            print(f"{j['status']:20} {j['title']} @ {j['company']} ({j['location']})")


def list_manual_jobs() -> None:
    """Detailed view of jobs needing manual application — full URLs and reasons."""
    from src.db import tracker
    tracker.init_db()
    jobs = tracker.get_jobs_by_status("manual_required")
    if not jobs:
        print("No jobs need manual application. Great!")
        return

    print(f"\n {len(jobs)} job(s) need manual application:\n")
    print("─" * 80)
    for i, j in enumerate(jobs, 1):
        print(f"\n[{i}] {j['title']}")
        print(f"    Company:  {j['company']}")
        print(f"    Location: {j['location']}")
        print(f"    Source:   {j['source']}  (score {j['match_score']:.2f})")
        print(f"    URL:      {j['url']}")
        if j.get("notes"):
            print(f"    Reason:   {j['notes']}")
        print("─" * 80)
    print(f"\n Tip: run `python main.py --export-manual` to save this as a CSV.")


def export_manual_jobs() -> None:
    """Export manual_required jobs to a CSV file for easy review in Excel/Sheets."""
    import csv
    from src.db import tracker
    tracker.init_db()
    jobs = tracker.get_jobs_by_status("manual_required")
    if not jobs:
        print("No jobs need manual application.")
        return

    out_path = ROOT / "data" / "manual_jobs.csv"
    fieldnames = ["title", "company", "location", "source", "match_score", "url", "notes", "created_at"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for j in jobs:
            writer.writerow(j)
    print(f" Exported {len(jobs)} jobs to {out_path}")
    print(f" Open it with: open {out_path}")


def check_setup() -> bool:
    """Verify critical files/env vars before running."""
    issues = []

    config_path = ROOT / "config" / "settings.yaml"
    if not config_path.exists():
        issues.append("config/settings.yaml not found")

    # Read the resume path from config rather than hardcoding it
    resume_rel = "resume/resume.pdf"
    if config_path.exists():
        try:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            resume_rel = cfg.get("resume_path", resume_rel)
        except Exception:
            pass
    resume_path = ROOT / resume_rel
    if not resume_path.exists():
        issues.append(f"{resume_rel} not found — place your resume PDF here before running")

    env_path = ROOT / ".env"
    if not env_path.exists():
        issues.append(".env file not found — copy .env.example to .env and fill in your API keys")
    else:
        # Only check credentials for sources/features that are actually enabled.
        # JSearch and OpenAI are optional — system works without them.
        for key in ["EMAIL_ADDRESS", "EMAIL_APP_PASSWORD"]:
            if not os.getenv(key):
                issues.append(f"{key} not set in .env")

    if issues:
        print("\n Setup issues detected:")
        for issue in issues:
            print(f"  ✗ {issue}")
        print()
        return False

    print(" Setup looks good!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="AutomateResume — Automated Job Application System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--schedule", action="store_true", help="Run on a recurring schedule")
    parser.add_argument("--stats", action="store_true", help="Show application statistics")
    parser.add_argument("--list-jobs", action="store_true", help="List all tracked jobs")
    parser.add_argument("--manual", action="store_true", help="List jobs needing manual apply")
    parser.add_argument("--check", action="store_true", help="Check setup and credentials")
    parser.add_argument("--no-check", action="store_true", help="Skip setup check")
    parser.add_argument("--linkedin-login", action="store_true", help="Capture LinkedIn session via browser")
    parser.add_argument("--import-cookies", metavar="FILE", help="Import LinkedIn cookies exported from Cookie-Editor Chrome extension")
    parser.add_argument("--extract-chrome-cookies", action="store_true", help="Extract LinkedIn cookies directly from Chrome (includes httpOnly cookies)")
    parser.add_argument("--clear-linkedin-session", action="store_true", help="Delete the saved LinkedIn session file")
    parser.add_argument("--export-manual", action="store_true", help="Export manual_required jobs to CSV")
    parser.add_argument("--report", action="store_true", help="Generate/open the HTML job report from the database")

    args = parser.parse_args()

    if args.clear_linkedin_session:
        from src.apply.linkedin_apply import STATE_PATH
        if STATE_PATH.exists():
            STATE_PATH.unlink()
            print(f"Deleted {STATE_PATH}")
        else:
            print("No saved LinkedIn session to clear.")
        return

    if args.import_cookies:
        from src.apply.linkedin_apply import LinkedInApplier
        LinkedInApplier.import_cookies_from_file(args.import_cookies)
        return

    if args.extract_chrome_cookies:
        from src.apply.linkedin_apply import LinkedInApplier
        LinkedInApplier.extract_from_chrome()
        return

    if getattr(args, "report", False):
        from src.report import generate_report
        import subprocess
        path = generate_report()
        print(f"Report saved: {path}")
        try:
            subprocess.run(["open", str(path)], check=False)
        except Exception:
            print(f"Open it manually: file://{path}")
        return

    if args.stats:
        show_stats()
        return

    if args.list_jobs:
        list_jobs()
        return

    if args.manual:
        list_manual_jobs()
        return

    if args.export_manual:
        export_manual_jobs()
        return

    if args.check:
        check_setup()
        return

    if args.linkedin_login:
        from src.apply.linkedin_apply import LinkedInApplier
        config = load_config()
        LinkedInApplier(config).save_cookies_interactively()
        return

    # Validate setup before running
    if not args.no_check and not check_setup():
        print("Fix the issues above, then run again.\n")
        print("Quick start:")
        print("  1. cp .env.example .env  (then fill in your API keys)")
        print("  2. Place your resume at the path set in config/settings.yaml (resume_path)")
        print("  3. Edit:                  config/settings.yaml")
        print("  4. Run:                   python main.py\n")
        sys.exit(1)

    config = load_config()

    if args.schedule:
        interval_hours = config.get("schedule", {}).get("run_every_hours", 12)
        if interval_hours <= 0:
            interval_hours = 12

        logger.info("Scheduled mode: running every %d hours", interval_hours)
        run_pipeline(config)  # Run immediately on start

        schedule.every(interval_hours).hours.do(run_pipeline, config=config)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_pipeline(config)


if __name__ == "__main__":
    main()
