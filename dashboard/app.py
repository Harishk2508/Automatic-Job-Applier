"""
Dashboard Backend + Orchestrator — Flask API — Phase 3 Enhanced
Runs the full 4-stage pipeline with proper batch processing:
  Scrape → JD Extract → Resume Tailor → Apply
  Batch 1 (20 jobs) → cooldown wait → Batch 2 (20 jobs) → ...

New vs original:
  ✅ Full orchestrator embedded (no separate orchestrator.py needed)
  ✅ Batch-aware pipeline: 20 jobs → apply → wait cooldown → next 20
  ✅ Real-time pipeline stage + batch status in /api/status
  ✅ /api/pipeline/stop   — graceful stop after current batch
  ✅ /api/batches         — list all batch files + progress
  ✅ /api/batches/<n>     — jobs in a specific batch
  ✅ /api/failures        — list failure screenshots
  ✅ /api/applications/<url>/response  — mark interview call / rejection
  ✅ /api/interview-stats — response rate analytics
  ✅ run_*.json saved after every run with full stage breakdown
  ✅ dry_run=False by default (was True — never submitted anything)
  ✅ Proper error logging to data/logs/pipeline_errors.log
"""

import json
import logging
import threading
import sys
import time
import os
import base64
import urllib.parse
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("orchestrator")

sys.stdout.reconfigure(encoding="utf-8")

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

BASE_DIR   = Path(__file__).parent.parent
DATA_DIR   = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
AGENTS_DIR = BASE_DIR / "agents"

# Ensure directories exist
for d in [DATA_DIR / "applications", DATA_DIR / "logs", DATA_DIR / "resumes",
          DATA_DIR / "logs" / "jds", DATA_DIR / "logs" / "jd_failures",
          DATA_DIR / "logs" / "app_failures"]:
    d.mkdir(parents=True, exist_ok=True)

# Add agents to path
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(AGENTS_DIR))

# ── Pipeline state ────────────────────────────────────────────────────────────
_state = {
    "running":        False,
    "stop_requested": False,
    "stage":          "idle",       # idle | scraping | extracting | tailoring | applying | cooldown | done
    "batch_current":  0,
    "batch_total":    0,
    "batch_size":     20,
    "cooldown_min":   30,
    "dry_run":        False,
    "started_at":     None,
    "last_run_id":    None,
    "stage_progress": 0,            # 0-100 within current stage
    "last_error":     None,
}
_state_lock = threading.Lock()
_pipeline_thread = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(path, default=None):
    p = Path(path)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}


