"""
Agent 3: Resume Tailor
- Uses NEW google-genai SDK (google.genai) — old google.generativeai is deprecated
- Sequential processing with smart rate-limit backoff (no parallel 429 storms)
- Fixed JSON extraction: handles leading newlines and all edge cases
- Full-page A4 PDF, name centered, title below with spacing fix
- Forces: 4 ZeAI bullets (only experience), 3 projects x 3 bullets
- Problem→Solution bullet style, ATS keyword optimization
- Header is STATIC (never regenerated) — only content body is tailored

Install: pip install google-genai
Get key: https://aistudio.google.com/apikey  (free, no card)
.env:    GEMINI_API_KEY=AIzaSy...
"""

import json, logging, re, hashlib, time, os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.0-flash"

# Most sought-after ATS keywords for fresher software engineering roles in India
SKILL_KEYWORDS = [
    "python", "java", "fastapi", "flask", "spring boot", "rest api", "microservices",
    "docker", "kubernetes", "jenkins", "ci/cd", "mysql", "mongodb", "postgresql",
    "aws", "kafka", "jwt", "oauth", "machine learning", "deep learning", "llm",
    "transformers", "rag", "lora", "fine-tuning", "nlp", "opencv", "mediapipe",
    "git", "agile", "system design", "data structures", "algorithms", "oop",
    "devops", "mlops", "websockets", "roberta", "langchain", "redis", "celery",
    "django", "reactjs", "nodejs", "typescript", "pandas", "numpy", "scikit-learn",
    "tensorflow", "keras", "pytorch", "hugging face", "computer vision",
    "api development", "unit testing", "linux", "sql", "nosql", "json",
    "html", "css", "javascript", "ajax", "postman", "swagger", "openapi",
    "github actions", "aws ec2", "aws s3", "lambda", "serverless",
    "authentication", "authorization", "rbac", "encryption", "security",
    "scalability", "performance optimization", "caching", "message queue",
]

