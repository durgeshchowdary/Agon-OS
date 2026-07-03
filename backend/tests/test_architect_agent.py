import os
import sys

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test database environment variable
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_agon_os.db"

import pytest
import asyncio
from unittest.mock import patch
from sqlalchemy.future import select

from app.agents.architect import ArchitectAgent, ArchitectOutput
from app.llm.base import LLMProvider
from app.workflow.engine import run_workflow, sse_manager
from app.core.database import AsyncSessionLocal, init_db
from app.models.run import AgentRun, AgentStep
from app.models.project import Project, Decision
from app.models.artifact import ProjectArtifact
from app.models.user import User
from tests.mock_responses import code_review_response, response_for_prompt

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
        return response_for_prompt(system_prompt)

@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == "test@agon.ai"))
        user = res.scalars().first()
        if not user:
            user = User(
                id="test-user-id",
                email="test@agon.ai",
                hashed_password="mocked_password"
            )
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
        await db.execute(delete(Decision))
        await db.execute(delete(ProjectArtifact))
        await db.execute(delete(AgentStep))
        await db.execute(delete(AgentRun))
        await db.commit()

@pytest.mark.asyncio
async def test_architect_agent_validation_success():
    mock_json = (
        '```json\n'
        '{"executive_summary": "Exec summary", "architecture_overview": "Arch overview", '
        '"recommended_stack": ["FastAPI", "SQLite"], "database_design": ["users table"], '
        '"api_design": ["POST /api/v1/auth"], "system_components": ["API Gateway"], '
        '"tradeoffs": ["Monolith vs Microservices"], "risks": ["Single point of failure"], '
        '"scalability_considerations": ["Vertical scale"], '
        '"decisions": [{"title": "DB Choice", "description": "Relational choice", "options": ["PostgreSQL", "SQLite"], "selected_option": "SQLite", "rationale": "Simple testing"}], '
        '"confidence": 0.92}\n'
        '```'
    )
    mock_provider = MockLLMProvider([mock_json])
    
    arch = ArchitectAgent(llm_provider=mock_provider)
    output = await arch.run("GST Filing Platform", "PM Artifact Content")
    
    assert isinstance(output, ArchitectOutput)
    assert output.executive_summary == "Exec summary"
    assert output.recommended_stack == ["FastAPI", "SQLite"]
    assert output.confidence == 0.92
    assert len(output.decisions) == 1
    assert output.decisions[0].title == "DB Choice"

@pytest.mark.asyncio
async def test_architect_agent_retry_on_validation_failure():
    invalid_json = '{"executive_summary": "Broken json",'
    valid_json = (
        '{"executive_summary": "Valid on second try", "architecture_overview": "Arch overview", '
        '"recommended_stack": ["FastAPI"], "database_design": ["users"], '
        '"api_design": ["GET /api"], "system_components": ["API"], "tradeoffs": ["None"], '
        '"risks": ["None"], "scalability_considerations": ["None"], '
        '"decisions": [], "confidence": 0.99}'
    )
    
    mock_provider = MockLLMProvider([invalid_json, valid_json])
    arch = ArchitectAgent(llm_provider=mock_provider)
    output = await arch.run("GST Platform", "PM Artifact Content")
    
    assert mock_provider.call_count == 2
    assert output.executive_summary == "Valid on second try"

@pytest.mark.asyncio
async def test_architect_agent_validation_max_failures():
    invalid_json = '{"executive_summary": "Broken json",'
    mock_provider = MockLLMProvider([invalid_json, invalid_json])
    arch = ArchitectAgent(llm_provider=mock_provider)
    
    with pytest.raises(ValueError) as excinfo:
        await arch.run("GST Platform", "PM Artifact Content")
    
    assert "Failed to generate valid Architect output after 2 attempts" in str(excinfo.value)
    assert mock_provider.call_count == 2

