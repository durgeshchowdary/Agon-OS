import os
import sys

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test database environment variable before importing settings or app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agon_os.db"

import pytest
import asyncio
from unittest.mock import patch
from sqlalchemy.future import select

from app.llm.base import LLMProvider
from app.workflow.engine import run_workflow, sse_manager
from app.core.database import AsyncSessionLocal, init_db
from app.models.run import AgentRun, AgentStep, Approval
from app.models.project import Project, Decision
from app.models.artifact import ProjectArtifact
from app.models.user import User

from fastapi.testclient import TestClient
from app.main import app

class MockLLMProvider(LLMProvider):
    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.call_count < len(self.responses):
            res = self.responses[self.call_count]
            self.call_count += 1
            if isinstance(res, Exception):
                raise res
            return res
        if "Principal System Architect" in system_prompt:
            return (
                '{"executive_summary": "Summary", "architecture_overview": "Overview", '
                '"recommended_stack": ["React", "FastAPI"], "database_design": ["Table users"], '
                '"api_design": ["GET /users"], "system_components": ["Auth"], "tradeoffs": ["SQL vs NoSQL"], '
                '"risks": ["Auth latency"], "scalability_considerations": ["Caching"], '
                '"decisions": [{"title": "DB Choice", "description": "Relational choice", "options": ["Postgre", "Mongo"], "selected_option": "Postgre", "rationale": "ACID"}], '
                '"confidence": 0.95}'
            )
        if "Design Reviewer and QA" in system_prompt:
            return (
                '{"executive_summary": "Review summary", "strengths": ["Str"], "weaknesses": ["Weak"], '
                '"scalability_issues": ["Scale"], "security_concerns": ["Security"], "cost_risks": ["Cost"], '
                '"architectural_gaps": ["Gap"], "alternative_approaches": ["Alt"], '
                '"review_decisions": [{"title": "Authentication concerns", "severity": "Medium", "recommendation": "Encrypt payload"}], '
                '"confidence": 0.92}'
            )
        return '{"summary": "Mock summary", "requirements": ["Req 1"], "user_stories": ["Story 1"], "risks": ["Risk 1"], "decisions": ["Decision 1"], "confidence": 0.9}'

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
            
        p_res = await db.execute(select(Project).where(Project.creator_id == user.id))
        project = p_res.scalars().first()
        if not project:
            project = Project(
                id="test-project-id",
                creator_id=user.id,
                name="Test Project",
                description="A test project for verification",
                domain="software_engineering"
            )
            db.add(project)
            await db.commit()
            
    yield
    
    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete
        await db.execute(delete(Approval))
        await db.execute(delete(Decision))
        await db.execute(delete(ProjectArtifact))
        await db.execute(delete(AgentStep))
        await db.execute(delete(AgentRun))
        await db.commit()

@pytest.fixture
def test_client():
    # Helper client
    return TestClient(app)

@pytest.fixture
def auth_headers(test_client):
    login_res = test_client.post("/api/v1/auth/login", data={
        "username": "test@agon.ai",
        "password": "strongpassword123"
    })
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_workflow_pause_and_resume_flow(test_client, auth_headers):
    # Set up mock response providers
    mock_provider = MockLLMProvider()
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Build an eCommerce platform",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        # 1. Run PM Stage
        await run_workflow("test-project-id", run_id, "Build an eCommerce platform", start_stage="PM", approvals_enabled=True)

        # Verify run is now in WAITING_APPROVAL status, stage PM
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = run_res.scalars().first()
            assert run_obj.status == "WAITING_APPROVAL"
            assert run_obj.current_stage == "PM"
            
            # Verify a PENDING approval record is stored
            app_res = await db.execute(
                select(Approval).where(Approval.run_id == run_id, Approval.stage == "PM")
            )
            approval = app_res.scalars().first()
            assert approval is not None
            assert approval.status == "PENDING"

        # 2. Approve PM Stage via API
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "PM", "approved_by": "john_pm", "comments": "Good reqs", "rationale": "Requirements complete"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "APPROVED"
        assert resp.json()["approved_by"] == "john_pm"
        assert resp.json()["rationale"] == "Requirements complete"

        # Wait for the background Architect task to execute and update status
        await asyncio.sleep(1.5)

        # Verify run is now in WAITING_APPROVAL status, stage Architect
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = run_res.scalars().first()
            assert run_obj.status == "WAITING_APPROVAL"
            assert run_obj.current_stage == "Architect"
            
            # Verify PM approval record was updated, and a new Architect PENDING approval was created
            pm_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "PM"))).scalars().first()
            assert pm_app.status == "APPROVED"
            
            arch_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "Architect"))).scalars().first()
            assert arch_app.status == "PENDING"

        # 3. Approve Architect Stage
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Architect", "approved_by": "jane_arch", "comments": "Stack matches", "rationale": "Database schema checked"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        await asyncio.sleep(1.5)

        # Verify run is now in WAITING_APPROVAL status, stage Reviewer
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = run_res.scalars().first()
            assert run_obj.status == "WAITING_APPROVAL"
            assert run_obj.current_stage == "Reviewer"

        # 4. Approve Reviewer Stage (Final complete)
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Reviewer", "approved_by": "qa_lead", "comments": "Risks addressed", "rationale": "All good"},
            headers=auth_headers
        )
        assert resp.status_code == 200

        # Verify final COMPLETED run state
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = run_res.scalars().first()
            assert run_obj.status == "COMPLETED"
            assert run_obj.completed_at is not None