# NOTE: Only body content is tailored. Header (name, phone, email, links) is STATIC.
TAILORING_PROMPT = """You are an expert ATS-optimized resume writer for software engineering fresher roles in India.
Your output will be used to fill a single A4 page PDF. The resume MUST be content-rich and fill the entire page.

## CANDIDATE BASE RESUME:
{base_resume}

## TARGET JOB:
Title: {title}
Company: {company}
Job Description:
{jd_text}

## JD SKILLS DETECTED:
{jd_skills}

## MANDATORY RULES — follow every single one:

### TAILORED TITLE:
- Match the JD role title almost exactly (e.g., "Python Backend Developer | REST APIs | Microservices")
- Include 2-3 JD core technologies separated by pipes
- Must sound like a professional headline that an ATS would score highly

### SUMMARY (3 full sentences, 50-65 words total):
- Sentence 1: "Computer Science graduate (CGPA 8.6) with production experience in [2-3 JD-relevant technologies]."
- Sentence 2: Mention specific backend/AI skills matching the JD + "800+ LeetCode problems solved (Top 15% globally)"
- Sentence 3: What value the candidate brings to THIS specific role and company
- Embed at least 4 JD keywords naturally in the summary

### SKILLS (all 6 categories, 5-8 items each):
- Put JD-matching skills FIRST in each category (critical for ATS scanners)
- Categories: Languages, Backend and APIs, Databases, DevOps and Tools, Core CS, AI / ML
- Each item separated by commas
- Mirror exact JD phrases: "RESTful APIs" not "REST", "CI/CD pipelines" not "CI/CD"

### EXPERIENCE — ONLY ONE entry: ZeAI Soft
- Title: "Tech Trainee Intern → Software Engineer"
- Company: "ZeAI Soft"
- Duration: "Oct 2025 – Present"
- Subtitle: "Learning Management System – Full Stack Product Development"
- EXACTLY 5 bullet points, each 30-40 words (longer bullets fill the page better)
- Bullet format: "To [specific problem/challenge], [specific technology/approach] was [action verb + detail], achieving [quantifiable metric/outcome]."
- NEVER write "I did" or "I built" — use passive outcome language
- EVERY bullet MUST contain at least 1 keyword from the JD
- Prioritize bullets most relevant to JD skills. Reword existing bullets to match JD language.
- Keep ALL metrics: 99%+ uptime, 95% accuracy, 10+ APIs, JWT/RBAC, Jenkins CI/CD

### PROJECTS — EXACTLY 3 projects from base resume:
- Pick the 2 most relevant to the JD + 1 other from base resume
- Each project: name, duration, tech stack, and EXACTLY 3 bullets (30-40 words each)
- Bullet format: "Challenge/Problem: [what needed solving]. Solution: [what was built/done], resulting in [metric/outcome]."
- EVERY bullet MUST contain at least 1 keyword from the JD
- Keep ALL original metrics: 95%+ accuracy, 80% reduction, 100K conversations, 25% improvement, etc.

### ATS OPTIMIZATION (CRITICAL — this determines interview calls):
- Embed 20+ keywords from the JD naturally throughout the resume content
- Mirror exact phrases from JD when possible ("REST APIs" not just "APIs")
- Include both spelled-out and abbreviated forms (e.g., "Continuous Integration/Continuous Deployment (CI/CD)")
- Use the SAME action verbs found in the JD (e.g., if JD says "develop", use "developed")
- Distribute keywords across ALL sections — summary, skills, experience bullets, and project bullets
- Front-load important keywords in the first 5 words of each bullet point

## OUTPUT FORMAT — CRITICAL:
- Return ONLY a valid JSON object
- NO markdown, NO backticks, NO text before/after
- Start with {{ and end with }}
- Use this exact schema:

{{"tailored_title":"role title matching JD","summary":"sentence1. sentence2. sentence3.","skills":{{"Languages":"items","Backend and APIs":"items","Databases":"items","DevOps and Tools":"items","Core CS":"items","AI / ML":"items"}},"experience":[{{"title":"Tech Trainee Intern → Software Engineer","company":"ZeAI Soft","duration":"Oct 2025 – Present","subtitle":"Learning Management System – Full Stack Product Development","bullets":["b1","b2","b3","b4","b5"]}}],"projects":[{{"name":"project1","duration":"Mon YYYY – Mon YYYY","tech":"Tech1 | Tech2 | Tech3","bullets":["b1","b2","b3"]}},{{"name":"project2","duration":"Mon YYYY – Mon YYYY","tech":"Tech1 | Tech2","bullets":["b1","b2","b3"]}},{{"name":"project3","duration":"Mon YYYY – Mon YYYY","tech":"Tech1 | Tech2","bullets":["b1","b2","b3"]}}],"ats_keywords_used":["kw1","kw2","kw3","kw4","kw5","kw6","kw7","kw8","kw9","kw10","kw11","kw12","kw13","kw14","kw15","kw16","kw17","kw18","kw19","kw20"],"match_score":85,"skills_matched":["skill1","skill2","skill3"]}}"""


