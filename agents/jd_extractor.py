"""
Agent 2: JD Extractor (Playwright-based) — Phase 2 Enhanced
Visits each job URL and extracts: full JD text, required skills,
salary/package info, responsibilities, and company details.

Fixes vs original:
  ✅ Every failed JD logs the URL + reason (was completely silent)
  ✅ Internshala company name fallback (page title / og:site_name / meta)
  ✅ Fresh page per job — one crash no longer kills the whole batch
  ✅ Naukri extractor added  (new platform from Phase 1 scraper)
  ✅ Wellfound extractor added (new platform from Phase 1 scraper)
  ✅ Batch-aware run(batch) signature aligned with orchestrator
  ✅ JD quality filter — skips jobs where jd_text < 100 chars
  ✅ Screenshot saved on extraction failure for debugging
  ✅ Cache keyed per URL so re-runs skip already-extracted JDs
"""

import json
import logging
import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class JDExtractor:
    def __init__(self, data_dir: str = "data"):
        self.data_dir     = Path(data_dir)
        self.jd_cache_dir = self.data_dir / "logs" / "jds"
        self.fail_dir     = self.data_dir / "logs" / "jd_failures"
        self.jd_cache_dir.mkdir(parents=True, exist_ok=True)
        self.fail_dir.mkdir(parents=True, exist_ok=True)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _cache_key(self, url: str) -> str:
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def _clean(self, text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_salary(self, text: str) -> str:
        patterns = [
            r"(?:salary|package|ctc|compensation|lpa|lakh)[:\s]*([₹\d.,\s\-Llakh per annumPA]+)",
            r"(\d+\s*[-–]\s*\d+\s*(?:LPA|lakh|L|lacs))",
            r"(\d+(?:\.\d+)?\s*(?:LPA|lakh|L)\s*(?:per annum|p\.a\.)?)",
            r"(?:upto|up to)\s+([\d.,]+\s*(?:LPA|lakh|L))",
            r"(\$\s*\d[\d,]*(?:\.\d+)?\s*(?:\/\s*(?:yr|year|month|mo))?)",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return "Not disclosed"

    def _company_from_page(self, page) -> str:
        """
        Fallback company name from page metadata when element selectors fail.
        Tries: og:site_name → page title → document.title split.
        """
        try:
            og = page.query_selector("meta[property='og:site_name']")
            if og:
                val = og.get_attribute("content") or ""
                if val.strip():
                    return val.strip()
        except Exception:
            pass
        try:
            title = page.title()
            # "Job Title at Company Name | Platform" → "Company Name"
            for sep in [" at ", " @ ", " | ", " - "]:
                if sep in title:
                    parts = title.split(sep)
                    if len(parts) >= 2:
                        candidate = parts[1].split("|")[0].split("-")[0].strip()
                        if candidate and len(candidate) > 2:
                            return candidate
        except Exception:
            pass
        return ""

    def _screenshot_failure(self, page, url: str, label: str):
        """Save a screenshot when JD extraction fails — for debugging."""
        try:
            safe = re.sub(r"[^a-zA-Z0-9]", "_", url)[:40]
            path = self.fail_dir / f"{label}_{safe}.png"
            page.screenshot(path=str(path))
            logger.debug(f"Failure screenshot saved: {path.name}")
        except Exception:
            pass  # screenshot is best-effort

    # ── Platform-specific extractors ──────────────────────────────────────────

    def _extract_naukri_jd(self, page, url: str) -> dict:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)

        jd_el      = page.query_selector(
            "div.job-desc, div[class*='dang-inner-html'], section.job-desc-main, "
            "div[class*='jobDescription'], div#job_summary"
        )
        skills_el  = page.query_selector(
            "div.key-skill, div[class*='chip-list'], ul.tags-gt, div[class*='keySkillList']"
        )
        title_el   = page.query_selector("h1.jd-header-title, h1[class*='jd-header'], h1[class*='title']")
        company_el = page.query_selector(
            "div.jd-header-comp-name a, a[class*='comp-name'], span[class*='companyName'] a"
        )
        loc_el     = page.query_selector("li.location span, span[class*='location'], li[class*='loc']")
        salary_el  = page.query_selector("li.salary span, span[class*='salary'], div[class*='salary']")
        exp_el     = page.query_selector("li.experience span, div[class*='exp']")

        jd_text = jd_el.inner_text() if jd_el else ""
        skills  = skills_el.inner_text() if skills_el else ""
        salary  = salary_el.inner_text().strip() if salary_el else self._extract_salary(jd_text)
        company = company_el.inner_text().strip() if company_el else self._company_from_page(page)

        return {
            "title":               title_el.inner_text().strip() if title_el else "",
            "company":             company,
            "location":            loc_el.inner_text().strip() if loc_el else "",
            "salary":              salary or "Not disclosed",
            "experience_required": exp_el.inner_text().strip() if exp_el else "",
            "key_skills":          skills,
            "jd_text":             self._clean(jd_text[:5000]),
        }

    def _extract_linkedin_jd(self, page, url: str) -> dict:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)

        # Expand "show more"
        for btn_sel in [
            "button[aria-label*='Show more']",
            "button.show-more-less-html__button",
            "button[class*='show-more']",
        ]:
            try:
                btn = page.query_selector(btn_sel)
                if btn:
                    btn.click()
                    page.wait_for_timeout(800)
                    break
            except Exception:
                pass

        jd_el      = page.query_selector(
            "div.description__text, div[class*='show-more-less-html__markup'], "
            "div[class*='jobs-description__content']"
        )
        title_el   = page.query_selector(
            "h1.top-card-layout__title, h1[class*='job-details'], "
            "h1[class*='jobs-unified-top-card']"
        )
        company_el = page.query_selector(
            "a.topcard__org-name-link, [class*='company-name'], "
            "a[class*='ember-view topcard__org-name']"
        )
        loc_el     = page.query_selector(
            "span.topcard__flavor--bullet, [class*='location'], "
            "span[class*='jobs-unified-top-card__bullet']"
        )
        salary_el  = page.query_selector(
            "div[class*='salary'], span[class*='compensation'], "
            "div[class*='jobs-unified-top-card__salary']"
        )

        jd_text = jd_el.inner_text() if jd_el else ""
        salary  = salary_el.inner_text().strip() if salary_el else self._extract_salary(jd_text)
        company = company_el.inner_text().strip() if company_el else self._company_from_page(page)

        return {
            "title":               title_el.inner_text().strip() if title_el else "",
            "company":             company,
            "location":            loc_el.inner_text().strip() if loc_el else "",
            "salary":              salary or "Not disclosed",
            "experience_required": "",
            "key_skills":          "",
            "jd_text":             self._clean(jd_text[:5000]),
        }

    def _extract_indeed_jd(self, page, url: str) -> dict:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)

        jd_el      = page.query_selector(
            "div#jobDescriptionText, div[id*='jobDescription'], "
            "div[data-testid='jobsearch-JobComponent-description']"
        )
        title_el   = page.query_selector(
            "h1.jobsearch-JobInfoHeader-title, "
            "h1[data-testid='jobsearch-JobInfoHeader-title']"
        )
        company_el = page.query_selector(
            "div[data-company-name='true'], [class*='companyName'], "
            "[data-testid='inlineHeader-companyName']"
        )
        loc_el     = page.query_selector(
            "div[data-testid='job-location'], [class*='companyLocation'], "
            "div[data-testid='inlineHeader-companyLocation']"
        )
        salary_el  = page.query_selector(
            "div[id='salaryInfoAndJobType'], [class*='salary'], "
            "div[data-testid='jobsearch-OtherJobDetailsContainer']"
        )

        jd_text = jd_el.inner_text() if jd_el else ""
        salary  = salary_el.inner_text().strip() if salary_el else self._extract_salary(jd_text)
        company = company_el.inner_text().strip() if company_el else self._company_from_page(page)

        return {
            "title":               title_el.inner_text().strip() if title_el else "",
            "company":             company,
            "location":            loc_el.inner_text().strip() if loc_el else "",
            "salary":              salary or "Not disclosed",
            "experience_required": "",
            "key_skills":          "",
            "jd_text":             self._clean(jd_text[:5000]),
        }

    def _extract_internshala_jd(self, page, url: str) -> dict:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)

        # JD content — try multiple selectors for Internshala's varying layouts
        jd_el = (
            page.query_selector("div#about_the_job") or
            page.query_selector("div.about_the_job") or
            page.query_selector("div.internship_details div.text-container") or
            page.query_selector("div.individual_internship_details") or
            page.query_selector("div[class*='job_description']") or
            page.query_selector("div.detail_view div.content")
        )

        title_el = (
            page.query_selector("h1.profile_detail") or
            page.query_selector("div.profile_detail h1") or
            page.query_selector("span.profile_on_detail_page") or
            page.query_selector("h3.job-internship-name") or
            page.query_selector("h1[class*='heading']")
        )
        company_el = (
            page.query_selector("div.company_name a") or
            page.query_selector("a.link_display_like_text") or
            page.query_selector("p.company_name a") or
            page.query_selector("div.heading_4_6 a") or
            page.query_selector("div[class*='company'] a")
        )
        loc_el = (
            page.query_selector("div#location_names a") or
            page.query_selector("p.locations a") or
            page.query_selector("span.location_link a") or
            page.query_selector("div.location_link a")
        )
        salary_el = (
            page.query_selector("div.stipend_container_desktop span") or
            page.query_selector("span.stipend") or
            page.query_selector("div.stipend") or
            page.query_selector("span.salary") or
            page.query_selector("div[class*='salary']")
        )
        skills_el = (
            page.query_selector("div.skills_container") or
            page.query_selector("div.round_tabs_container") or
            page.query_selector("div.skill_container") or
            page.query_selector("div[class*='skills']")
        )

        jd_text = jd_el.inner_text() if jd_el else page.evaluate("document.body.innerText")
        company = company_el.inner_text().strip() if company_el else ""

        # ── Company name fallback chain ──────────────────────────────────────
        if not company or company.strip() == "":
            company = self._company_from_page(page)

        # Last resort: try structured data
        if not company:
            try:
                ld = page.query_selector("script[type='application/ld+json']")
                if ld:
                    data = json.loads(ld.inner_text())
                    company = (
                        data.get("hiringOrganization", {}).get("name", "") or
                        data.get("name", "")
                    )
            except Exception:
                pass

        salary = salary_el.inner_text().strip() if salary_el else self._extract_salary(jd_text)

        return {
            "title":               title_el.inner_text().strip() if title_el else "",
            "company":             company or "Unknown",
            "location":            loc_el.inner_text().strip() if loc_el else "",
            "salary":              salary or "Not disclosed",
            "experience_required": "",
            "key_skills":          skills_el.inner_text().strip() if skills_el else "",
            "jd_text":             self._clean(jd_text[:5000]),
        }

    def _extract_wellfound_jd(self, page, url: str) -> dict:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)

        jd_el      = page.query_selector(
            "div[class*='description'], div[class*='job-description'], "
            "div[class*='JobDescription']"
        )
        title_el   = page.query_selector("h1[class*='title'], h1[class*='JobTitle']")
        company_el = page.query_selector(
            "a[class*='startup'], h2[class*='company'], span[class*='startup-name']"
        )
        salary_el  = page.query_selector(
            "span[class*='salary'], span[class*='compensation'], span[class*='equity']"
        )
        loc_el     = page.query_selector(
            "span[class*='location'], div[class*='location']"
        )

        jd_text = jd_el.inner_text() if jd_el else ""
        salary  = salary_el.inner_text().strip() if salary_el else self._extract_salary(jd_text)
        company = company_el.inner_text().strip() if company_el else self._company_from_page(page)

        return {
            "title":               title_el.inner_text().strip() if title_el else "",
            "company":             company or "Unknown",
            "location":            loc_el.inner_text().strip() if loc_el else "Remote / India",
            "salary":              salary or "Not disclosed",
            "experience_required": "",
            "key_skills":          "",
            "jd_text":             self._clean(jd_text[:5000]),
        }

    def _extract_remotive_jd(self, page, url: str) -> dict:
        """Remotive job detail pages."""
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2500)

        jd_el      = page.query_selector(
            "div[class*='job-description'], div[class*='description'], "
            "section[class*='job'], div#job-description"
        )
        title_el   = page.query_selector("h1[class*='title'], h1[class*='job']")
        company_el = page.query_selector(
            "a[class*='company'], span[class*='company'], h2[class*='company']"
        )
        salary_el  = page.query_selector("span[class*='salary'], div[class*='salary']")

        jd_text = jd_el.inner_text() if jd_el else page.evaluate("document.body.innerText")
        salary  = salary_el.inner_text().strip() if salary_el else self._extract_salary(jd_text)
        company = company_el.inner_text().strip() if company_el else self._company_from_page(page)

        return {
            "title":               title_el.inner_text().strip() if title_el else "",
            "company":             company or "Unknown",
            "location":            "Remote",
            "salary":              salary or "Not disclosed",
            "experience_required": "",
            "key_skills":          "",
            "jd_text":             self._clean(jd_text[:5000]),
        }

    def _generic_extract(self, page, url: str) -> dict:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2000)
        body_text = page.evaluate("document.body.innerText")
        company   = self._company_from_page(page)
        return {
            "title":               "",
            "company":             company or "Unknown",
            "location":            "",
            "salary":              self._extract_salary(body_text),
            "experience_required": "",
            "key_skills":          "",
            "jd_text":             self._clean(body_text[:5000]),
        }

    # ── Core extraction logic ─────────────────────────────────────────────────

    def extract_one(self, job: dict, context) -> Optional[dict]:
        """
        Extract JD for a single job.
        Creates a FRESH page per job — one crash won't kill the whole batch.
        """
        url      = job.get("url", "")
        platform = job.get("platform", "").lower()
        company  = job.get("company", "Unknown")
        title    = job.get("title", "?")

        if not url:
            logger.warning(f"JD SKIP: no URL for '{title}' @ '{company}'")
            return None

        # Check cache first
        cache_file = self.jd_cache_dir / f"{self._cache_key(url)}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)

        # Create a fresh page for this job
        page = context.new_page()
        try:
            if "naukri" in platform:
                extracted = self._extract_naukri_jd(page, url)
            elif "linkedin" in platform:
                extracted = self._extract_linkedin_jd(page, url)
            elif "indeed" in platform:
                extracted = self._extract_indeed_jd(page, url)
            elif "internshala" in platform:
                extracted = self._extract_internshala_jd(page, url)
            elif "wellfound" in platform or "angel" in platform:
                extracted = self._extract_wellfound_jd(page, url)
            elif "remotive" in platform:
                extracted = self._extract_remotive_jd(page, url)
            else:
                extracted = self._generic_extract(page, url)

            # Quality gate — JD must have meaningful text
            jd_text = extracted.get("jd_text", "")
            if len(jd_text.strip()) < 100:
                logger.warning(
                    f"JD FAILED (too short: {len(jd_text)} chars): "
                    f"'{title}' @ '{company}' | {url}"
                )
                self._screenshot_failure(page, url, platform)
                return None

            # Merge: prefer extracted non-empty values over job metadata
            result = {**job}
            for k, v in extracted.items():
                if v and str(v).strip():
                    result[k] = v

            # Salary fallback
            if not result.get("salary") or result["salary"] == "Not disclosed":
                result["salary"] = job.get("salary", "Not disclosed")

            # Company name fallback if still Unknown
            if result.get("company", "Unknown") == "Unknown":
                fallback_co = self._company_from_page(page)
                if fallback_co:
                    result["company"] = fallback_co

            result["jd_extracted_at"] = datetime.now().isoformat()

            with open(cache_file, "w") as f:
                json.dump(result, f, indent=2)

            return result

        except Exception as e:
            logger.error(
                f"JD FAILED ({type(e).__name__}): "
                f"'{title}' @ '{company}' | {url} | {e}"
            )
            self._screenshot_failure(page, url, platform)
            return None

        finally:
            try:
                page.close()
            except Exception:
                pass

    # ── Batch run ─────────────────────────────────────────────────────────────

    def run(self, jobs: list) -> list:
        """
        Extract JDs for a list of jobs.
        Each job gets its own fresh Playwright page.
        Failed extractions are fully logged with URL.

        Args:
            jobs : list of job dicts from scraper (one batch)

        Returns:
            list of enriched job dicts with jd_text populated
        """
        logger.info(f"=== JD Extractor Starting: {len(jobs)} jobs ===")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        extracted = []
        failed    = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            # Suppress webdriver detection
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )

            for i, job in enumerate(jobs):
                t = job.get("title", "?")
                c = job.get("company", "?")
                logger.info(f"[{i+1}/{len(jobs)}] Extracting: {t} @ {c}")

                result = self.extract_one(job, context)

                if result and result.get("jd_text"):
                    extracted.append(result)
                else:
                    failed.append({"title": t, "company": c, "url": job.get("url", "")})

                time.sleep(random.uniform(1.5, 3.0))

            browser.close()

        # Log a clean summary of all failures
        logger.info(
            f"JD extraction complete: {len(extracted)}/{len(jobs)} successful, "
            f"{len(failed)} failed"
        )
        if failed:
            logger.warning(f"Failed JD extractions ({len(failed)}):")
            for f in failed:
                logger.warning(f"  ✗ {f['title']} @ {f['company']} | {f['url']}")

        return extracted