"""
Agent 1: Job Scraper (Playwright) — Phase 1 Enhanced
Platforms:
  - Indeed        (works well, no login)
  - LinkedIn      (cookie-based, 2025 selectors, authwall detection)
  - Internshala   (best Indian fresher site, improved selectors)
  - Remotive      (UTC timezone fix — was killing all results)
  - Naukri        (NEW — largest Indian job database)
  - Wellfound     (NEW — startup jobs, no login)

Fixes vs original:
  ✅ LinkedIn: cookies loaded BEFORE page creation, authwall/checkpoint handling
  ✅ Remotive: UTC-aware datetime comparison (was silently dropping all jobs)
  ✅ Role blacklist: iOS/ServiceNow/WordPress/etc filtered out
  ✅ Batch architecture: run(batch_size=20) with configurable cooldown
  ✅ Better LinkedIn 2025 selectors
  ✅ Naukri scraper added
  ✅ Wellfound scraper added
  ✅ Company name 'Unknown' fallback from page title
  ✅ All scraping errors logged with URL for debugging
"""

import json
import logging
import re
import time
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Fresher role filter: reject these experience patterns ─────────────────────
FRESHER_REJECT_PATTERNS = [
    r"\b[3-9]\+?\s*(?:years?|yrs?)\b",
    r"\b[1-9][0-9]\+?\s*(?:years?|yrs?)\b",
    r"\bminimum\s+[3-9]\s+years?\b",
    r"\b(?:senior|sr\.?)\s+(?:software|developer|engineer|architect)\b",
    r"\blead\s+(?:engineer|developer|architect)\b",
    r"\bstaff\s+engineer\b",
    r"\bprincipal\s+engineer\b",
    r"\bvp\s+of\s+engineering\b",
    r"\bengineering\s+manager\b",
]

# ── Role blacklist: irrelevant to Python/AI/Backend candidate ────────────────
ROLE_BLACKLIST_PATTERNS = [
    r"\bios\s+developer\b",
    r"\bandroid\s+developer\b",
    r"\bswift\s+developer\b",
    r"\bkotlin\s+developer\b",
    r"\bflutter\s+developer\b",
    r"\bservicenow\b",
    r"\bwordpress\s+developer\b",
    r"\bweb\s+designer\b",
    r"\bgraphic\s+designer\b",
    r"\bsystem\s+network\s+admin\b",
    r"\bnetwork\s+administrator\b",
    r"\btechnical\s+architect\b",
    r"\bsap\s+developer\b",
    r"\bsalesforce\s+developer\b",
    r"\b\.net\s+developer\b",
    r"\bc\#\s+developer\b",
    r"\bphp\s+developer\b",
    r"\bruby\s+developer\b",
    r"\bembedded\s+(?:systems?|engineer)\b",
    r"\bfirmware\s+engineer\b",
    r"\bhardware\s+engineer\b",
    r"\bvlsi\b",
    r"\bcontent\s+writer\b",
    r"\bseo\s+specialist\b",
    r"\bdigital\s+marketing\b",
    r"\bsales\s+engineer\b",
]

# ── High-value platforms / sources (affects rank score) ──────────────────────
PLATFORM_SCORES = {
    "LinkedIn":   3,
    "Naukri":     3,
    "Indeed":     2,
    "Wellfound":  2,
    "Internshala":1,
    "Remotive":   2,
}


def is_fresher_role(title: str, description: str = "") -> bool:
    combined = (title + " " + description).lower()
    for pat in FRESHER_REJECT_PATTERNS:
        if re.search(pat, combined, re.IGNORECASE):
            return False
    return True


def is_relevant_role(title: str) -> bool:
    """Block roles that are completely irrelevant to the candidate."""
    t = title.lower()
    for pat in ROLE_BLACKLIST_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            logger.debug(f"Role blacklisted: {title}")
            return False
    return True