@pytest.mark.asyncio
async def test_workflow_engine_pm_architect_chaining():
    pm_response = '{"summary": "GST Filing PRD", "requirements": ["Req 1"], "user_stories": ["Story 1"], "risks": ["Risk 1"], "decisions": ["PM decision A"], "confidence": 0.9}'
    arch_response = (
        '{"executive_summary": "Architecture summary", "architecture_overview": "Overview pattern", '
        '"recommended_stack": ["FastAPI", "PostgreSQL"], "database_design": ["DDL table"], '
        '"api_design": ["POST /api/v1/tax"], "system_components": ["Tax calculator"], '
        '"tradeoffs": ["FastAPI vs Django"], "risks": ["Tax compliance update lag"], '
        '"scalability_considerations": ["Horizontal scale with containerization"], '
        '"decisions": [{"title": "DB Selection", "description": "Relational choice", "options": ["Postgres", "Mongo"], "selected_option": "Postgres", "rationale": "ACID compliance"}], '
        '"confidence": 0.95}'
    )
    
    class ChainedMockLLMProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
        async def generate(self, system_prompt: str, user_prompt: str) -> str:
            self.call_count += 1
            if "Lead Product Manager" in system_prompt:
                return pm_response
            elif "Principal System Architect" in system_prompt:
                return arch_response
            elif "Design Reviewer and QA" in system_prompt:
                return (
                    '{"executive_summary": "Review summary", "strengths": ["Str"], "weaknesses": ["Weak"], '
                    '"scalability_issues": ["Scale"], "security_concerns": ["Security"], "cost_risks": ["Cost"], '
                    '"architectural_gaps": ["Gap"], "alternative_approaches": ["Alt"], '
                    '"review_decisions": [{"title": "Authentication concerns", "severity": "Medium", "recommendation": "Encrypt payload"}], '
                    '"confidence": 0.92}'
                )
            elif "Engineering Planner" in system_prompt or "Task Planner" in system_prompt or "Planner" in system_prompt:
                return '{"epic_title": "Epic", "epic_description": "Desc", "tasks": [], "confidence": 0.95}'
            elif "Code Generator" in system_prompt or "Principal Software Engineer" in system_prompt:
                return '{"implementation_plan": "Plan", "files": [], "confidence": 0.95}'
            elif "Automated Code Reviewer" in system_prompt or "CodeReviewer" in system_prompt:
                return code_review_response()
            return response_for_prompt(system_prompt)

    mock_provider = ChainedMockLLMProvider()
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="GST Filing Platform",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
            
        sse_queue = sse_manager.subscribe(run_id)
        
        await run_workflow("test-project-id", run_id, "GST Filing Platform")
        
        async with AsyncSessionLocal() as db:
            db_run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            db_run = db_run_res.scalars().first()
            assert db_run.status == "COMPLETED"
            
            types = ["REQUIREMENTS", "ARCHITECTURE", "DATABASE", "API"]
            for art_type in types:
                art_res = await db.execute(
                    select(ProjectArtifact).where(
                        ProjectArtifact.project_id == "test-project-id",
                        ProjectArtifact.artifact_type == art_type
                    )
                )
                artifact = art_res.scalars().first()
                assert artifact is not None
                assert artifact.version == 1
                assert artifact.status == "DRAFT"
            
            dec_res = await db.execute(select(Decision).where(Decision.run_id == run_id))
            decisions = dec_res.scalars().all()
            assert len(decisions) >= 3
            
            architect_decision = [d for d in decisions if d.title == "DB Selection"][0]
            assert architect_decision.selected_option == "Postgres"
            assert architect_decision.rationale == "ACID compliance"
            assert "Mongo" in architect_decision.options
            
        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
            
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "PM_COMPLETED" in statuses
        assert "ARCHITECT_STARTED" in statuses
        assert "ARCHITECT_THINKING" in statuses
        assert "ARCHITECT_COMPLETED" in statuses
        assert "REVIEWER_STARTED" in statuses
        assert "REVIEWER_COMPLETED" in statuses
        assert "COMPLETED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)

@pytest.mark.asyncio
async def test_workflow_engine_architect_failures():
    pm_response = '{"summary": "GST Filing PRD", "requirements": ["Req 1"], "user_stories": ["Story 1"], "risks": ["Risk 1"], "decisions": ["PM decision A"], "confidence": 0.9}'
    
    class FailedArchitectMockProvider(LLMProvider):
        async def generate(self, system_prompt: str, user_prompt: str) -> str:
            if "Lead Product Manager" in system_prompt:
                return pm_response
            elif "Principal System Architect" in system_prompt:
                raise Exception("Gemini API connection error during architecture design")
            return ""

    mock_provider = FailedArchitectMockProvider()
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="GST Filing Platform",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
            
        sse_queue = sse_manager.subscribe(run_id)
        
        await run_workflow("test-project-id", run_id, "GST Filing Platform")
        
        async with AsyncSessionLocal() as db:
            db_run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            db_run = db_run_res.scalars().first()
            assert db_run.status == "FAILED"
            
            req_res = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.project_id == "test-project-id",
                    ProjectArtifact.artifact_type == "REQUIREMENTS"
                )
            )
            assert req_res.scalars().first() is not None
            
            arch_res = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.project_id == "test-project-id",
                    ProjectArtifact.artifact_type == "ARCHITECTURE"
                )
            )
            assert arch_res.scalars().first() is None
            
        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
            
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "PM_COMPLETED" in statuses
        assert "ARCHITECT_STARTED" in statuses
        assert "ARCHITECT_THINKING" in statuses
        assert "ARCHITECT_FAILED" in statuses
        assert "FAILED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)
