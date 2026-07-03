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

from app.agents.planner import PlannerAgent
from app.schemas.planner import PlannerOutput
from app.workflow.engine import run_workflow, sse_manager
from app.core.database import AsyncSessionLocal, init_db
from app.models.run import AgentRun, AgentStep, Approval
from app.models.project import Project, Decision
from app.models.artifact import ProjectArtifact
from app.models.user import User
from tests.mock_responses import code_review_response

from fastapi.testclient import TestClient
from app.main import app

class MockLLMProvider:
    async def generate(self, system_prompt: str, user_prompt: str, response_schema=None) -> str:
        if "Automated Code Reviewer" in system_prompt or "CodeReviewer" in system_prompt:
            return code_review_response()
        if "Code Generator" in system_prompt or "Principal Software Engineer" in system_prompt:
            return '{"implementation_plan": "Plan content", "files": [{"path": "backend/app/api/v1/mock_temp.py", "content": "class Temp:\\n    pass\\n", "type": "code"}], "confidence": 0.99}'
        return (
            '{"epic_title": "Test Epic", "epic_description": "Objective summary", '
            '"tasks": [{"id": "TASK-101", "title": "Test Task", "description": "Desc", '
            '"complexity": "Low", "priority": "High", "estimate": "1 story point", '
            '"dependencies": [], "acceptance_criteria": ["Criteria A"], '
            '"subtasks": []}], "confidence": 0.98}'
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
async def test_planner_agent_output_validation():
    mock_provider = MockLLMProvider()
    agent = PlannerAgent(llm_provider=mock_provider)
    output = await agent.run("PRD reqs", "Arch designs", "Database designs", "API contracts")
    
    assert isinstance(output, PlannerOutput)
    assert output.epic_title == "Test Epic"
    assert len(output.tasks) == 1
    assert output.tasks[0].id == "TASK-101"
    
    # Verify markdown formatting works
    md = agent.format_to_markdown(output)
    assert "# Engineering Backlog: Test Epic" in md
    assert "[TASK-101] Test Task" in md

@pytest.mark.asyncio
async def test_planner_workflow_integration():
    mock_provider = MockLLMProvider()
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Workflow integration test prompt",
                status="PENDING",
                review_cycle_number=1
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        # Run PM, Architect, Reviewer, and Planner stages with approvals off
        # Write requirements first so Planner stage can load it
        async with AsyncSessionLocal() as db:
            prd_art = ProjectArtifact(
                project_id="test-project-id",
                run_id=run_id,
                artifact_type="REQUIREMENTS",
                title="PRD",
                content="PRD content",
                version=1
            )
            arch_art = ProjectArtifact(
                project_id="test-project-id",
                run_id=run_id,
                artifact_type="ARCHITECTURE",
                title="Architecture",
                content="Architecture content",
                version=1
            )
            db_art = ProjectArtifact(
                project_id="test-project-id",
                run_id=run_id,
                artifact_type="DATABASE",
                title="Database",
                content="Database content",
                version=1
            )
            api_art = ProjectArtifact(
                project_id="test-project-id",
                run_id=run_id,
                artifact_type="API",
                title="API",
                content="API content",
                version=1
            )
            db.add(prd_art)
            db.add(arch_art)
            db.add(db_art)
            db.add(api_art)
            await db.commit()

        sse_queue = sse_manager.subscribe(run_id)
        await run_workflow("test-project-id", run_id, "Workflow integration test prompt", start_stage="Planner", approvals_enabled=False)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            # Since approvals are off, Planner transitions directly to CodeGenerator and writes files, completing the run
            assert db_run.status == "COMPLETED"
            
            # Check that BACKLOG and IMPLEMENTATION_PLAN artifacts were created
            art_res = await db.execute(
                select(ProjectArtifact).where(ProjectArtifact.run_id == run_id)
            )
            artifacts = art_res.scalars().all()
            types = [a.artifact_type for a in artifacts]
            assert "BACKLOG" in types
            assert "IMPLEMENTATION_PLAN" in types
            assert "GENERATED_FILE" in types

        sse_manager.unsubscribe(run_id, sse_queue)
