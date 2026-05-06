import requests
import json
import re
import time
import logging

log = logging.getLogger("job_scraper")


class JobAIEvaluator:
    def __init__(self, model="qwen2.5:7b", base_url="http://localhost:11434"):
        self.model = model
        self.url = f"{base_url}/api/generate"

    def _build_prompt(self, job):
        return f"""
    You are evaluating job relevance for a Software Engineer fresher candidate based in India.
    
    Candidate:
    - Final year CS student
    - Interested in Software Engineering roles (Backend / Fullstack / AI)
    - Prefers location in India only
    
    GOOD roles:
    - Software Engineer, SDE, Backend, Fullstack, AI Engineer, Intern
    
    BAD roles:
    - Senior,Manager, Sales, HR, Operations, Non-technical roles
    
    Job:
    Title: {job.get("Title")}
    Location: {job.get("Location")}
    Company: {job.get("Company")}
    Department: {job.get("Department")}
    
    Return ONLY valid JSON:
    {{
      "fit": "Yes/Maybe/No",
      "score": 1-10,
      "reason": "short explanation"
    }}
    """

    def _call_model(self, prompt):
        try:
            response = requests.post(
                self.url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0}
                },
                timeout=60
            )
            log.info(response.text)
            return response.json().get("response", "")
        except Exception as e:
            log.error(f"Got an error while parsing response from LLM: {e}")
            return ""

    def _parse_response(self, text):
        try:
            json_str = re.search(r"\{.*\}", text, re.DOTALL).group()
            return json.loads(json_str)
        except Exception as e:
            log.error(f"Got an error while parsing response from LLM: {e}")
            return {
                "fit": "Unknown",
                "score": 0,
                "reason": "Parsing failed"
            }

    def evaluate_job(self, job):
        prompt = self._build_prompt(job)
        raw = self._call_model(prompt)
        parsed = self._parse_response(raw)

        job["ai_fit"] = parsed.get("fit")
        job["ai_score"] = parsed.get("score")
        job["ai_reason"] = parsed.get("reason")

        return job

    def evaluate_jobs(self, jobs, limit=400, delay=0.5):
        """
        Evaluate top N jobs (sorted already)
        """
        for i, job in enumerate(jobs[:limit]):
            log.info(f"AI evaluating {i + 1}/{limit}: {job.get('Title')}")

            self.evaluate_job(job)
            time.sleep(delay)  # avoid overload

        return jobs
