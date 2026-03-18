"""
Email Reporter
Sends a formatted HTML email to harishknlpengineer25@gmail.com
with a summary of all successfully applied jobs in this session:
- Company Name
- Role/Title
- Package (if mentioned)
- Location
Uses Gmail SMTP (App Password) - completely free.
"""

import smtplib
import json
import logging
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)

TO_EMAIL = "harishknlpengineer25@gmail.com"
FROM_EMAIL = "harishknlpengineer25@gmail.com"


def build_html_email(applied_jobs: list[dict], run_summary: dict) -> str:
    """Build a rich HTML email with the application summary."""

    date_str = datetime.now().strftime("%d %B %Y, %I:%M %p")
    total = len(applied_jobs)
    platforms = {}
    for j in applied_jobs:
        p = j.get("platform", "Unknown").capitalize()
        platforms[p] = platforms.get(p, 0) + 1

    platform_str = " | ".join(f"{p}: {c}" for p, c in platforms.items())

    # Build rows
    rows_html = ""
    for i, job in enumerate(applied_jobs, 1):
        salary = job.get("salary", "Not disclosed") or "Not disclosed"
        location = job.get("location", "—") or "—"
        platform = job.get("platform", "—")
        title = job.get("title", "—")
        company = job.get("company", "—")
        url = job.get("url", "#")
        applied_at = job.get("applied_at", "")[:16].replace("T", " ")

        row_bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        rows_html += f"""
        <tr style="background:{row_bg};">
          <td style="padding:10px 14px;font-weight:600;color:#111827;border-bottom:1px solid #e5e7eb;">{i}</td>
          <td style="padding:10px 14px;color:#111827;border-bottom:1px solid #e5e7eb;font-weight:600;">{company}</td>
          <td style="padding:10px 14px;color:#374151;border-bottom:1px solid #e5e7eb;">{title}</td>
          <td style="padding:10px 14px;color:#059669;border-bottom:1px solid #e5e7eb;font-weight:500;">{salary}</td>
          <td style="padding:10px 14px;color:#6b7280;border-bottom:1px solid #e5e7eb;">{location}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;">
            <span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;">{platform}</span>
          </td>
          <td style="padding:10px 14px;color:#9ca3af;font-size:12px;border-bottom:1px solid #e5e7eb;">{applied_at}</td>
        </tr>"""

    # Stats cards
    stats_html = f"""
    <div style="display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap;">
      <div style="background:#dbeafe;border-radius:10px;padding:16px 24px;flex:1;min-width:120px;">
        <div style="font-size:28px;font-weight:700;color:#1d4ed8;">{total}</div>
        <div style="color:#3b82f6;font-size:12px;margin-top:2px;">Applied</div>
      </div>
      <div style="background:#dcfce7;border-radius:10px;padding:16px 24px;flex:1;min-width:120px;">
        <div style="font-size:28px;font-weight:700;color:#16a34a;">{run_summary.get('scraped',0)}</div>
        <div style="color:#22c55e;font-size:12px;margin-top:2px;">Scraped</div>
      </div>
      <div style="background:#fef9c3;border-radius:10px;padding:16px 24px;flex:1;min-width:120px;">
        <div style="font-size:28px;font-weight:700;color:#ca8a04;">{run_summary.get('tailored',0)}</div>
        <div style="color:#eab308;font-size:12px;margin-top:2px;">Resumes Made</div>
      </div>
      <div style="background:#fce7f3;border-radius:10px;padding:16px 24px;flex:1;min-width:120px;">
        <div style="font-size:28px;font-weight:700;color:#db2777;">{run_summary.get('failed',0)}</div>
        <div style="color:#ec4899;font-size:12px;margin-top:2px;">Failed</div>
      </div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:800px;margin:0 auto;padding:24px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1a56db,#7c3aed);border-radius:14px;padding:28px 32px;margin-bottom:20px;color:white;">
      <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;opacity:0.7;margin-bottom:6px;">JobBot Agentic Pipeline</div>
      <div style="font-size:26px;font-weight:700;margin-bottom:4px;">Application Report</div>
      <div style="opacity:0.8;font-size:13px;">{date_str} &nbsp;·&nbsp; Harish K &nbsp;·&nbsp; {platform_str}</div>
    </div>

    <!-- Stats -->
    {stats_html}

    <!-- Table -->
    <div style="background:white;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08);margin-bottom:20px;">
      <div style="padding:16px 20px;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;">
        <div style="font-weight:700;font-size:15px;color:#111827;">Successfully Applied Jobs</div>
        <div style="font-size:12px;color:#6b7280;">{total} applications this run</div>
      </div>
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#f9fafb;">
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">#</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Company</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Role</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Package</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Location</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Platform</th>
              <th style="padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Time</th>
            </tr>
          </thead>
          <tbody>
            {rows_html if rows_html else '<tr><td colspan="7" style="padding:24px;text-align:center;color:#9ca3af;">No applications in this run</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Footer -->
    <div style="text-align:center;color:#9ca3af;font-size:12px;padding:12px;">
      JobBot Agentic System &nbsp;·&nbsp; harishknlpengineer25@gmail.com<br>
      Powered by Groq (LLaMA 3) + Playwright + ReportLab &nbsp;·&nbsp; 100% Free Stack
    </div>
  </div>
</body>
</html>"""
    return html


def send_report(
    applied_jobs: list[dict],
    run_summary: dict,
    gmail_app_password: str = "",
) -> bool:
    """
    Send email summary via Gmail SMTP.
    gmail_app_password: Get from Google Account → Security → App Passwords
    Set as env var: GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
    """
    if not gmail_app_password:
        gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not gmail_app_password:
        logger.warning("GMAIL_APP_PASSWORD not set. Email not sent.")
        logger.info("To enable emails: export GMAIL_APP_PASSWORD='your 16-char app password'")
        return False

    subject = f"[JobBot] Applied to {len(applied_jobs)} jobs — {datetime.now().strftime('%d %b %Y')}"
    html_body = build_html_email(applied_jobs, run_summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(FROM_EMAIL, gmail_app_password)
            smtp.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
        logger.info(f"✉ Email report sent to {TO_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail auth failed. Make sure you use an App Password, not your main password.")
        logger.error("Steps: Google Account → Security → 2-Step Verification → App Passwords → Generate")
        return False
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False


def save_report_locally(applied_jobs: list[dict], run_summary: dict, data_dir: str = "data"):
    """Save HTML report locally as fallback."""
    reports_dir = Path(data_dir) / "logs"
    reports_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"report_{date_str}.html"
    html = build_html_email(applied_jobs, run_summary)
    with open(report_path, "w") as f:
        f.write(html)
    logger.info(f"Report saved locally: {report_path}")
    return str(report_path)
