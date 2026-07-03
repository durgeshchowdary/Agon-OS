import os
import sys

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test database environment variable before importing settings or app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agon_os.db"

import pytest
import asyncio
import json
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

class RevisionMockLLMProvider(LLMProvider):
    def __init__(self, reviewer_approved_sequence: list):
        self.reviewer_approved_sequence = reviewer_approved_sequence
        self.reviewer_call_count = 0
        self.architect_call_count = 0
        self.pm_call_count = 0

    async def generate(self, system_prompt: str, user_prompt: str, response_schema=None) -> str:
        if "Lead Product Manager" in system_prompt:
            self.pm_call_count += 1
            return '{"summary": "PRD summary", "requirements": ["Req A"], "user_stories": ["Story A"], "risks": ["Risk A"], "decisions": ["PM dec"], "confidence": 0.95}'
        elif "Principal System Architect" in system_prompt:
            self.architect_call_count += 1
            return (
                '{"executive_summary": "Arch summary", "architecture_overview": "Overview", '
                f'"recommended_stack": ["React", "SQLite", "Cycle {self.architect_call_count}"], "database_design": ["DDL"], '
                '"api_design": ["GET /api"], "system_components": ["API Gateway"], '
                '"tradeoffs": ["NoSQL"], "risks": ["Auth latency"], "scalability_considerations": ["Scaling"], '
                '"decisions": [], "confidence": 0.95}'
            )
        elif "Design Reviewer and QA" in system_prompt:
            idx = min(self.reviewer_call_count, len(self.reviewer_approved_sequence) - 1)
            approved = self.reviewer_approved_sequence[idx]
            self.reviewer_call_count += 1
            status = "APPROVED" if approved else "REJECTED"
            return json.dumps({
                "approved": approved,
                "summary": f"Review {self.reviewer_call_count} status {status}",
                "strengths": ["Str"],
                "issues": ["Issue"],
                "recommendations": ["Rec"],
                "approval_status": status,
                "confidence": 0.92
            })
        elif "Engineering Planner" in system_prompt or "Task Planner" in system_prompt or "Planner" in system_prompt:
            return '{"epic_title": "Epic", "epic_description": "Desc", "tasks": [], "confidence": 0.95}'
        elif "Code Generator" in system_prompt or "Principal Software Engineer" in system_prompt:
            return '{"implementation_plan": "Plan", "files": [], "confidence": 0.95}'
        return "{}"

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
async def test_reviewer_approves_immediately():
    mock_provider = RevisionMockLLMProvider(reviewer_approved_sequence=[True])
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Immediate Approve Prompt",
                status="PENDING",
                review_cycle_number=1
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        sse_queue = sse_manager.subscribe(run_id)
        await run_workflow("test-project-id", run_id, "Immediate Approve Prompt", approvals_enabled=False)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "COMPLETED"
            assert db_run.review_cycle_number == 1

            # Check artifacts
            art_res = await db.execute(
                select(ProjectArtifact).where(ProjectArtifact.run_id == run_id)
            )
            artifacts = art_res.scalars().all()
            # Requirements, Architecture, Database, API, Architecture Review, Backlog, Plan
            assert len(artifacts) == 7
            for a in artifacts:
                assert a.review_cycle_number == 1

        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
        
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "ARCHITECT_STARTED" in statuses
        assert "REVIEWER_STARTED" in statuses
        assert "REVIEW_CYCLE_COMPLETED" in statuses
        assert "COMPLETED" in statuses
        assert "REVIEW_REJECTED" not in statuses

        sse_manager.unsubscribe(run_id, sse_queue)

