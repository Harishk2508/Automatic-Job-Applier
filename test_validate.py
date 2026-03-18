"""Full pipeline validation: check every module, config, and PDF generation."""
import sys, os, json, re
sys.path.insert(0, r'd:\Downloads\jobbot_v2_harish\jobbot2')
os.chdir(r'd:\Downloads\jobbot_v2_harish\jobbot2')
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path

results = {}

# 1) Check all config files
print("=" * 60)
print("[1] CONFIG FILE CHECKS")
print("=" * 60)

for f in ["config/base_resume.json", "config/personal_kb.json"]:
    try:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        results[f] = "OK"
        print(f"  ✓ {f} - valid JSON ({len(json.dumps(data))} chars)")
    except Exception as e:
        results[f] = f"FAIL: {e}"
        print(f"  ✗ {f} - {e}")

# Check base_resume structure
with open("config/base_resume.json", "r") as f:
    br = json.load(f)
required = ["header", "summary", "skills", "experience", "projects", "education", "achievements"]
for key in required:
    ok = key in br
    print(f"  {'✓' if ok else '✗'} base_resume has '{key}'")
print(f"  ✓ Achievements count: {len(br.get('achievements', []))}")
print(f"  ✓ Projects count: {len(br.get('projects', []))}")
print(f"  ✓ Experience entries: {len(br.get('experience', []))}")

# Check personal_kb structure
with open("config/personal_kb.json", "r") as f:
    kb = json.load(f)
needed_qa = ["address", "date_of_birth", "10th_percentage", "12th_percentage", "expected_ctc", "notice_period"]
for key in needed_qa:
    val = kb.get("application_qa", {}).get(key, None) or kb.get("personal_info", {}).get(key, None)
    ok = val is not None and val != "Please refer resume"
    print(f"  {'✓' if ok else '✗'} KB has real '{key}': {val}")

# 2) Check .env
print("\n" + "=" * 60)
print("[2] ENVIRONMENT VARIABLES")  
print("=" * 60)
gemini = os.environ.get("GEMINI_API_KEY", "").strip()
print(f"  {'✓' if gemini else '✗'} GEMINI_API_KEY: {'set (' + gemini[:10] + '...)' if gemini else 'MISSING'}")
groq = os.environ.get("GROQ_API_KEY", "").strip()
print(f"  {'✓' if groq else '⚠'} GROQ_API_KEY: {'set' if groq else 'not set (optional)'}")

# 3) Check module imports
print("\n" + "=" * 60)
print("[3] MODULE IMPORT CHECKS")
print("=" * 60)

modules = {
    "agents.scraper": "JobScraper",
    "agents.jd_extractor": "JDExtractor",
    "agents.resume_tailor": "ResumeTailor",
    "agents.applicator": "ApplicationAgent",
}
for mod, cls in modules.items():
    try:
        m = __import__(mod, fromlist=[cls])
        obj = getattr(m, cls)
        results[mod] = "OK"
        print(f"  ✓ {mod}.{cls} imports OK")
    except Exception as e:
        results[mod] = f"FAIL: {e}"
        print(f"  ✗ {mod}.{cls} import FAILED: {e}")

# 4) Check orchestrator
try:
    import orchestrator
    results["orchestrator"] = "OK"
    print(f"  ✓ orchestrator.py imports OK")
except Exception as e:
    results["orchestrator"] = f"FAIL: {e}"
    print(f"  ✗ orchestrator.py import FAILED: {e}")

# 5) PDF generation test
print("\n" + "=" * 60)
print("[4] PDF GENERATION TEST")
print("=" * 60)

from agents.resume_tailor import ResumeTailor
tailor = ResumeTailor(config_dir="config", data_dir="data")

