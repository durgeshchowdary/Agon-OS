import os
import sys

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test database environment variable before importing settings or app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agon_os.db"

import pytest
import asyncio
from sqlalchemy.future import select
from fastapi.testclient import TestClient

from app.core.database import AsyncSessionLocal, init_db
from app.agents.architect import ArchitectOutput
from app.agents.critic import ReviewerOutput
from app.agents.pm import PMOutput
from app.models.artifact import ProjectArtifact
from app.models.run import AgentRun, AgentStep, Approval
from app.models.user import User
from app.schemas.codegen import CodegenOutput
from app.schemas.code_reviewer import CodeReviewOutput, ReviewFinding
from app.schemas.planner import PlannerOutput
from app.services.code_reviewer import CodeReviewService
from app.main import app
from tests.mock_responses import (
    architect_response,
    code_review_response,
    codegen_response,
    planner_response,
    pm_response,
    reviewer_response,
)

@pytest.fixture(autouse=True)
async def setup_db():
    from app.models import Base
    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == "test@agon.ai"))
        user = res.scalars().first()
        from app.core.security import get_password_hash
        hashed = get_password_hash("strongpassword123")
        if not user:
            user = User(
                id="test-user-id",
                email="test@agon.ai",
                hashed_password=hashed
            )
            db.add(user)
        else:
            user.hashed_password = hashed
            db.add(user)
        await db.commit()
        await db.refresh(user)
        
    yield
    
    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete
        await db.execute(delete(Approval))
        await db.execute(delete(AgentStep))
        await db.execute(delete(AgentRun))
        await db.execute(delete(ProjectArtifact))
        await db.commit()

@pytest.fixture
def test_client():
    return TestClient(app)

@pytest.fixture
def auth_headers(test_client):
    login_res = test_client.post("/api/v1/auth/login", data={
        "username": "test@agon.ai",
        "password": "strongpassword123"
    })
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def calculate_review_status_and_score(findings: list[ReviewFinding]) -> tuple[str, float]:
    # Implements identical scoring rules as CodeReviewService for isolated logic check
    score = 100.0
    has_critical_or_high = False
    has_medium = False
    for f in findings:
        sev = f.severity.upper()
        if sev == "CRITICAL":
            score -= 30.0
            has_critical_or_high = True
        elif sev == "HIGH":
            score -= 15.0
            has_critical_or_high = True
        elif sev == "MEDIUM":
            score -= 5.0
            has_medium = True
        elif sev == "LOW":
            score -= 2.0
            
    score = max(0.0, score)
    status = "FAIL" if has_critical_or_high else ("WARNING" if has_medium else "PASS")
    return status, score

def test_scoring_and_status_logic():
    PMOutput.model_validate_json(pm_response())
    ArchitectOutput.model_validate_json(architect_response())
    ReviewerOutput.model_validate_json(reviewer_response())
    PlannerOutput.model_validate_json(planner_response())
    CodegenOutput.model_validate_json(codegen_response())
    CodeReviewOutput.model_validate_json(code_review_response())

    # 1. Test FAIL due to Critical finding
    f1 = ReviewFinding(
        category="Security",
        severity="Critical",
        file_path="backend/app/main.py",
        finding_title="SQL Injection",
        description="Raw SQL injection query found",
        recommendation="Use parameterization"
    )
    status, score = calculate_review_status_and_score([f1])
    assert status == "FAIL"
    assert score == 70.0

    # 2. Test FAIL due to High finding
    f2 = ReviewFinding(
        category="Architecture",
        severity="High",
        file_path="backend/app/main.py",
        finding_title="Signature mismatch",
        description="Signature does not match architecture spec",
        recommendation="Align attributes"
    )
    status, score = calculate_review_status_and_score([f2])
    assert status == "FAIL"
    assert score == 85.0

    # 3. Test WARNING due to Medium finding
    f3 = ReviewFinding(
        category="Maintainability",
        severity="Medium",
        file_path="backend/app/main.py",
        finding_title="Complex logic",
        description="Function calculate() exceeds 100 lines",
        recommendation="Split calculate into smaller methods"
    )
    status, score = calculate_review_status_and_score([f3])
    assert status == "WARNING"
    assert score == 95.0

    # 4. Test PASS with only Low findings
    f4 = ReviewFinding(
        category="Maintainability",
        severity="Low",
        file_path="backend/app/main.py",
        finding_title="Missing docstring",
        description="Class is missing docstring comments",
        recommendation="Add documentation"
    )
    status, score = calculate_review_status_and_score([f4])
    assert status == "PASS"
    assert score == 98.0

    # 5. Test score minimum bound is 0.0
    many_findings = [f1, f1, f1, f1, f2] # Deduct 135 points
    status, score = calculate_review_status_and_score(many_findings)
    assert status == "FAIL"
    assert score == 0.0

@pytest.mark.asyncio
async def test_code_review_service_integration():
    async with AsyncSessionLocal() as db:
        # Pre-seed run and artifacts
        run = AgentRun(
            id="test-review-run-id",
            project_id="test-project-id",
            status="RUNNING",
            current_stage="CodeGenerator",
            initial_prompt="Create tax calculator"
        )
        db.add(run)
        
        # Requirements
        prd = ProjectArtifact(
            project_id="test-project-id",
            run_id="test-review-run-id",
            artifact_type="REQUIREMENTS",
            title="Requirements",
            content="Must calculate sales tax",
            version=1,
            status="APPROVED"
        )
        # Architecture
        arch = ProjectArtifact(
            project_id="test-project-id",
            run_id="test-review-run-id",
            artifact_type="ARCHITECTURE",
            title="Architecture",
            content="FastAPI service mapping to sales tax calculators",
            version=1,
            status="APPROVED"
        )
        # Backlog
        backlog = ProjectArtifact(
            project_id="test-project-id",
            run_id="test-review-run-id",
            artifact_type="BACKLOG",
            title="Backlog",
            content='{"epic_title": "Tax Calc", "tasks": []}',
            version=1,
            status="APPROVED"
        )
        # Generated files
        gen_file = ProjectArtifact(
            project_id="test-project-id",
            run_id="test-review-run-id",
            artifact_type="GENERATED_FILE",
            title="backend/app/api/v1/tax.py",
            content="def get_tax(amount): return amount * 0.18",
            version=1,
            status="DRAFT"
        )
        db.add(prd)
        db.add(arch)
        db.add(backlog)
        db.add(gen_file)
        await db.commit()

        # Execute CodeReviewService
        review_output = await CodeReviewService.review_code(db, "test-project-id", "test-review-run-id")
        
        assert review_output is not None
        assert review_output.status in ("PASS", "WARNING", "FAIL")
        assert review_output.score is not None
        
        # Verify CODE_REVIEW artifact is stored
        artifact_res = await db.execute(
            select(ProjectArtifact)
            .where(ProjectArtifact.run_id == "test-review-run-id", ProjectArtifact.artifact_type == "CODE_REVIEW")
        )
        db_artifact = artifact_res.scalars().first()
        assert db_artifact is not None
        assert db_artifact.title == "Automated Code Review Report"
        
        # Verify AgentStep is logged
        step_res = await db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == "test-review-run-id", AgentStep.agent_name == "CodeReviewer")
        )
        db_step = step_res.scalars().first()
        assert db_step is not None
        assert "Report" in db_step.content