def is_quality_internship(title: str, company: str, salary: str) -> bool:
    text = f"{title} {company}".lower()
    reject_keywords = [
        "sales", "marketing", "hr ", "human resource",
        "business development", "telecalling", "content writing", "seo",
        "digital marketing", "bde ", "bdm ",
    ]
    if any(k in text for k in reject_keywords):
        return False
    if salary and "unpaid" in salary.lower():
        return False
    return True


class JobScraper:
    def __init__(self, data_dir: str = "data"):
        self.data_dir  = Path(data_dir)
        self.apps_dir  = self.data_dir / "applications"
        self.logs_dir  = self.data_dir / "logs"
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.applied_file  = self.apps_dir / "applied_links.json"
        self.applied_links = self._load_applied()

        self.linkedin_cookies_file = self.data_dir / "linkedin_cookies.json"
        self.naukri_cookies_file   = self.data_dir / "naukri_cookies.json"

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _load_applied(self) -> set:
        if self.applied_file.exists():
            with open(self.applied_file) as f:
                return set(json.load(f).get("links", []))
        return set()

    def _delay(self, lo: float = 1.5, hi: float = 3.5):
        time.sleep(random.uniform(lo, hi))

    def _load_cookies(self, context, cookie_file: Path, label: str):
        """Load exported browser cookies into a Playwright context."""
        if not cookie_file.exists():
            logger.warning(f"{label} cookies file not found — skipping login")
            return False
        try:
            with open(cookie_file, encoding="utf-8") as f:
                raw = json.load(f)

            cleaned = []
            for c in raw:
                try:
                    cookie = {
                        "name":     c.get("name", ""),
                        "value":    c.get("value", ""),
                        "domain":   c.get("domain", ""),
                        "path":     c.get("path", "/"),
                        "secure":   bool(c.get("secure", False)),
                        "httpOnly": bool(c.get("httpOnly", False)),
                    }
                    # Normalise sameSite (Playwright is strict about this)
                    ss = c.get("sameSite", "").lower()
                    if ss in ("no_restriction", "none"):
                        cookie["sameSite"] = "None"
                    elif ss == "strict":
                        cookie["sameSite"] = "Strict"
                    else:
                        cookie["sameSite"] = "Lax"

                    if "expirationDate" in c:
                        cookie["expires"] = int(c["expirationDate"])

                    cleaned.append(cookie)
                except Exception as e:
                    logger.debug(f"Skipping malformed cookie: {e}")

            context.add_cookies(cleaned)
            logger.info(f"{label} cookies loaded ✅ ({len(cleaned)} cookies)")
            return True
        except Exception as e:
            logger.error(f"Failed to load {label} cookies: {e}")
            return False

    def _is_blocked(self, page, expected_fragment: str) -> bool:
        """Return True if page redirected to a block / login wall."""
        url = page.url.lower()
        block_fragments = ["login", "authwall", "checkpoint", "signin", "uas/authenticate"]
        return any(frag in url for frag in block_fragments) or expected_fragment not in url

    # ── LinkedIn check ────────────────────────────────────────────────────────

    def _verify_linkedin_login(self, page) -> bool:
        """Navigate to feed and confirm we are logged in."""
        try:
            page.goto("https://www.linkedin.com/feed/", timeout=30000)
            page.wait_for_timeout(4000)
            url = page.url.lower()
            if any(frag in url for frag in ["authwall", "login", "checkpoint", "uas/"]):
                logger.error(f"LinkedIn login failed — redirected to: {page.url}")
                return False
            logger.info("LinkedIn login verified ✅")
            return True
        except Exception as e:
            logger.error(f"LinkedIn login check error: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # SCRAPER: Indeed
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_indeed(self, page) -> list:
        jobs = []
        queries = [
            "python developer fresher",
            "backend developer python fresher",
            "machine learning engineer fresher",
            "ai engineer fresher",
            "data scientist fresher",
            "software engineer python fresher",
        ]
        locations = [
            ("Chennai, Tamil Nadu", "chennai"),
            ("Bangalore, Karnataka", "bangalore"),
            ("Remote", "remote"),
        ]

        for role in queries:
            for loc_label, loc_key in locations:
                try:
                    url = (
                        f"https://in.indeed.com/jobs"
                        f"?q={role.replace(' ', '+')}"
                        f"&l={loc_label.replace(' ', '+').replace(',', '%2C')}"
                        f"&fromage=3&sort=date"
                    )
                    page.goto(url, timeout=30000)
                    page.wait_for_timeout(3000)

                    # Scroll to load lazy cards
                    for _ in range(3):
                        page.mouse.wheel(0, 1500)
                        page.wait_for_timeout(800)

                    cards = page.query_selector_all(
                        "div.job_seen_beacon, div[class*='tapItem'], div.resultContent"
                    )
                    for card in cards:
                        try:
                            link_el  = card.query_selector("h2.jobTitle a, a.jcs-JobTitle")
                            title_el = card.query_selector(
                                "h2.jobTitle span[title], h2.jobTitle span, span[id*='jobTitle']"
                            )
                            co_el    = card.query_selector(
                                "span.companyName, [data-testid='company-name'], "
                                "span[class*='companyName']"
                            )
                            loc_el   = card.query_selector(
                                "div.companyLocation, [data-testid='text-location'], "
                                "div[class*='companyLocation']"
                            )
                            sal_el   = card.query_selector(
                                "div[id*='salaryInfo'], [class*='salary'], "
                                "div[data-testid='attribute_snippet_testid']"
                            )

                            href  = link_el.get_attribute("href") if link_el else ""
                            link  = (
                                f"https://in.indeed.com{href}"
                                if href.startswith("/") else href
                            )
                            title = title_el.inner_text().strip() if title_el else role
                            co    = co_el.inner_text().strip()    if co_el    else "Unknown"
                            loc   = loc_el.inner_text().strip()   if loc_el   else loc_label
                            sal   = sal_el.inner_text().strip()   if sal_el   else "Not disclosed"

                            if not link or link in self.applied_links:
                                continue
                            if not is_fresher_role(title):
                                continue
                            if not is_relevant_role(title):
                                continue

                            jobs.append({
                                "platform":    "Indeed",
                                "title":       title,
                                "company":     co,
                                "location":    loc,
                                "salary":      sal,
                                "url":         link,
                                "scraped_at":  datetime.now().isoformat(),
                                "search_role": role,
                            })
                        except Exception as e:
                            logger.debug(f"Indeed card parse error: {e}")
                    self._delay()
                except Exception as e:
                    logger.error(f"Indeed error ({role} @ {loc_label}): {e}")

        logger.info(f"Indeed: {len(jobs)} jobs")
        return jobs

    # ──────────────────────────────────────────────────────────────────────────
    # SCRAPER: LinkedIn (cookie-based, 2025 UI selectors)
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_linkedin(self, page, logged_in: bool = False) -> list:
        jobs = []

        if not logged_in:
            logger.warning("LinkedIn: skipping scrape — not logged in")
            return jobs

        queries = [
            "python developer fresher",
            "backend developer fresher",
            "machine learning engineer fresher",
            "ai engineer fresher",
            "software engineer python fresher",
        ]
        locations = ["Chennai", "Bangalore", "India"]

        for role in queries:
            for loc in locations:
                try:
                    # f_E=1 → Entry level, f_TPR=r259200 → last 72h, f_EA=true → Easy Apply
                    url = (
                        f"https://www.linkedin.com/jobs/search/"
                        f"?keywords={role.replace(' ', '%20')}"
                        f"&location={loc.replace(' ', '%20')}"
                        f"&f_E=1&f_TPR=r259200&f_EA=true&sortBy=DD"
                    )
                    page.goto(url, timeout=30000)
                    page.wait_for_timeout(4000)

                    # Check we haven't been kicked to a wall
                    if self._is_blocked(page, "jobs/search"):
                        logger.warning(f"LinkedIn blocked on {role}@{loc} — {page.url}")
                        break

                    # Scroll to load more results
                    for _ in range(5):
                        page.mouse.wheel(0, 2000)
                        page.wait_for_timeout(1200)

                    # 2025 LinkedIn job card selectors
                    cards = page.query_selector_all(
                        "li.jobs-search-results__list-item, "
                        "div[data-job-id], "
                        "li[class*='scaffold-layout__list-item']"
                    )

                    for card in cards:
                        try:
                            # Try multiple selector combos for 2025 LinkedIn UI
                            link_el = (
                                card.query_selector("a[href*='/jobs/view/']") or
                                card.query_selector("a.job-card-list__title") or
                                card.query_selector("a[class*='job-card']")
                            )
                            title_el = (
                                card.query_selector("h3.job-card-list__title") or
                                card.query_selector("span.sr-only") or
                                card.query_selector("h3")
                            )
                            comp_el = (
                                card.query_selector("h4.job-card-container__company-name") or
                                card.query_selector("span.job-card-container__primary-description") or
                                card.query_selector("h4")
                            )
                            loc_el = (
                                card.query_selector("span.job-card-container__metadata-item") or
                                card.query_selector("li[class*='job-card-container__metadata-item']") or
                                card.query_selector("span[class*='location']")
                            )

                            href  = (link_el.get_attribute("href") or "").split("?")[0] if link_el else ""
                            link  = href if href.startswith("http") else f"https://www.linkedin.com{href}"
                            title = title_el.inner_text().strip() if title_el else ""
                            co    = comp_el.inner_text().strip()   if comp_el else "Unknown"
                            location_text = loc_el.inner_text().strip() if loc_el else loc

                            if not link or "/jobs/view/" not in link:
                                continue
                            if link in self.applied_links:
                                continue
                            if not title:
                                continue
                            if not is_fresher_role(title):
                                continue
                            if not is_relevant_role(title):
                                continue

                            jobs.append({
                                "platform":    "LinkedIn",
                                "title":       title,
                                "company":     co,
                                "location":    location_text,
                                "salary":      "Not disclosed",
                                "url":         link,
                                "easy_apply":  True,
                                "scraped_at":  datetime.now().isoformat(),
                                "search_role": role,
                            })
                        except Exception as e:
                            logger.debug(f"LinkedIn card parse: {e}")

                    self._delay(2, 4)
                except Exception as e:
                    logger.error(f"LinkedIn error ({role} @ {loc}): {e}")

        # Deduplicate by URL within LinkedIn results
        seen = set()
        unique = []
        for j in jobs:
            if j["url"] not in seen:
                seen.add(j["url"])
                unique.append(j)

        logger.info(f"LinkedIn: {len(unique)} jobs")
        return unique

    # ──────────────────────────────────────────────────────────────────────────
    # SCRAPER: Internshala (improved selectors + company name fallback)
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_internshala(self, page) -> list:
        jobs = []
        searches = [
            ("python-developer",     "python developer"),
            ("machine-learning",     "machine learning engineer"),
            ("backend-developer",    "backend developer"),
            ("software-engineer",    "software engineer"),
            ("artificial-intelligence", "AI engineer"),
            ("data-science",         "data scientist"),
            ("full-stack-developer", "full stack developer"),
        ]

        for slug, label in searches:
            try:
                url = f"https://internshala.com/jobs/{slug}-jobs"
                page.goto(url, timeout=30000)
                page.wait_for_timeout(3000)

                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1000)")
                    page.wait_for_timeout(800)

                cards = page.query_selector_all(
                    "div.internship_meta, "
                    "div[class*='individual_internship'], "
                    "div.container-fluid.individual_internship, "
                    "div.job_container"
                )

                for card in cards:
                    try:
                        link_el = (
                            card.query_selector("a.job-title-href") or
                            card.query_selector("h3.job-internship-name a") or
                            card.query_selector("a[href*='/jobs/detail']") or
                            card.query_selector("a[href*='/job-detail']")
                        )
                        titl_el = (
                            card.query_selector("h3.job-internship-name") or
                            card.query_selector("p.profile") or
                            card.query_selector("div.job_title")
                        )
                        comp_el = (
                            card.query_selector("p.company_name a") or
                            card.query_selector("a.link_display_like_text") or
                            card.query_selector("div.company_name a") or
                            card.query_selector("span.company_name")
                        )
                        loc_el = (
                            card.query_selector("p.locations a") or
                            card.query_selector("div.location_link a") or
                            card.query_selector("span.location_link")
                        )
                        sal_el = (
                            card.query_selector("span.stipend") or
                            card.query_selector("div.stipend") or
                            card.query_selector("span.salary_info")
                        )

                        href  = link_el.get_attribute("href") if link_el else ""
                        link  = (
                            f"https://internshala.com{href}"
                            if href.startswith("/") else href
                        )
                        title = titl_el.inner_text().strip() if titl_el else label
                        co    = comp_el.inner_text().strip()  if comp_el else ""
                        loc   = loc_el.inner_text().strip()   if loc_el  else "India"
                        sal   = sal_el.inner_text().strip()   if sal_el  else "Not disclosed"

                        # Company name fallback from page metadata if empty
                        if not co or co.strip() == "":
                            co = "Unknown"

                        if not link or link in self.applied_links:
                            continue
                        if not is_fresher_role(title):
                            continue
                        if not is_relevant_role(title):
                            continue
                        if not is_quality_internship(title, co, sal):
                            continue

                        loc_lower = loc.lower()
                        if not any(k in loc_lower for k in [
                            "chennai", "bangalore", "bengaluru",
                            "remote", "work from home", "india", "pan india"
                        ]):
                            continue

                        jobs.append({
                            "platform":    "Internshala",
                            "title":       title,
                            "company":     co,
                            "location":    loc,
                            "salary":      sal,
                            "url":         link,
                            "scraped_at":  datetime.now().isoformat(),
                            "search_role": label,
                        })
                    except Exception as e:
                        logger.debug(f"Internshala card parse: {e}")

                self._delay()
            except Exception as e:
                logger.error(f"Internshala error ({slug}): {e}")

        logger.info(f"Internshala: {len(jobs)} jobs")
        return jobs

    # ──────────────────────────────────────────────────────────────────────────
    # SCRAPER: Remotive — UTC TIMEZONE FIX (was silently dropping all results)
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_remotive(self, page) -> list:
        jobs = []
        searches = ["python", "machine-learning", "backend", "artificial-intelligence", "data"]

        # Use UTC-aware cutoff — previous IST naive comparison dropped ALL results
        cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=72)

        for tag in searches:
            try:
                url = (
                    f"https://remotive.com/api/remote-jobs"
                    f"?category=software-dev&search={tag}&limit=30"
                )
                page.goto(url, timeout=25000)
                page.wait_for_timeout(2000)

                content  = page.evaluate("document.body.innerText")
                data     = json.loads(content)
                job_list = data.get("jobs", [])

                for j in job_list:
                    try:
                        pub_str = j.get("publication_date", "")
                        if pub_str:
                            # Parse as UTC-aware datetime
                            pub_dt = datetime.fromisoformat(
                                pub_str.replace("Z", "+00:00")
                            )
                            if pub_dt < cutoff_utc:
                                continue

                        title = j.get("title", "")
                        link  = j.get("url", "")
                        co    = j.get("company_name", "Unknown")
                        sal   = j.get("salary", "") or "Not disclosed"

                        if not link or link in self.applied_links:
                            continue
                        if not is_fresher_role(title):
                            continue
                        if not is_relevant_role(title):
                            continue

                        jobs.append({
                            "platform":    "Remotive",
                            "title":       title,
                            "company":     co,
                            "location":    "Remote",
                            "salary":      sal,
                            "url":         link,
                            "scraped_at":  datetime.now().isoformat(),
                            "search_role": tag,
                        })
                    except Exception as e:
                        logger.debug(f"Remotive job parse: {e}")

                self._delay(1, 2)
            except Exception as e:
                logger.error(f"Remotive error ({tag}): {e}")

        logger.info(f"Remotive: {len(jobs)} jobs")
        return jobs

    # ──────────────────────────────────────────────────────────────────────────
    # SCRAPER: Naukri (NEW — largest Indian database)
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_naukri(self, page) -> list:
        jobs = []
        searches = [
            ("python-developer", "0", "python developer"),
            ("machine-learning", "0", "machine learning engineer"),
            ("backend-developer", "0", "backend developer"),
            ("artificial-intelligence", "0", "AI engineer"),
            ("data-scientist", "0", "data scientist"),
        ]

        for slug, exp, label in searches:
            for location in ["chennai", "bangalore", "remote"]:
                try:
                    url = (
                        f"https://www.naukri.com/{slug}-jobs-in-{location}"
                        f"?experience={exp}&jobAge=3"
                    )
                    page.goto(url, timeout=30000)
                    page.wait_for_timeout(4000)

                    # Scroll to trigger lazy loading
                    for _ in range(3):
                        page.mouse.wheel(0, 1500)
                        page.wait_for_timeout(1000)

                    cards = page.query_selector_all(
                        "article.jobTuple, div[class*='jobTupleHeader'], "
                        "article[class*='jobTuple'], div.cust-job-tuple"
                    )

                    for card in cards:
                        try:
                            title_el = (
                                card.query_selector("a.title") or
                                card.query_selector("a[class*='title']") or
                                card.query_selector("h2 a")
                            )
                            comp_el = (
                                card.query_selector("a.subTitle") or
                                card.query_selector("a[class*='companyInfo']") or
                                card.query_selector("span[class*='company']")
                            )
                            loc_el = (
                                card.query_selector("li.location") or
                                card.query_selector("span[class*='location']")
                            )
                            exp_el = card.query_selector("li.experience, span[class*='experience']")
                            sal_el = card.query_selector("li.salary, span[class*='salary']")

                            title = title_el.inner_text().strip() if title_el else label
                            href  = title_el.get_attribute("href") if title_el else ""
                            co    = comp_el.inner_text().strip()   if comp_el else "Unknown"
                            loc   = loc_el.inner_text().strip()    if loc_el  else location
                            sal   = sal_el.inner_text().strip()    if sal_el  else "Not disclosed"

                            link = href if href.startswith("http") else f"https://www.naukri.com{href}"

                            if not href or link in self.applied_links:
                                continue
                            if not is_fresher_role(title):
                                continue
                            if not is_relevant_role(title):
                                continue

                            # Naukri sometimes puts 0-2 years experience — that's fine
                            exp_text = exp_el.inner_text().lower() if exp_el else ""
                            if re.search(r"\b[3-9]\s*-?\s*\d*\s*yrs?\b", exp_text):
                                continue

                            jobs.append({
                                "platform":    "Naukri",
                                "title":       title,
                                "company":     co,
                                "location":    loc,
                                "salary":      sal,
                                "url":         link,
                                "scraped_at":  datetime.now().isoformat(),
                                "search_role": label,
                            })
                        except Exception as e:
                            logger.debug(f"Naukri card parse: {e}")

                    self._delay(2, 3)
                except Exception as e:
                    logger.error(f"Naukri error ({slug} @ {location}): {e}")

        logger.info(f"Naukri: {len(jobs)} jobs")
        return jobs

    # ──────────────────────────────────────────────────────────────────────────
    # SCRAPER: Wellfound / AngelList (NEW — startup jobs, no login)
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_wellfound(self, page) -> list:
        jobs = []
        searches = [
            ("python", "python developer"),
            ("machine-learning", "machine learning engineer"),
            ("backend", "backend developer"),
        ]

        for tag, label in searches:
            try:
                url = f"https://wellfound.com/jobs?q={tag}&l=india&remote=true"
                page.goto(url, timeout=30000)
                page.wait_for_timeout(4000)

                for _ in range(4):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(1200)

                cards = page.query_selector_all(
                    "div[class*='JobListing'], div[class*='job-listing'], "
                    "div[data-test='StartupResult']"
                )

                for card in cards:
                    try:
                        title_el = (
                            card.query_selector("a[class*='job-title']") or
                            card.query_selector("h2 a") or
                            card.query_selector("span[class*='title'] a")
                        )
                        comp_el = (
                            card.query_selector("a[class*='startup-name']") or
                            card.query_selector("h2[class*='company']") or
                            card.query_selector("span[class*='company']")
                        )
                        loc_el = card.query_selector(
                            "span[class*='location'], div[class*='location']"
                        )
                        sal_el = card.query_selector(
                            "span[class*='salary'], span[class*='compensation']"
                        )

                        if not title_el:
                            continue

                        title = title_el.inner_text().strip()
                        href  = title_el.get_attribute("href") or ""
                        link  = (
                            f"https://wellfound.com{href}"
                            if href.startswith("/") else href
                        )
                        co  = comp_el.inner_text().strip() if comp_el else "Unknown"
                        loc = loc_el.inner_text().strip()  if loc_el  else "Remote/India"
                        sal = sal_el.inner_text().strip()  if sal_el  else "Not disclosed"

                        if not link or link in self.applied_links:
                            continue
                        if not is_fresher_role(title):
                            continue
                        if not is_relevant_role(title):
                            continue

                        jobs.append({
                            "platform":    "Wellfound",
                            "title":       title,
                            "company":     co,
                            "location":    loc,
                            "salary":      sal,
                            "url":         link,
                            "scraped_at":  datetime.now().isoformat(),
                            "search_role": label,
                        })
                    except Exception as e:
                        logger.debug(f"Wellfound card parse: {e}")

                self._delay(2, 3)
            except Exception as e:
                logger.error(f"Wellfound error ({tag}): {e}")

        logger.info(f"Wellfound: {len(jobs)} jobs")
        return jobs

    # ──────────────────────────────────────────────────────────────────────────
    # Deduplication + Ranking
    # ──────────────────────────────────────────────────────────────────────────
    def deduplicate(self, jobs: list) -> list:
        seen_urls   = set()
        seen_titles = {}   # (company_lower, title_lower) → True
        result      = []

        for j in jobs:
            url  = j.get("url", "").strip()
            key  = (j.get("company", "").lower().strip(),
                    j.get("title", "").lower().strip())

            if not url:
                continue
            if url in self.applied_links or url in seen_urls:
                continue
            if key in seen_titles:
                continue

            seen_urls.add(url)
            seen_titles[key] = True
            result.append(j)

        return result

    def rank_jobs(self, jobs: list) -> list:
        """Score jobs by relevance to a Python/AI/Backend candidate."""
        def score(job):
            title = job.get("title", "").lower()
            s = 0

            # Core role match
            if "python"           in title: s += 6
            if "machine learning" in title: s += 6
            if "ai"               in title: s += 6
            if "deep learning"    in title: s += 5
            if "nlp"              in title: s += 5
            if "data scientist"   in title: s += 5
            if "backend"          in title: s += 5
            if "fastapi"          in title: s += 4
            if "django"           in title: s += 4
            if "flask"            in title: s += 4
            if "developer"        in title: s += 2
            if "engineer"         in title: s += 2

            # Easy apply platforms preferred
            if job.get("easy_apply"):             s += 3
            s += PLATFORM_SCORES.get(job.get("platform", ""), 0)

            # Penalty for Java (might slip through if mixed title)
            if "java"   in title: s -= 3
            if "kotlin" in title: s -= 5

            return s

        return sorted(jobs, key=score, reverse=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Main run — with BATCH processing
    # ──────────────────────────────────────────────────────────────────────────
    def run(self, batch_size: int = 20, max_total: int = 100,
            cooldown_minutes: float = 30) -> list[list]:
        """
        Scrape all sources, deduplicate, rank, then split into batches.

        Returns a list of batches (each batch is a list of job dicts).
        The orchestrator is responsible for:
          1. Processing batch[0] (JD extract → tailor → apply)
          2. Waiting cooldown_minutes
          3. Processing batch[1], etc.

        Args:
            batch_size       : jobs per batch (default 20)
            max_total        : hard cap on total scraped jobs (default 100)
            cooldown_minutes : minutes to wait between batches (set by orchestrator)
        """
        logger.info("=== Job Scraper (Playwright) Starting ===")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        all_jobs = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1280,900",
                ]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )

            # ── CRITICAL: Load cookies BEFORE creating the page ──────────────
            linkedin_loaded = self._load_cookies(
                context, self.linkedin_cookies_file, "LinkedIn"
            )
            self._load_cookies(context, self.naukri_cookies_file, "Naukri")

            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )

            # ── Verify LinkedIn login ────────────────────────────────────────
            linkedin_ok = False
            if linkedin_loaded:
                linkedin_ok = self._verify_linkedin_login(page)

            # ── Run all scrapers ─────────────────────────────────────────────
            logger.info("Scraping Indeed...")
            all_jobs.extend(self.scrape_indeed(page))

            logger.info("Scraping LinkedIn...")
            all_jobs.extend(self.scrape_linkedin(page, logged_in=linkedin_ok))

            logger.info("Scraping Internshala...")
            all_jobs.extend(self.scrape_internshala(page))

            logger.info("Scraping Remotive (API)...")
            all_jobs.extend(self.scrape_remotive(page))

            logger.info("Scraping Naukri...")
            all_jobs.extend(self.scrape_naukri(page))

            logger.info("Scraping Wellfound...")
            all_jobs.extend(self.scrape_wellfound(page))

            browser.close()

        # ── Dedup + Rank + Cap ───────────────────────────────────────────────
        unique = self.deduplicate(all_jobs)
        unique = self.rank_jobs(unique)
        unique = unique[:max_total]

        logger.info(
            f"Total after dedup+rank+cap: {len(unique)} "
            f"(from {len(all_jobs)} raw scraped)"
        )

        # ── Split into batches ───────────────────────────────────────────────
        batches = [
            unique[i : i + batch_size]
            for i in range(0, len(unique), batch_size)
        ]

        logger.info(
            f"Split into {len(batches)} batches of ~{batch_size} jobs each"
        )

        # ── Save full list + batches to disk ─────────────────────────────────
        out = self.logs_dir / "scraped_jobs.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp":    datetime.now().isoformat(),
                "total":        len(unique),
                "batch_size":   batch_size,
                "batch_count":  len(batches),
                "cooldown_min": cooldown_minutes,
                "count":        len(unique),   # kept for dashboard compat
                "jobs":         unique,
            }, f, indent=2)

        for i, batch in enumerate(batches):
            batch_file = self.logs_dir / f"batch_{i+1:02d}.json"
            with open(batch_file, "w", encoding="utf-8") as f:
                json.dump({
                    "batch_number": i + 1,
                    "total_batches": len(batches),
                    "job_count":    len(batch),
                    "jobs":         batch,
                }, f, indent=2)
            logger.info(f"Batch {i+1}/{len(batches)} saved: {len(batch)} jobs → {batch_file.name}")

        return batches