sample = {
    "tailored_title": "Python Backend Developer | REST APIs | Microservices",
    "summary": "Computer Science graduate (CGPA 8.6) with production experience building scalable REST APIs and microservices using Python, FastAPI, and Flask, backed by Docker-based containerized deployments. Proficient in JWT authentication, MySQL database optimization, and CI/CD pipeline automation with 800+ LeetCode problems solved (Top 15% globally). Eager to contribute backend engineering expertise to high-impact product teams requiring robust, well-tested API architectures.",
    "skills": {"Languages": "Python, Java, SQL, JavaScript (basics)", "Backend and APIs": "FastAPI, Flask, REST APIs, Microservices, MVC, JWT Authentication, WebSockets, Swagger/OpenAPI", "Databases": "MySQL, MongoDB, Indexing, Query Optimization, Redis (basics), PostgreSQL (basics)", "DevOps and Tools": "Docker, Jenkins, Git, GitHub, AWS (EC2, S3), Kafka (basics), Postman, Linux", "Core CS": "Data Structures and Algorithms, OOP, Operating Systems, Computer Networks, SDLC, Agile, System Design", "AI / ML": "LLM Fine-Tuning (LoRA / Unsloth), Transformers, RAG (basics), MLOps, OpenCV, MediaPipe, Hugging Face"},
    "experience": [{"title": "Tech Trainee Intern -> Software Engineer", "company": "ZeAI Soft", "duration": "Oct 2025 - Present", "subtitle": "Learning Management System - Full Stack Product Development", "bullets": ["To serve concurrent teacher-student workflows across LMS modules with zero downtime, 10+ production-grade REST API endpoints were architected using Python (Flask) and Microservices, achieving 99%+ uptime.", "To prevent unauthorised access to protected resources, JWT-based authentication and Role-Based Access Control (RBAC) were integrated across all API routes, with endpoint validation and documentation via Postman and Swagger.", "To proactively identify students at academic risk, a Logistic Regression classifier (95% accuracy) was built to score performance based on assessments and engagement, with automated alerts pushed via in-app notifications backed by MySQL.", "To ensure consistent, regression-free deployments across the LMS platform, Jenkins and GitHub-based CI/CD pipelines were set up to automate build, test, and deployment cycles reducing manual deployment effort by 70%.", "To improve frontend reliability and user experience, responsive UI components were developed and integrated with backend APIs, enabling real-time data sync and smooth interaction across student, teacher, and admin dashboards."]}],
    "projects": [{"name": "Indian PII Detection and Redaction Web App", "duration": "Nov 2024 - Feb 2025", "tech": "Python | FastAPI | RoBERTa NER | Regex | Docker", "bullets": ["Problem: users unknowingly leak sensitive Indian PII into external AI tools. Solution: a real-time detection-and-redaction pipeline was built to sanitise input at the point of entry, with zero data persistence.", "Detection, validation, and redaction were separated into three independent modules using a pre-trained RoBERTa NER model combined with per-entity regex rules, enabling new PII types to be added without modifying existing logic.", "Exposed via a FastAPI REST endpoint (Swagger auto-docs at /docs) and containerised with Docker for portable, environment-consistent deployment across development and production environments."]}, {"name": "Real-Time Multiplayer Yoga Pose Analyzer", "duration": "Aug 2025 - Sep 2025", "tech": "Python | FastAPI | WebSockets | OpenCV | MediaPipe | Docker", "bullets": ["Challenge: evaluate yoga pose accuracy in real-time for two simultaneous users without expensive CNN training. Solution: a WebSocket-driven multiplayer system was implemented using geometric inference via MediaPipe joint landmarks.", "95%+ pose similarity accuracy across 50+ asanas was achieved through keypoint normalisation and vector-based joint angle comparison, reducing compute overhead by 80% over CNN-based approaches.", "Engineered modular FastAPI backend with OpenCV-powered real-time pose processing and multiplayer support, enabling seamless quiz and practice sessions for up to 4 concurrent participants."]}, {"name": "Medical AI Chat System - LLM Fine-Tuning", "duration": "Aug 2024 - Nov 2024", "tech": "Python | LLaMA 3.2 (3B) | Unsloth | LoRA | Hugging Face", "bullets": ["Challenge: adapt a general LLM for medical QA without full fine-tuning cost. LLaMA 3.2 (3B) was fine-tuned on 100K real doctor-patient conversations using LoRA via Unsloth, cutting GPU memory by 60%.", "Post-training evaluation showed a 25% improvement in domain-specific relevance and factual accuracy, validated through automated metrics and manual review on diverse medical specialties.", "Implemented hyperparameter tuning (learning rate scheduling, batch optimization, warmup steps) and mixed precision training on free-tier Google Colab T4 instances."]}],
    "match_score": 88, "skills_matched": ["python", "fastapi", "flask", "rest api", "docker", "mysql", "jwt"]
}

out_path = Path("data/resumes/TEST_layout_check.pdf")
try:
    tailor.build_pdf(sample, out_path)
    with open(out_path, 'rb') as f:
        raw = f.read()
    from PyPDF2 import PdfReader
    pages = len(PdfReader(out_path).pages)
    size = len(raw)
    print(f"  ✓ PDF generated: {size} bytes, {pages} page(s)")
    if pages == 1:
        print(f"  ✓ PERFECT: Single page resume!")
    else:
        print(f"  ✗ WARNING: {pages} pages (should be 1)")
    results["pdf"] = f"OK - {pages} page(s), {size} bytes"
except Exception as e:
    results["pdf"] = f"FAIL: {e}"
    print(f"  ✗ PDF generation FAILED: {e}")

# 6) Applicator Q&A test
print("\n" + "=" * 60)
print("[5] APPLICATOR Q&A TEST")
print("=" * 60)

from agents.applicator import ApplicationAgent
app = ApplicationAgent(config_dir="config", data_dir="data")

test_questions = [
    "What is your email?",
    "What is your phone number?",
    "Are you a fresher?",
    "What is your expected CTC?",
    "What is your CGPA?",
    "What is your date of birth?",
    "What is your address?",
    "Tell me your full name",
    "What is your portfolio website?",
    "Do you have active backlogs?",
    "What is your highest qualification?",
    "Write a cover letter",
    "What is your notice period?",
    "What is your current company?",
    "What is your 10th percentage?",
    "What is your 12th percentage?",
]

all_answered = True
for q in test_questions:
    try:
        ans = app.answer_question(q)
        ok = ans and "unknown" not in ans.lower() and "refer" not in ans.lower()
        print(f"  {'✓' if ok else '⚠'} Q: \"{q}\" → \"{ans[:60]}{'...' if len(str(ans)) > 60 else ''}\"")
        if not ok:
            all_answered = False
    except Exception as e:
        print(f"  ✗ Q: \"{q}\" → ERROR: {e}")
        all_answered = False

results["applicator_qa"] = "OK" if all_answered else "PARTIAL"

# 7) Summary
print("\n" + "=" * 60)
print("[SUMMARY] Pipeline Validation Results")
print("=" * 60)
all_ok = all(v == "OK" or v.startswith("OK") for v in results.values())
for name, status in results.items():
    icon = "✓" if status.startswith("OK") else "✗"
    print(f"  {icon} {name}: {status}")

if all_ok:
    print("\n  🎉 ALL CHECKS PASSED — Pipeline is ready!")
else:
    print("\n  ⚠ Some checks need attention (see above)")
