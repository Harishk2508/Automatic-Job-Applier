"""
Master Orchestrator
Chains: Scraper → JD Extractor → Resume Tailor → Auto Applicator → Email Report
All FREE tools: Playwright + Groq API (free tier) + ReportLab + Gmail SMTP
"""

import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Configure logging
LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file FIRST before anything else
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

# Fix Windows Unicode encoding issue
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", mode="a"),
    ],
)
logger = logging.getLogger("orchestrator")

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"


def check_env():
    issues = []
    has_gemini = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    if not has_gemini:
        issues.append("GEMINI_API_KEY not set -> resume tailoring will use base resume only")
    if not os.environ.get("GROQ_API_KEY"):
        issues.append("GROQ_API_KEY not set -> applicator Q&A fallback disabled (non-critical)")
    if not os.environ.get("GMAIL_APP_PASSWORD"):
        issues.append("GMAIL_APP_PASSWORD not set -> email report will be saved locally only")
    for issue in issues:
        logger.warning(f"[WARN] {issue}")
    return has_gemini  # Only GEMINI_API_KEY is truly required


def run_pipeline(dry_run: bool = False):
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=" * 60)
    logger.info(f"JOBBOT PIPELINE | run={run_id} | dry_run={dry_run}")
    logger.info("=" * 60)

    if not check_env():
        logger.error("Missing required env vars. Aborting.")
        return

    summary = {
        "run_id": run_id,
        "started_at": datetime.now().isoformat(),
        "scraped": 0,
        "jds_extracted": 0,
        "tailored": 0,
        "reused": 0,
        "applied": 0,
        "failed": 0,
        "skipped": 0,
        "stages": {},
    }

    # ── Stage 1: Scrape ──────────────────────────────────────────────────────
    logger.info("\n[STAGE 1] Scraping jobs (Playwright)")
    jobs = []
    try:
        sys.path.insert(0, str(BASE_DIR))
        from agents.scraper import JobScraper
        scraper = JobScraper(data_dir=str(DATA_DIR))
        jobs = scraper.run()
        summary["scraped"] = len(jobs)
        summary["stages"]["scraper"] = {"count": len(jobs), "status": "ok"}
        logger.info(f"Stage 1: {len(jobs)} fresher jobs scraped")
    except Exception as e:
        logger.error(f"Stage 1 failed: {e}")
        summary["stages"]["scraper"] = {"status": "error", "error": str(e)}

    if not jobs:
        logger.warning("No jobs found. Pipeline ending.")
        _save_summary(summary, run_id)
        return summary

    # ── Stage 2: JD Extraction ───────────────────────────────────────────────
    logger.info(f"\n[STAGE 2] Extracting JDs for {len(jobs)} jobs")
    jobs_with_jd = []
    try:
        from agents.jd_extractor import JDExtractor
        extractor = JDExtractor(data_dir=str(DATA_DIR))
        jobs_with_jd = extractor.run(jobs)
        summary["jds_extracted"] = len(jobs_with_jd)
        summary["stages"]["jd_extractor"] = {"count": len(jobs_with_jd), "status": "ok"}
        logger.info(f"Stage 2: {len(jobs_with_jd)} JDs extracted")
    except Exception as e:
        logger.error(f"Stage 2 failed: {e}")
        summary["stages"]["jd_extractor"] = {"status": "error", "error": str(e)}
        jobs_with_jd = jobs  # use raw jobs as fallback

    # ── Stage 3: Resume Tailoring ─────────────────────────────────────────────
    logger.info(f"\n[STAGE 3] Tailoring resumes (Gemini 2.0 Flash - FREE)")
    resume_results = []
    try:
        from agents.resume_tailor import ResumeTailor
        tailor = ResumeTailor(config_dir=str(CONFIG_DIR), data_dir=str(DATA_DIR))
        resume_results = tailor.run(jobs_with_jd)
        tailored = sum(1 for r in resume_results if r["status"] == "tailored")
        reused = sum(1 for r in resume_results if r["status"] == "reused")
        summary["tailored"] = tailored
        summary["reused"] = reused
        summary["stages"]["resume_tailor"] = {"tailored": tailored, "reused": reused, "status": "ok"}
        logger.info(f"Stage 3: {tailored} tailored + {reused} reused resumes")
    except Exception as e:
        logger.error(f"Stage 3 failed: {e}")
        summary["stages"]["resume_tailor"] = {"status": "error", "error": str(e)}

    if not resume_results:
        logger.warning("No resumes. Pipeline ending.")
        _save_summary(summary, run_id)
        return summary

    # ── Stage 4: Apply ────────────────────────────────────────────────────────
    if dry_run:
        logger.info("\n[STAGE 4] Skipped (dry_run=True) — resumes are ready")
        summary["stages"]["applicator"] = {"status": "skipped_dry_run"}
    else:
        logger.info(f"\n[STAGE 4] Auto-applying to {len(resume_results)} jobs")
        app_results = []
        session_applied = []
        try:
            from agents.applicator import ApplicationAgent
            applicator = ApplicationAgent(config_dir=str(CONFIG_DIR), data_dir=str(DATA_DIR))
            app_results = applicator.run(resume_results)
            session_applied = applicator.get_session_applied()

            applied = sum(1 for r in app_results if r["status"] == "applied")
            failed = sum(1 for r in app_results if r["status"] == "failed")
            skipped = sum(1 for r in app_results if "skip" in r["status"])
            summary["applied"] = applied
            summary["failed"] = failed
            summary["skipped"] = skipped
            summary["stages"]["applicator"] = {
                "applied": applied, "failed": failed, "skipped": skipped, "status": "ok"
            }
            logger.info(f"Stage 4: {applied} applied | {failed} failed | {skipped} skipped")
        except Exception as e:
            logger.error(f"Stage 4 failed: {e}")
            summary["stages"]["applicator"] = {"status": "error", "error": str(e)}
            session_applied = []

        # ── Stage 5: Email Report ─────────────────────────────────────────────
        logger.info("\n[STAGE 5] Sending email report")
        try:
            from agents.email_reporter import send_report, save_report_locally
            email_sent = send_report(session_applied, summary)
            report_path = save_report_locally(session_applied, summary, str(DATA_DIR))
            summary["stages"]["email"] = {
                "sent": email_sent,
                "local_report": report_path,
                "status": "ok",
            }
            if email_sent:
                logger.info(f"✓ Email report sent to {summary.get('notification_email','harishknlpengineer25@gmail.com')}")
            else:
                logger.info(f"✓ HTML report saved locally: {report_path}")
        except Exception as e:
            logger.error(f"Email report error: {e}")

    # ── Final ─────────────────────────────────────────────────────────────────
    summary["completed_at"] = datetime.now().isoformat()
    _save_summary(summary, run_id)

    logger.info("\n" + "=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Scraped: {summary['scraped']} | JDs: {summary['jds_extracted']}")
    logger.info(f"  Resumes: {summary['tailored']} tailored + {summary['reused']} reused")
    logger.info(f"  Applied: {summary['applied']} | Failed: {summary['failed']}")
    logger.info("=" * 60)

    return summary


def _save_summary(summary: dict, run_id: str):
    p = DATA_DIR / "logs" / f"run_{run_id}.json"
    p.parent.mkdir(exist_ok=True)
    with open(p, "w") as f:
        json.dump(summary, f, indent=2)


def schedule(interval_hours: int = 12):
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler = BlockingScheduler()
        scheduler.add_job(run_pipeline, "interval", hours=interval_hours, id="jobbot")
        logger.info(f"Scheduler active: runs every {interval_hours}h")
        run_pipeline()  # immediate first run
        scheduler.start()
    except ImportError:
        logger.warning("APScheduler not found. Running once.")
        run_pipeline()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="JobBot Orchestrator")
    p.add_argument("--dry-run", action="store_true", help="Scrape + tailor only, no applications")
    p.add_argument("--schedule", type=int, default=0, help="Run every N hours (0=once)")
    args = p.parse_args()

    if args.schedule > 0:
        schedule(args.schedule)
    else:
        run_pipeline(dry_run=args.dry_run)
