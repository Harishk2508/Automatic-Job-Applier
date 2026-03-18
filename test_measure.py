"""Generate PDF and measure remaining space."""
import sys, os, re
sys.path.insert(0, r'd:\Downloads\jobbot_v2_harish\jobbot2')
os.chdir(r'd:\Downloads\jobbot_v2_harish\jobbot2')
from dotenv import load_dotenv
load_dotenv()
from agents.resume_tailor import ResumeTailor
from pathlib import Path

tailor = ResumeTailor(config_dir="config", data_dir="data")
sample = {
    "tailored_title": "Python Backend Developer | REST APIs | Microservices",
    "summary": "Computer Science graduate (CGPA 8.6) with production experience building scalable REST APIs and microservices using Python, FastAPI, and Flask, backed by Docker-based containerized deployments. Proficient in JWT authentication, MySQL database optimization, and CI/CD pipeline automation with 800+ LeetCode problems solved (Top 15% globally). Eager to contribute backend engineering expertise to high-impact product teams requiring robust, well-tested API architectures.",
    "skills": {"Languages": "Python, Java, SQL, JavaScript (basics)", "Backend and APIs": "FastAPI, Flask, REST APIs, Microservices, MVC, JWT Authentication, WebSockets, Swagger/OpenAPI", "Databases": "MySQL, MongoDB, Indexing, Query Optimization, Redis (basics), PostgreSQL (basics)", "DevOps and Tools": "Docker, Jenkins, Git, GitHub, AWS (EC2, S3), Kafka (basics), Postman, Linux", "Core CS": "Data Structures and Algorithms, OOP, Operating Systems, Computer Networks, SDLC, Agile, System Design", "AI / ML": "LLM Fine-Tuning (LoRA / Unsloth), Transformers, RAG (basics), MLOps, OpenCV, MediaPipe, Hugging Face"},
    "experience": [{"title": "Tech Trainee Intern -> Software Engineer", "company": "ZeAI Soft", "duration": "Oct 2025 - Present", "subtitle": "Learning Management System - Full Stack Product Development", "bullets": ["To serve concurrent teacher-student workflows across LMS modules with zero downtime, 10+ production-grade REST API endpoints were architected using Python (Flask) and Microservices, achieving 99%+ uptime across all deployed modules.", "To prevent unauthorised access to protected resources, JWT-based authentication and Role-Based Access Control (RBAC) were integrated across all API routes, with endpoint validation and API documentation done via Postman and Swagger.", "To proactively identify students at academic risk, a Logistic Regression classifier (95% accuracy) was built to score performance based on assessments and engagement, with automated alerts pushed via in-app notifications backed by MySQL.", "To ensure consistent, regression-free deployments across the LMS platform, Jenkins and GitHub-based CI/CD pipelines were set up to automate build, test, and deployment cycles reducing manual deployment effort by 70%.", "To improve frontend reliability and user experience, responsive UI components were developed and integrated with backend APIs, enabling real-time data sync and smooth interaction across student, teacher, and admin dashboards."]}],
    "projects": [{"name": "Indian PII Detection and Redaction Web App", "duration": "Nov 2024 - Feb 2025", "tech": "Python | FastAPI | RoBERTa NER | Regex | Docker", "bullets": ["Problem: users unknowingly leak sensitive Indian PII into external AI tools. Solution: a real-time detection-and-redaction pipeline was built to sanitise input at the point of entry, with zero data persistence.", "Detection, validation, and redaction were separated into three independent modules using a pre-trained RoBERTa NER model combined with per-entity regex rules, enabling new PII types to be added without modifying existing logic or retraining.", "Exposed via a FastAPI REST endpoint (Swagger auto-docs at /docs) and containerised with Docker for portable, environment-consistent deployment across development and production environments."]}, {"name": "Real-Time Multiplayer Yoga Pose Analyzer", "duration": "Aug 2025 - Sep 2025", "tech": "Python | FastAPI | WebSockets | OpenCV | MediaPipe | Docker", "bullets": ["Challenge: evaluate yoga pose accuracy in real-time for two simultaneous users without expensive CNN training. Solution: a WebSocket-driven multiplayer system was implemented using geometric inference via MediaPipe joint landmarks.", "95%+ pose similarity accuracy across 50+ asanas was achieved through keypoint normalisation and vector-based joint angle comparison, reducing compute overhead by 80% over CNN-based approaches.", "Engineered modular FastAPI backend with OpenCV-powered real-time pose processing and multiplayer support, enabling seamless quiz and practice sessions for up to 4 concurrent participants with Docker-based deployment."]}, {"name": "Medical AI Chat System - LLM Fine-Tuning", "duration": "Aug 2024 - Nov 2024", "tech": "Python | LLaMA 3.2 (3B) | Unsloth | LoRA | Hugging Face", "bullets": ["Challenge: adapt a general LLM for medical QA without full fine-tuning cost. LLaMA 3.2 (3B) was fine-tuned on 100K real doctor-patient conversations using LoRA via Unsloth, cutting GPU memory by 60% vs full fine-tuning.", "Post-training evaluation on held-out medical questions showed a 25% improvement in domain-specific relevance and factual accuracy, validated through automated metrics and manual review on diverse medical specialties.", "Implemented hyperparameter tuning (learning rate scheduling, batch optimization, warmup steps) and mixed precision training on free-tier Google Colab T4 instances."]}],
    "match_score": 88, "skills_matched": ["python", "fastapi", "flask", "rest api", "docker", "mysql", "jwt"]
}

out = Path("data/resumes/TEST_layout_check.pdf")
tailor.build_pdf(sample, out)
with open(out, 'rb') as f:
    raw = f.read()
count = re.search(rb'/Count\s+(\d+)', raw)
pages = int(count.group(1)) if count else 0
print(f"Pages: {pages}")
print(f"Size: {len(raw)} bytes")
if pages == 1:
    print("PERFECT - Single page!")
else:
    print("WARNING - Multiple pages!")