@pytest.mark.asyncio
async def test_workflow_rejection_flow(test_client, auth_headers):
    mock_provider = MockLLMProvider()
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Build a billing portal",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        # Run PM & pause
        await run_workflow("test-project-id", run_id, "Build a billing portal", start_stage="PM", approvals_enabled=True)
        
        # Approve PM stage
        test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "PM"},
            headers=auth_headers
        )
        await asyncio.sleep(1.2)

        # Confirm we are at Architect stage waiting approval
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = run_res.scalars().first()
            assert run_obj.status == "WAITING_APPROVAL"
            assert run_obj.current_stage == "Architect"

        # Reject Architect Stage
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/reject",
            json={"stage": "Architect", "approved_by": "senior_reviewer", "comments": "Redesign DB schema", "rationale": "Missing index"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "REJECTED"

        # Verify status goes back to WAITING_APPROVAL for PM (previous stage), allowing rerun of Architect
        async with AsyncSessionLocal() as db:
            run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = run_res.scalars().first()
            assert run_obj.status == "WAITING_APPROVAL"
            assert run_obj.current_stage == "PM"
            
            # Verify the rejection record exists
            rej_app = (await db.execute(
                select(Approval).where(Approval.run_id == run_id, Approval.stage == "Architect", Approval.status == "REJECTED")
            )).scalars().first()
            assert rej_app is not None
            assert rej_app.comments == "Redesign DB schema"
            
            # Verify a new PENDING PM approval was created
            new_pm = (await db.execute(
                select(Approval).where(Approval.run_id == run_id, Approval.stage == "PM", Approval.status == "PENDING")
            )).scalars().first()
            assert new_pm is not None

@pytest.mark.asyncio
async def test_invalid_approvals_validation(test_client, auth_headers):
    async with AsyncSessionLocal() as db:
        run = AgentRun(
            project_id="test-project-id",
            initial_prompt="Validations run",
            status="WAITING_APPROVAL",
            current_stage="PM"
        )
        db.add(run)
        # Add a PM pending approval record
        approval = Approval(run=run, stage="PM", status="PENDING")
        db.add(approval)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    # 1. Try to approve a non-existent or invalid stage
    resp = test_client.post(
        f"/api/v1/runs/{run_id}/approve",
        json={"stage": "SecurityGate"},
        headers=auth_headers
    )
    assert resp.status_code == 400
    assert "Invalid approval stage name" in resp.json()["detail"]

    # 2. Try to skip and approve Architect stage while waiting for PM
    resp = test_client.post(
        f"/api/v1/runs/{run_id}/approve",
        json={"stage": "Architect"},
        headers=auth_headers
    )
    assert resp.status_code == 400
    assert "Cannot approve stage Architect" in resp.json()["detail"]

    # 3. Try to reject Architect when waiting for PM
    resp = test_client.post(
        f"/api/v1/runs/{run_id}/reject",
        json={"stage": "Architect"},
        headers=auth_headers
    )
    assert resp.status_code == 400
    assert "Cannot reject stage Architect" in resp.json()["detail"]
