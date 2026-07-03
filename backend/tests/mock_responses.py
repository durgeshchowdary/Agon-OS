import json


def pm_response(**overrides):
    payload = {
        "summary": "Mock summary",
        "requirements": ["Req 1"],
        "user_stories": ["Story 1"],
        "risks": ["Risk 1"],
        "decisions": ["Decision 1"],
        "confidence": 0.9,
    }
    payload.update(overrides)
    return json.dumps(payload)


def architect_response(**overrides):
    payload = {
        "executive_summary": "Summary",
        "architecture_overview": "Overview",
        "recommended_stack": ["React", "FastAPI"],
        "database_design": ["Table users"],
        "api_design": ["GET /users"],
        "system_components": ["Auth"],
        "tradeoffs": ["SQL vs NoSQL"],
        "risks": ["Auth latency"],
        "scalability_considerations": ["Caching"],
        "decisions": [
            {
                "title": "DB Choice",
                "description": "Relational choice",
                "options": ["Postgre", "Mongo"],
                "selected_option": "Postgre",
                "rationale": "ACID",
            }
        ],
        "confidence": 0.95,
    }
    payload.update(overrides)
    return json.dumps(payload)


def reviewer_response(**overrides):
    payload = {
        "executive_summary": "Review summary",
        "strengths": ["Str"],
        "weaknesses": ["Weak"],
        "scalability_issues": ["Scale"],
        "security_concerns": ["Security"],
        "cost_risks": ["Cost"],
        "architectural_gaps": ["Gap"],
        "alternative_approaches": ["Alt"],
        "review_decisions": [
            {
                "title": "Authentication concerns",
                "severity": "Medium",
                "recommendation": "Encrypt payload",
            }
        ],
        "confidence": 0.92,
    }
    payload.update(overrides)
    return json.dumps(payload)


def planner_response(**overrides):
    payload = {
        "epic_title": "Epic",
        "epic_description": "Desc",
        "tasks": [],
        "confidence": 0.95,
    }
    payload.update(overrides)
    return json.dumps(payload)


def codegen_response(**overrides):
    payload = {
        "implementation_plan": "Plan",
        "files": [],
        "confidence": 0.95,
    }
    payload.update(overrides)
    return json.dumps(payload)


def code_review_response(**overrides):
    payload = {
        "status": "PASS",
        "summary": "Generated code satisfies architecture, reuse, security, and test requirements.",
        "score": 100.0,
        "findings": [],
        "confidence": 0.96,
    }
    payload.update(overrides)
    return json.dumps(payload)


def response_for_prompt(system_prompt: str) -> str:
    if "Automated Code Reviewer" in system_prompt or "CodeReviewer" in system_prompt:
        return code_review_response()
    if "Principal System Architect" in system_prompt:
        return architect_response()
    if "Design Reviewer and QA" in system_prompt:
        return reviewer_response()
    if "Engineering Planner" in system_prompt or "Task Planner" in system_prompt or "Planner" in system_prompt:
        return planner_response()
    if "Code Generator" in system_prompt or "Principal Software Engineer" in system_prompt:
        return codegen_response()
    if "Lead Product Manager" in system_prompt:
        return pm_response()
    return pm_response()