class ResumeTailor:
    def __init__(self, config_dir="config", data_dir="data"):
        self.config_dir  = Path(config_dir)
        self.data_dir    = Path(data_dir)
        self.resumes_dir = self.data_dir / "resumes"
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.index_file  = self.resumes_dir / "resume_index.json"

        with open(self.config_dir / "base_resume.json", encoding="utf-8") as f:
            self.base_resume = json.load(f)
        self.resume_index = self._load_index()

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set.\n"
                "Get free key: https://aistudio.google.com/apikey\n"
                "Add to .env: GEMINI_API_KEY=AIzaSy..."
            )
        # NEW SDK initialisation
        from google import genai
        self.client = genai.Client(api_key=api_key)
        logger.info(f"Gemini client ready ({GEMINI_MODEL})")

        # Track last API call time for global rate limiting
        self._last_call_time = 0
        self._min_interval = 6  # minimum seconds between API calls (10 RPM safe margin)

    def _load_index(self):
        if self.index_file.exists():
            with open(self.index_file, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_index(self):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.resume_index, f, indent=2)

    def _jd_hash(self, jd):
        return hashlib.md5(jd.encode()).hexdigest()[:12]

    def _safe_name(self, s):
        return re.sub(r"[^a-zA-Z0-9]", "_", s.strip())[:30]

    def _extract_jd_skills(self, jd):
        jd_lower = jd.lower()
        return [kw for kw in SKILL_KEYWORDS if kw in jd_lower]

    def _match_score(self, jd_skills):
        base_text = json.dumps(self.base_resume["skills"]).lower()
        matched   = sum(1 for s in jd_skills if s in base_text)
        return (matched / max(len(jd_skills), 1)) * 100

    def find_reusable_resume(self, jd_skills, threshold=85.0):
        for rid, meta in self.resume_index.items():
            stored  = set(meta.get("skills_matched", []))
            jd_set  = set(jd_skills)
            if not jd_set:
                continue
            overlap = len(stored & jd_set) / len(jd_set) * 100
            if overlap >= threshold:
                p = Path(meta["pdf_path"])
                if p.exists():
                    logger.info(f"Reusing resume ({overlap:.0f}%): {p.name}")
                    return str(p)
        return None

    def _rate_limit_wait(self):
        """Ensure minimum interval between API calls to avoid 429s."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug(f"Rate limit: waiting {wait:.1f}s before next API call")
            time.sleep(wait)
        self._last_call_time = time.time()

    def call_groq(self, job):
        from groq import Groq

        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not set.\n"
                "Get key: https://console.groq.com/\n"
                "Add to .env: GROQ_API_KEY=..."
            )

        client = Groq(api_key=api_key)

        jd      = job.get("jd_text", "")[:4500]
        company = job.get("company", "Unknown")
        title   = job.get("title", "Software Engineer")

        if not jd:
            return None

        jd_skills = self._extract_jd_skills(jd)

        prompt = TAILORING_PROMPT.format(
            base_resume=json.dumps(self.base_resume, indent=2),
            title=title,
            company=company,
            jd_text=jd,
            jd_skills=", ".join(jd_skills) if jd_skills else "general software engineering skills",
        )

        max_retries = 5

        for attempt in range(max_retries):
            try:
                self._rate_limit_wait()

                response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are an ATS resume optimizer that outputs ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=4000,
                response_format={"type": "json_object"}  # ✅ ADD THIS LINE
            )

                raw = response.choices[0].message.content.strip()

                # ── SAME JSON CLEANING LOGIC ─────────────────────────
                raw = re.sub(r"```(?:json)?", "", raw).strip()
                raw = raw.strip()

                start = raw.find("{")
                end   = raw.rfind("}") + 1

                if start == -1 or end == 0:
                    logger.warning(f"No JSON found (attempt {attempt+1})")
                    logger.debug(f"Raw: {raw[:300]}")
                    if attempt >= max_retries - 1:
                        return None
                    time.sleep(3)
                    continue

                json_str = raw[start:end]

                # Fix issues
                json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
                json_str = json_str.replace("\n", " ")
                json_str = json_str.replace("→", "->")

                result = json.loads(json_str)

                # Validate structure
                if not isinstance(result, dict):
                    raise ValueError("Not a dict")

                required = ["tailored_title", "summary", "skills", "experience", "projects"]
                missing = [k for k in required if k not in result]

                if missing:
                    logger.warning(f"Missing keys {missing}")
                    if attempt >= max_retries - 1:
                        return None
                    time.sleep(3)
                    continue

                return result

            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error attempt {attempt+1}: {e}")
                if attempt >= max_retries - 1:
                    return None
                time.sleep(5)

            except Exception as e:
                err = str(e).lower()

                if "rate" in err or "429" in err:
                    wait = 5 * (2 ** attempt)  # faster than Gemini
                    logger.warning(f"Groq rate limit. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"Groq API error: {e}")
                    if attempt >= max_retries - 1:
                        return None
                    time.sleep(3)

        return None

    def build_pdf(self, tailored, out_path):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.lib import colors
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer,
                Table, TableStyle, HRFlowable
            )
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT

            BLUE  = colors.HexColor("#1a56db")
            DARK  = colors.HexColor("#111827")
            GRAY  = colors.HexColor("#374151")
            LIGHT = colors.HexColor("#6b7280")
            GOLD  = colors.HexColor("#b8860b")

            doc = SimpleDocTemplate(
                str(out_path), pagesize=A4,
                leftMargin=10*mm, rightMargin=10*mm,
                topMargin=5*mm,   bottomMargin=4*mm,
            )

            SECTION_GAP    = 8   # pt before each section heading — fills the blank space
            INTER_PROJ_GAP = 4    # pt between projects

            def S(n, **kw):
                return ParagraphStyle(n, **kw)

            # ── CALIBRATED STYLES (fills 810 of 816pt available) ─────────
            # Header styles — name CENTERED, title below with clear gap
            name_s    = S("Nm", fontSize=18,  fontName="Helvetica-Bold",   textColor=DARK,  leading=22, spaceAfter=0, spaceBefore=0, alignment=TA_CENTER)
            title_s   = S("Ti", fontSize=9,   fontName="Helvetica-Oblique", textColor=GRAY,  leading=12, spaceAfter=2, spaceBefore=0, alignment=TA_CENTER)
            contact_s = S("Co", fontSize=7.5, fontName="Helvetica",         textColor=LIGHT, leading=10, spaceAfter=1, spaceBefore=0, alignment=TA_CENTER)
            link_s    = S("Lk", fontSize=7.2, fontName="Helvetica",         textColor=BLUE,  leading=10, spaceAfter=0, spaceBefore=0, alignment=TA_CENTER)

            # Section & body styles — generous but controlled
            sec_s     = S("Se", fontSize=8.5, fontName="Helvetica-Bold",    textColor=BLUE,  leading=11,   spaceBefore=0, spaceAfter=1.5)
            body_s    = S("Bo", fontSize=8,   fontName="Helvetica",         textColor=DARK,  leading=10.5, spaceAfter=1.5)
            bul_s     = S("Bu", fontSize=8,   fontName="Helvetica",         textColor=DARK,  leading=10.5, leftIndent=8,  spaceAfter=1.5)
            bold_s    = S("Bl", fontSize=8,   fontName="Helvetica-Bold",    textColor=DARK,  leading=10.5, spaceAfter=0.5)
            ital_s    = S("It", fontSize=7.8, fontName="Helvetica-Oblique", textColor=BLUE,  leading=10,   spaceAfter=0.5)
            rt_s      = S("Rt", fontSize=7.8, fontName="Helvetica-Oblique", textColor=LIGHT, leading=10,   alignment=TA_RIGHT)
            skill_cat = S("Sc", fontSize=8,   fontName="Helvetica",         textColor=DARK,  leading=10.5, spaceAfter=1)
            ach_s     = S("Ac", fontSize=8,   fontName="Helvetica",         textColor=DARK,  leading=10.5, leftIndent=8,  spaceAfter=1.5)

            def two_col(lp, rp):
                t = Table([[lp, rp]], colWidths=["72%", "28%"])
                t.setStyle(TableStyle([
                    ("VALIGN",        (0,0), (-1,-1), "TOP"),
                    ("LEFTPADDING",   (0,0), (-1,-1), 0),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 0),
                    ("TOPPADDING",    (0,0), (-1,-1), 0),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                ]))
                return t

            def section(heading):
                story.append(Spacer(1, SECTION_GAP))
                story.append(Paragraph(heading, sec_s))
                story.append(HRFlowable(width="100%", thickness=0.5, color=BLUE, spaceAfter=2))

            h    = self.base_resume["header"]
            edu  = self.base_resume["education"]
            achs = self.base_resume["achievements"]
            story = []

            # ── HEADER — STATIC, never regenerated by AI ──────────────────
            story.append(Paragraph(h["name"], name_s))
            story.append(Spacer(1, 3))
            story.append(Paragraph(
                tailored.get("tailored_title", h["title"]),
                title_s
            ))
            story.append(Paragraph(
                f'{h["phone"]}  |  {h["email"]}  |  {h["linkedin"]}',
                contact_s
            ))
            story.append(Paragraph(
                f'{h.get("github","")}  |  {h["leetcode"].split("|")[0].strip()}  |  {h.get("portfolio", "harishk-ml-engineer.netlify.app")}',
                link_s
            ))
            story.append(Spacer(1, 2))
            story.append(HRFlowable(width="100%", thickness=1.0, color=BLUE, spaceAfter=2))

            # ── PROFESSIONAL SUMMARY ──────────────────────────────────────
            section("PROFESSIONAL SUMMARY")
            story.append(Paragraph(
                tailored.get("summary", self.base_resume["summary"]),
                body_s
            ))

            # ── TECHNICAL SKILLS ──────────────────────────────────────────
            section("TECHNICAL SKILLS")
            skills = tailored.get("skills", self.base_resume["skills"])
            for cat, val in skills.items():
                if val and str(val).strip():
                    story.append(Paragraph(
                        f"<b><font color='#1a56db'>{cat}:</font></b>"
                        f"<font color='#374151'>  {val}</font>",
                        skill_cat
                    ))

            # ── PROFESSIONAL EXPERIENCE ───────────────────────────────────
            section("PROFESSIONAL EXPERIENCE")
            experience_list = tailored.get("experience", self.base_resume["experience"])
            for exp in experience_list[:1]:
                story.append(two_col(
                    Paragraph(f"<b>{exp['title']}</b>", bold_s),
                    Paragraph(f"<i>{exp.get('duration','')}</i>", rt_s),
                ))
                sub = exp.get("subtitle", "")
                co  = exp.get("company", "")
                if sub and co:
                    story.append(Paragraph(f"{co}  |  {sub}", ital_s))
                elif co:
                    story.append(Paragraph(co, ital_s))
                for b in exp.get("bullets", [])[:5]:
                    story.append(Paragraph(f"&#9658; {b}", bul_s))
                story.append(Spacer(1, 2))

            # ── KEY PROJECTS (3 projects) ─────────────────────────────────
            projs = tailored.get("projects", self.base_resume["projects"])[:3]
            if projs:
                section("KEY PROJECTS")
                for proj in projs:
                    story.append(two_col(
                        Paragraph(f"<b>{proj['name']}</b>", bold_s),
                        Paragraph(f"<i>{proj.get('duration','')}</i>", rt_s),
                    ))
                    tech = proj.get("tech", "")
                    if tech:
                        story.append(Paragraph(tech, ital_s))
                    for b in proj.get("bullets", [])[:3]:
                        story.append(Paragraph(f"&#9658; {b}", bul_s))
                    if proj != projs[-1]:           # not the last project
                        story.append(Spacer(1, INTER_PROJ_GAP))

            # ── EDUCATION ─────────────────────────────────────────────────
            section("EDUCATION")
            story.append(two_col(
                Paragraph(f"<b>{edu['degree']}</b>", bold_s),
                Paragraph(f"<i>{edu['duration']}</i>", rt_s),
            ))
            story.append(Paragraph(
                f"{edu['institution']}  |  CGPA: {edu['cgpa']}",
                ital_s
            ))

            # ── ACHIEVEMENTS & RECOGNITION ────────────────────────────────
            section("ACHIEVEMENTS & RECOGNITION")
            for a in achs[:4]:
                story.append(Paragraph(f"&#9658; {a}", ach_s))

            doc.build(story)
            logger.info(f"PDF saved: {out_path.name}")
            return True
        except Exception as e:
            logger.error(f"PDF build failed: {e}", exc_info=True)
            return False

    def process_job(self, job):
        company    = job.get("company", "Unknown")
        title      = job.get("title", "Role")
        jd_text    = job.get("jd_text", "")
        jd_skills  = self._extract_jd_skills(jd_text)
        base_match = self._match_score(jd_skills)

        existing = self.find_reusable_resume(jd_skills)
        if existing:
            return {"status": "reused", "resume_path": existing, "company": company, "title": title,
                    "url": job.get("url"), "platform": job.get("platform", ""),
                    "salary": job.get("salary", "Not disclosed"),
                    "location": job.get("location", ""), "match_score": base_match}

        tailored = self.call_groq(job)
        if not tailored:
            logger.warning(f"Gemini failed for {company}. Using base resume with enhancements.")
            tailored = {
                "tailored_title":    title,
                "summary":           self.base_resume["summary"],
                "skills":            self.base_resume["skills"],
                "experience":        [self.base_resume["experience"][0]],  # Only ZeAI Soft
                "projects":          self.base_resume["projects"][:3],
                "ats_keywords_used": jd_skills[:15],
                "match_score":       base_match,
                "skills_matched":    jd_skills,
            }

        date_str = datetime.now().strftime("%Y%m%d")
        safe_co  = self._safe_name(company)
        filename = f"{safe_co}_{date_str}.pdf"
        out_path = self.resumes_dir / filename
        counter  = 1
        while out_path.exists():
            filename = f"{safe_co}_{date_str}_{counter}.pdf"
            out_path = self.resumes_dir / filename
            counter += 1

        if not self.build_pdf(tailored, out_path):
            return None

        rid = self._jd_hash(jd_text)
        self.resume_index[rid] = {
            "pdf_path":       str(out_path),
            "company":        company,
            "title":          title,
            "skills_matched": tailored.get("skills_matched", jd_skills),
            "match_score":    tailored.get("match_score", base_match),
            "ats_keywords":   tailored.get("ats_keywords_used", []),
            "created_at":     datetime.now().isoformat(),
        }
        self._save_index()

        return {"status": "tailored", "resume_path": str(out_path), "company": company, "title": title,
                "url": job.get("url"), "platform": job.get("platform", ""),
                "salary": job.get("salary", "Not disclosed"), "location": job.get("location", ""),
                "match_score": tailored.get("match_score", base_match),
                "ats_keywords": tailored.get("ats_keywords_used", [])}

    def run(self, jobs, batch_number=1, output_queue=None):
        """Sequential processing. If output_queue provided, pushes each result
        immediately after PDF save for parallel application."""
        logger.info(f"=== Resume Tailor | Batch {batch_number} | {len(jobs)} jobs ===")
        results = []

        for i, job in enumerate(jobs):
            title   = job.get("title", "Role")
            company = job.get("company", "Unknown")
            logger.info(f"[{i+1}/{len(jobs)}] {title} @ {company}")

            try:
                r = self.process_job(job)
                if r:
                    results.append(r)
                    if output_queue is not None:
                        output_queue.put(r)       # apply thread picks this up immediately
            except Exception as e:
                logger.error(f"Error processing {title} @ {company}: {e}", exc_info=True)

            if i < len(jobs) - 1:
                time.sleep(2)

        # Sentinel: tells apply_worker thread in app.py to stop waiting
        if output_queue is not None:
            output_queue.put(None)

        tailored_count = sum(1 for r in results if r.get("status") == "tailored")
        reused_count   = sum(1 for r in results if r.get("status") == "reused")
        logger.info(f"Done: {tailored_count} tailored, {reused_count} reused")
        return results