@pytest.mark.asyncio
async def test_reviewer_rejects_once_then_approves():
    mock_provider = RevisionMockLLMProvider(reviewer_approved_sequence=[False, True])
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Reject then Approve Prompt",
                status="PENDING",
                review_cycle_number=1
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        sse_queue = sse_manager.subscribe(run_id)
        await run_workflow("test-project-id", run_id, "Reject then Approve Prompt", approvals_enabled=False)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "COMPLETED"
            assert db_run.review_cycle_number == 2

            # Check that version and cycle numbering for modified architecture artifacts are correct
            art_res = await db.execute(
                select(ProjectArtifact)
                .where(ProjectArtifact.run_id == run_id, ProjectArtifact.artifact_type == "ARCHITECTURE")
                .order_by(ProjectArtifact.version.asc())
            )
            arch_artifacts = art_res.scalars().all()
            assert len(arch_artifacts) == 2
            assert arch_artifacts[0].review_cycle_number == 1
            assert arch_artifacts[0].version == 1
            assert arch_artifacts[1].review_cycle_number == 2
            assert arch_artifacts[1].version == 2

        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
        
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        # Verify cycles
        cycles = [e.get("cycle") for e in emitted_events if "cycle" in e]
        assert "REVIEW_REJECTED" in statuses
        assert "ARCHITECT_REVISION_STARTED" in statuses
        assert "ARCHITECT_REVISION_COMPLETED" in statuses
        assert "REVIEW_CYCLE_COMPLETED" in statuses
        assert 1 in cycles
        assert 2 in cycles
        
        sse_manager.unsubscribe(run_id, sse_queue)

@pytest.mark.asyncio
async def test_reviewer_rejects_until_max_cycles():
    mock_provider = RevisionMockLLMProvider(reviewer_approved_sequence=[False, False, False, False])
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Reject to Max Prompt",
                status="PENDING",
                review_cycle_number=1
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        sse_queue = sse_manager.subscribe(run_id)
        await run_workflow("test-project-id", run_id, "Reject to Max Prompt", approvals_enabled=False)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "FAILED"
            assert db_run.review_cycle_number == 3  # MAX_REVIEW_CYCLES is 3

        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
        
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "REVIEW_REJECTED" in statuses
        assert "FAILED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)

@pytest.mark.asyncio
async def test_reviewer_approval_gates_interactive(test_client, auth_headers):
    mock_provider = RevisionMockLLMProvider(reviewer_approved_sequence=[False, True])
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Approval Gate Interactive Prompt",
                status="PENDING",
                review_cycle_number=1
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        # 1. Run PM
        await run_workflow("test-project-id", run_id, "Approval Gate Interactive Prompt", start_stage="PM", approvals_enabled=True)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "PM"
            pm_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "PM"))).scalars().first()
            assert pm_app.status == "PENDING"

        # 2. Approve PM
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "PM", "approved_by": "test_pm"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0) # wait for background task (Architect)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "Architect"
            arch_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "Architect", Approval.review_cycle_number == 1))).scalars().first()
            assert arch_app.status == "PENDING"

        # 3. Approve Architect (runs Reviewer next)
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Architect", "approved_by": "test_arch"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0) # wait for background task (Reviewer)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "Reviewer"
            # Reviewer Agent rejects, so the pending Approval has comments="AGENT_REJECTED"
            rev_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "Reviewer", Approval.review_cycle_number == 1))).scalars().first()
            assert rev_app.status == "PENDING"
            assert rev_app.comments == "AGENT_REJECTED"

        # 4. Human approves the Reviewer audit.
        # This triggers revision loop back to Architect for Cycle 2 in the background.
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Reviewer", "approved_by": "test_qa"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0) # wait for background task (Architect Cycle 2)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "Architect"
            assert db_run.review_cycle_number == 2
            
            # Verify new pending approval for Architect at cycle 2
            arch2_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "Architect", Approval.review_cycle_number == 2))).scalars().first()
            assert arch2_app.status == "PENDING"

        # 5. Approve Architect Cycle 2 (runs Reviewer Cycle 2 next)
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Architect", "approved_by": "test_arch"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "Reviewer"
            
            # Reviewer Agent approved this time
            rev2_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "Reviewer", Approval.review_cycle_number == 2))).scalars().first()
            assert rev2_app.status == "PENDING"
            assert rev2_app.comments == "AGENT_APPROVED"

        # 6. Approve Reviewer stage -> Transition to Planner stage
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Reviewer", "approved_by": "test_qa"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0)
        
        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "Planner"

        # 7. Approve Planner stage -> Transition to CodeGenerator stage
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "Planner", "approved_by": "test_pm"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "CodeGenerator"

        # 8. Approve CodeGenerator stage -> Transition to COMPLETED stage
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/approve",
            json={"stage": "CodeGenerator", "approved_by": "test_lead_dev"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        await asyncio.sleep(1.0)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "COMPLETED"
