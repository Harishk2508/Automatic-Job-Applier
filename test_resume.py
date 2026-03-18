from agents.resume_tailor import ResumeTailor

# 🔹 Create dummy job input
job = {
    "title": "Python Backend Developer",
    "company": "Test Company",
    "jd_text": """
    We are looking for a Python Backend Developer with experience in Flask, FastAPI,
    REST APIs, MySQL, Docker, and AWS. Knowledge of CI/CD pipelines and Git is required.
    """,
    "location": "Remote",
    "salary": "5-8 LPA"
}

# 🔹 Initialize
tailor = ResumeTailor()

# 🔹 Run for single job
result = tailor.process_job(job)

print("\n=== RESULT ===")
print(result)