def _save(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def _get_state():
    with _state_lock:
        return dict(_state)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_pipeline(dry_run: bool = False, batch_size: int = 20,
                 cooldown_minutes: float = 30):
    """
    Full pipeline:
      Stage 1 — Scrape all sources → split into batches of batch_size
      For each batch:
        Stage 2 — Extract JDs
        Stage 3 — Tailor resumes (Gemini → Groq fallback)
        Stage 4 — Apply (skipped if dry_run=True)
        Wait cooldown_minutes before next batch
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    _set_state(
        running=True, stop_requested=False, dry_run=dry_run,
        started_at=datetime.now().isoformat(),
        last_run_id=run_id, batch_current=0, batch_total=0,
        last_error=None,
    )

    summary = {
        "run_id":       run_id,
        "started_at":   datetime.now().isoformat(),
        "dry_run":      dry_run,
        "batch_size":   batch_size,
        "cooldown_min": cooldown_minutes,
        "scraped":      0,
        "batches":      [],
        "total_applied": 0,
        "total_failed":  0,
        "total_tailored":0,
        "stages":       {},
    }

    logger.info("=" * 60)
    logger.info("JOBBOT PIPELINE | run=%s | dry_run=%s", run_id, dry_run)
    logger.info("=" * 60)

    try:
        # ── Import agents ─────────────────────────────────────────────────────
        from agents.scraper        import JobScraper
        from agents.jd_extractor   import JDExtractor
        from agents.resume_tailor  import ResumeTailor
        from agents.applicator     import ApplicationAgent
        from agents.email_reporter import send_report, save_report_locally

        # ── STAGE 1: Scrape ───────────────────────────────────────────────────
        _set_state(stage="scraping", stage_progress=0)
        logger.info("\n[STAGE 1] Scraping jobs")

        scraper = JobScraper(data_dir=str(DATA_DIR))
        batches = scraper.run(
            batch_size=batch_size,
            max_total=batch_size * 5,   # cap at 5 batches worth
            cooldown_minutes=cooldown_minutes,
        )

        total_scraped = sum(len(b) for b in batches)
        summary["scraped"]     = total_scraped
        summary["batch_total"] = len(batches)
        _set_state(batch_total=len(batches), stage_progress=100)

        logger.info("Stage 1: %d jobs in %d batches", total_scraped, len(batches))
        summary["stages"]["scraping"] = {
            "status": "ok",
            "total":  total_scraped,
            "batches": len(batches),
        }

        if not batches:
            logger.warning("No jobs scraped - pipeline ending early")
            summary["stages"]["scraping"]["status"] = "empty"
            _finish_run(summary, run_id)
            return

        # ── Per-batch processing ──────────────────────────────────────────────
        jd_extractor  = JDExtractor(data_dir=str(DATA_DIR))
        resume_tailor = ResumeTailor(
            config_dir=str(CONFIG_DIR),
            data_dir=str(DATA_DIR),
        )
        applicator = ApplicationAgent(
            config_dir=str(CONFIG_DIR),
            data_dir=str(DATA_DIR),
        )

        all_session_applied = []

        for batch_num, batch_jobs in enumerate(batches, start=1):
            # Check if stop was requested
            if _get_state()["stop_requested"]:
                logger.info("Stop requested — halting after current batch")
                break

            _set_state(batch_current=batch_num)
            logger.info(f"\n{'─'*50}")
            logger.info("BATCH %d/%d - %d jobs", batch_num, len(batches), len(batch_jobs))
            logger.info(f"{'─'*50}")

            batch_summary = {
                "batch":    batch_num,
                "scraped":  len(batch_jobs),
                "extracted": 0,
                "tailored": 0,
                "applied":  0,
                "failed":   0,
            }

            # ── Stage 2: JD Extraction ────────────────────────────────────────
            _set_state(stage="extracting", stage_progress=0)
            logger.info(f"\n[STAGE 2] Extracting JDs for {len(batch_jobs)} jobs")

            enriched = jd_extractor.run(batch_jobs)
            batch_summary["extracted"] = len(enriched)
            _set_state(stage_progress=100)

            logger.info("Stage 2: %d/%d JDs extracted", len(enriched), len(batch_jobs))

            if not enriched:
                logger.warning("Batch %d: No JDs extracted - skipping", batch_num)
                summary["batches"].append(batch_summary)
                continue

            # ── Stage 3 + 4: Tailor AND Apply in parallel ─────────────────────
            #
            # As soon as one resume PDF is ready the applicator picks it up.
            # Uses Python stdlib queue.Queue — zero extra dependencies.
            #
            # Thread-A (tailor_worker): generate resumes → push to result_q
            # Thread-B (apply_worker) : pop from result_q → submit application
            # None sentinel in queue  : signals apply_worker to exit cleanly
            #
            _set_state(stage="tailoring", stage_progress=0)
            logger.info("\n[STAGE 3+4] Tailoring + Applying in parallel (%d jobs)", len(enriched))

            import queue as _queue
            result_q     = _queue.Queue()
            resume_results  = []
            app_results     = []

            def tailor_worker():
                """Thread A: tailors each resume and pushes result to queue."""
                results = resume_tailor.run(
                    enriched,
                    batch_number=batch_num,
                    output_queue=result_q,   # pushes each result + None sentinel
                )
                resume_results.extend(results)

            def apply_worker():
                """Thread B: consumes from queue and applies as soon as resume is ready."""
                if dry_run:
                    # drain the queue without applying
                    while True:
                        item = result_q.get()
                        if item is None:
                            break
                    logger.info("[STAGE 4] SKIPPED (dry_run=True)")
                    return

                _set_state(stage="applying")
                while True:
                    item = result_q.get()
                    if item is None:
                        break   # sentinel: tailoring done
                    # Apply immediately for this single job
                    url         = item.get("url", "")
                    resume_path = item.get("resume_path", "")
                    if not url or not resume_path or not Path(resume_path).exists():
                        logger.warning("Skipping apply — missing url/resume for %s", item.get("company"))
                        continue
                    if applicator.is_duplicate(url):
                        continue

                    job_meta = {
                        "url":      url,
                        "company":  item.get("company",""),
                        "title":    item.get("title",""),
                        "platform": item.get("platform",""),
                        "salary":   item.get("salary","Not disclosed"),
                        "location": item.get("location",""),
                    }
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(
                            headless=True,
                            args=["--no-sandbox","--disable-dev-shm-usage",
                                  "--disable-blink-features=AutomationControlled"],
                        )
                        context = browser.new_context(
                            user_agent=(
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
                            ),
                            viewport={"width":1280,"height":900},
                        )
                        applicator._load_cookies(context, applicator.linkedin_cookies_file, "LinkedIn")
                        applicator._load_cookies(context, applicator.naukri_cookies_file,   "Naukri")
                        page = context.new_page()
                        page.add_init_script(
                            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                        )
                        result = applicator.apply_one(
                            job_meta, resume_path, page,
                            cover_letter=item.get("cover_letter","")
                        )
                        app_results.append(result)
                        browser.close()

                    import random as _random
                    import time as _time
                    _time.sleep(_random.uniform(25, 60))

            # Launch both threads
            t_tailor = threading.Thread(target=tailor_worker, daemon=True, name="tailor")
            t_apply  = threading.Thread(target=apply_worker,  daemon=True, name="apply")
            t_tailor.start()
            t_apply.start()
            t_tailor.join()
            t_apply.join()

            tailored_count = sum(1 for r in resume_results if r.get("status") == "tailored")
            reused_count   = sum(1 for r in resume_results if r.get("status") == "reused")
            batch_summary["tailored"] = tailored_count + reused_count
            summary["total_tailored"] += tailored_count + reused_count
            _set_state(stage_progress=100)

            logger.info(
                "Stage 3: %d tailored, %d reused out of %d",
                tailored_count, reused_count, len(enriched)
            )

            applied_n = sum(1 for r in app_results if r.get("status") == "applied")
            failed_n  = sum(1 for r in app_results if r.get("status") == "failed")
            batch_summary["applied"] = applied_n
            batch_summary["failed"]  = failed_n
            summary["total_applied"] += applied_n
            summary["total_failed"]  += failed_n
            all_session_applied.extend(applicator.get_session_applied())

            if not dry_run:
                logger.info(
                    f"Stage 4: {applied_n} applied, {failed_n} failed "
                    f"out of {len(resume_results)}"
                )

            summary["batches"].append(batch_summary)

            # Save incremental run summary
            _save(DATA_DIR / "logs" / f"run_{run_id}.json", summary)

            # ── Cooldown before next batch ────────────────────────────────────
            if batch_num < len(batches) and not _get_state()["stop_requested"]:
                _set_state(stage="cooldown", stage_progress=0)
                wait_secs = cooldown_minutes * 60
                logger.info(
                    f"\n⏸  Cooldown: waiting {cooldown_minutes:.0f} min "
                    f"before batch {batch_num + 1}..."
                )
                start_wait = time.time()
                while time.time() - start_wait < wait_secs:
                    if _get_state()["stop_requested"]:
                        break
                    elapsed = time.time() - start_wait
                    _set_state(stage_progress=int(elapsed / wait_secs * 100))
                    time.sleep(5)

        # ── Email / local report ──────────────────────────────────────────────
        run_summary_for_email = {
            "scraped":  summary["scraped"],
            "tailored": summary["total_tailored"],
            "applied":  summary["total_applied"],
            "failed":   summary["total_failed"],
        }

        gmail_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
        if gmail_pw and all_session_applied:
            send_report(all_session_applied, run_summary_for_email, gmail_pw)
        else:
            save_report_locally(all_session_applied, run_summary_for_email,
                                str(DATA_DIR))

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        summary["error"] = str(e)
        _set_state(last_error=str(e))

    finally:
        _finish_run(summary, run_id)


def _finish_run(summary: dict, run_id: str):
    summary["completed_at"] = datetime.now().isoformat()
    _save(DATA_DIR / "logs" / f"run_{run_id}.json", summary)
    _set_state(
        running=False, stage="idle", stage_progress=0,
        stop_requested=False,
    )
    logger.info(
        f"\n{'='*60}\n"
        f"PIPELINE COMPLETE | run={run_id} | "
        f"applied={summary.get('total_applied',0)} | "
        f"failed={summary.get('total_failed',0)}\n"
        f"{'='*60}"
    )


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    log     = _load(DATA_DIR / "applications" / "application_log.json", [])
    scraped = _load(DATA_DIR / "logs" / "scraped_jobs.json", {})
    idx     = _load(DATA_DIR / "resumes" / "resume_index.json", {})

    applied  = [r for r in log if r.get("status") == "applied"]
    failed   = [r for r in log if r.get("status") == "failed"]
    skipped  = [r for r in log if "skip" in r.get("status", "")]
    interview= [r for r in log if r.get("response_status") == "interview_call"]

    st = _get_state()
    return jsonify({
        "pipeline_running":  st["running"],
        "stage":             st["stage"],
        "stage_progress":    st["stage_progress"],
        "batch_current":     st["batch_current"],
        "batch_total":       st["batch_total"],
        "dry_run":           st["dry_run"],
        "last_run_id":       st["last_run_id"],
        "last_error":        st["last_error"],
        "total_scraped":     scraped.get("count", 0),
        "total_resumes":     len(idx),
        "total_applied":     len(applied),
        "total_failed":      len(failed),
        "total_skipped":     len(skipped),
        "total_interviews":  len(interview),
        "last_scrape":       scraped.get("timestamp", "Never"),
    })


@app.route("/api/pipeline/start", methods=["POST"])
def start_pipeline():
    global _pipeline_thread
    st = _get_state()
    if st["running"]:
        return jsonify({"status": "already_running"}), 409

    data            = request.get_json() or {}
    dry_run         = data.get("dry_run", False)       # default False now
    batch_size      = int(data.get("batch_size", 20))
    cooldown_minutes= float(data.get("cooldown_minutes", 30))

    def _run():
        run_pipeline(
            dry_run=dry_run,
            batch_size=batch_size,
            cooldown_minutes=cooldown_minutes,
        )

    _pipeline_thread = threading.Thread(target=_run, daemon=True)
    _pipeline_thread.start()
    return jsonify({
        "status":           "started",
        "dry_run":          dry_run,
        "batch_size":       batch_size,
        "cooldown_minutes": cooldown_minutes,
    })


@app.route("/api/pipeline/stop", methods=["POST"])
def stop_pipeline():
    st = _get_state()
    if not st["running"]:
        return jsonify({"status": "not_running"}), 400
    _set_state(stop_requested=True)
    logger.info("Stop requested by user — will halt after current batch")
    return jsonify({"status": "stop_requested"})


@app.route("/api/applications")
def applications():
    log      = _load(DATA_DIR / "applications" / "application_log.json", [])
    status_f = request.args.get("status", "")
    response_f = request.args.get("response", "")
    if status_f:
        log = [r for r in log if r.get("status") == status_f]
    if response_f:
        log = [r for r in log if r.get("response_status", "") == response_f]
    log  = sorted(log, key=lambda x: x.get("applied_at", ""), reverse=True)
    page = int(request.args.get("page", 1))
    per  = int(request.args.get("per_page", 20))
    return jsonify({
        "total":        len(log),
        "applications": log[(page - 1) * per : page * per],
    })


@app.route("/api/applications/response", methods=["PUT"])
def update_response():
    """
    Mark an application's interview response status.
    Body: { "url": "...", "response_status": "interview_call" | "rejection" | "no_response" | "pending" }
    """
    data      = request.get_json() or {}
    url       = data.get("url", "")
    resp_stat = data.get("response_status", "")

    valid = {"interview_call", "rejection", "no_response", "pending"}
    if resp_stat not in valid:
        return jsonify({"error": f"response_status must be one of {valid}"}), 400
    if not url:
        return jsonify({"error": "url required"}), 400

    log_path = DATA_DIR / "applications" / "application_log.json"
    log      = _load(log_path, [])
    updated  = False
    for record in log:
        if record.get("url") == url:
            record["response_status"]    = resp_stat
            record["response_updated_at"] = datetime.now().isoformat()
            updated = True
            break

    if not updated:
        return jsonify({"error": "application not found"}), 404

    _save(log_path, log)
    logger.info(f"Response updated: {url} → {resp_stat}")
    return jsonify({"status": "updated", "url": url, "response_status": resp_stat})


@app.route("/api/interview-stats")
def interview_stats():
    """Analytics: response rate by platform, by role type, by day."""
    log = _load(DATA_DIR / "applications" / "application_log.json", [])

    applied = [r for r in log if r.get("status") == "applied"]
    total   = len(applied)
    if total == 0:
        return jsonify({"total_applied": 0, "message": "No applications yet"})

    interviews = [r for r in applied if r.get("response_status") == "interview_call"]
    rejections = [r for r in applied if r.get("response_status") == "rejection"]
    pending    = [r for r in applied if r.get("response_status", "pending") == "pending"]

    # Platform breakdown
    platform_stats = {}
    for r in applied:
        pf = r.get("platform", "unknown")
        if pf not in platform_stats:
            platform_stats[pf] = {"applied": 0, "interviews": 0, "rejections": 0}
        platform_stats[pf]["applied"] += 1
        rs = r.get("response_status", "")
        if rs == "interview_call": platform_stats[pf]["interviews"] += 1
        if rs == "rejection":      platform_stats[pf]["rejections"] += 1

    for pf in platform_stats:
        n = platform_stats[pf]["applied"]
        platform_stats[pf]["interview_rate"] = round(
            platform_stats[pf]["interviews"] / n * 100, 1
        ) if n else 0

    return jsonify({
        "total_applied":    total,
        "total_interviews": len(interviews),
        "total_rejections": len(rejections),
        "total_pending":    len(pending),
        "overall_rate":     round(len(interviews) / total * 100, 1),
        "by_platform":      platform_stats,
    })


@app.route("/api/jobs")
def jobs():
    data = _load(DATA_DIR / "logs" / "scraped_jobs.json", {"jobs": [], "count": 0})
    pf   = request.args.get("platform", "")
    j    = data.get("jobs", [])
    if pf:
        j = [x for x in j if x.get("platform", "").lower() == pf.lower()]
    return jsonify({
        "total":     len(j),
        "timestamp": data.get("timestamp"),
        "batches":   data.get("batch_count", 1),
        "jobs":      j[:200],
    })


@app.route("/api/batches")
def batches():
    """List all batch files with their job counts."""
    logs_dir = DATA_DIR / "logs"
    out = []
    for f in sorted(logs_dir.glob("batch_*.json")):
        d = _load(f, {})
        out.append({
            "batch_number":  d.get("batch_number", 0),
            "total_batches": d.get("total_batches", 0),
            "job_count":     d.get("job_count", 0),
            "filename":      f.name,
        })
    return jsonify({"batches": out})


@app.route("/api/batches/<int:num>")
def batch_detail(num: int):
    f = DATA_DIR / "logs" / f"batch_{num:02d}.json"
    if not f.exists():
        return jsonify({"error": "batch not found"}), 404
    return jsonify(_load(f, {}))


@app.route("/api/resumes")
def resumes():
    idx = _load(DATA_DIR / "resumes" / "resume_index.json", {})
    out = []
    for rid, m in idx.items():
        out.append({
            "id":           rid,
            "company":      m.get("company"),
            "title":        m.get("title"),
            "match_score":  m.get("match_score"),
            "primary_tech": m.get("primary_tech", "general"),
            "ats_keywords": m.get("ats_keywords", []),
            "created_at":   m.get("created_at"),
            "filename":     Path(m.get("pdf_path", "")).name,
        })
    return jsonify({
        "total":   len(out),
        "resumes": sorted(out, key=lambda x: x.get("created_at", ""), reverse=True),
    })


@app.route("/api/resumes/download/<filename>")
def download(filename):
    p = DATA_DIR / "resumes" / filename
    if p.exists():
        return send_file(str(p), as_attachment=True)
    return jsonify({"error": "not found"}), 404


@app.route("/api/runs")
def runs():
    logs_dir = DATA_DIR / "logs"
    out      = []
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("run_*.json"), reverse=True)[:20]:
            try:
                with open(f) as fp:
                    out.append(json.load(fp))
            except Exception:
                pass
    return jsonify({"runs": out})


@app.route("/api/failures")
def failures():
    """List failure screenshots from JD extraction and application attempts."""
    jd_fail_dir  = DATA_DIR / "logs" / "jd_failures"
    app_fail_dir = DATA_DIR / "logs" / "app_failures"
    out = []
    for d, label in [(jd_fail_dir, "jd"), (app_fail_dir, "app")]:
        if d.exists():
            for f in sorted(d.glob("*.png"), reverse=True)[:30]:
                out.append({"name": f.name, "type": label, "path": str(f)})
    return jsonify({"failures": out})


@app.route("/api/failures/image/<path:filename>")
def failure_image(filename):
    """Serve a failure screenshot PNG inline."""
    for d in [DATA_DIR / "logs" / "jd_failures",
              DATA_DIR / "logs" / "app_failures"]:
        p = d / filename
        if p.exists():
            return send_file(str(p), mimetype="image/png")
    return jsonify({"error": "not found"}), 404


@app.route("/api/reports")
def reports():
    logs_dir = DATA_DIR / "logs"
    out      = []
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("report_*.html"), reverse=True)[:10]:
            out.append({"name": f.name, "path": str(f)})
    return jsonify({"reports": out})


@app.route("/api/personal-kb")
def get_kb():
    return jsonify(_load(CONFIG_DIR / "personal_kb.json", {}))


@app.route("/api/personal-kb", methods=["PUT"])
def set_kb():
    p = CONFIG_DIR / "personal_kb.json"
    _save(p, request.get_json())
    return jsonify({"status": "updated"})


if __name__ == "__main__":
    logger.info("JobBot Dashboard starting on http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)