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

from app.agents.pm import PMAgent, PMOutput
from app.llm.base import LLMProvider
from app.workflow.engine import run_workflow, sse_manager
from app.core.database import AsyncSessionLocal, init_db
from app.models.run import AgentRun, AgentStep
from app.models.project import Project, Decision
from app.models.artifact import ProjectArtifact
from app.models.user import User

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
        if "Engineering Planner" in system_prompt or "Task Planner" in system_prompt or "Planner" in system_prompt:
            return '{"epic_title": "Epic", "epic_description": "Desc", "tasks": [], "confidence": 0.95}'
        if "Code Generator" in system_prompt or "Principal Software Engineer" in system_prompt:
            return '{"implementation_plan": "Plan", "files": [], "confidence": 0.95}'
        return '{"summary": "Mock summary", "requirements": ["Req 1"], "user_stories": ["Story 1"], "risks": ["Risk 1"], "decisions": ["Decision 1"], "confidence": 0.9}'

@pytest.fixture(autouse=True)
async def setup_db():
    # Initialize the test database tables
    await init_db()
    
    # Create a dummy user and project for test runs
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
    
    # Cleanup runs, steps, decisions, and artifacts after each test
    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete
        await db.execute(delete(Decision))
        await db.execute(delete(ProjectArtifact))
        await db.execute(delete(AgentStep))
        await db.execute(delete(AgentRun))
        await db.commit()

@pytest.mark.asyncio
async def test_pm_agent_validation_success():
    mock_json = '```json\n{"summary": "Test product summary", "requirements": ["Req A", "Req B"], "user_stories": ["Story A"], "risks": ["Risk A"], "decisions": ["Decision A"], "confidence": 0.88}\n```'
    mock_provider = MockLLMProvider([mock_json])
    
    pm = PMAgent(llm_provider=mock_provider)
    pm_output = await pm.run("Test Prompt")
    
    assert isinstance(pm_output, PMOutput)
    assert pm_output.summary == "Test product summary"
    assert pm_output.requirements == ["Req A", "Req B"]
    assert pm_output.confidence == 0.88

@pytest.mark.asyncio
async def test_pm_agent_retry_on_validation_failure():
    invalid_json = '{"summary": "Invalid JSON", "requirements": '
    valid_json = '{"summary": "Valid on second try", "requirements": ["Req 1"], "user_stories": ["Story 1"], "risks": ["Risk 1"], "decisions": ["Decision 1"], "confidence": 0.95}'
    
    mock_provider = MockLLMProvider([invalid_json, valid_json])
    pm = PMAgent(llm_provider=mock_provider)
    pm_output = await pm.run("Test Prompt")
    
    assert mock_provider.call_count == 2
    assert pm_output.summary == "Valid on second try"

@pytest.mark.asyncio
async def test_pm_agent_validation_max_failures():
    invalid_json = '{"summary": "Invalid JSON", "requirements": '
    mock_provider = MockLLMProvider([invalid_json, invalid_json])
    pm = PMAgent(llm_provider=mock_provider)
    
    with pytest.raises(ValueError) as excinfo:
        await pm.run("Test Prompt")
    
    assert "Failed to generate valid PM output after 2 attempts" in str(excinfo.value)
    assert mock_provider.call_count == 2

@pytest.mark.asyncio
async def test_workflow_engine_pm_integration():
    pm_response = '{"summary": "GST Filing Application", "requirements": ["Req 1"], "user_stories": ["Story 1"], "risks": ["Risk 1"], "decisions": ["Use SQLite for local", "Use REST APIs"], "confidence": 0.95}'
    arch_response = (
        '{"executive_summary": "Architecture summary", "architecture_overview": "Overview pattern", '
        '"recommended_stack": ["FastAPI", "SQLite"], "database_design": ["DDL table"], '
        '"api_design": ["POST /api/v1/tax"], "system_components": ["Tax calculator"], '
        '"tradeoffs": ["FastAPI vs Django"], "risks": ["Tax compliance update lag"], '
        '"scalability_considerations": ["Horizontal scale"], '
        '"decisions": [{"title": "DB Selection", "description": "Relational choice", "options": ["SQLite", "Mongo"], "selected_option": "SQLite", "rationale": "ACID"}], '
        '"confidence": 0.95}'
    )
    mock_provider = MockLLMProvider([pm_response, arch_response])
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Build a GST filing platform for Indian SMEs",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
            
        sse_queue = sse_manager.subscribe(run_id)
        
        await run_workflow("test-project-id", run_id, "Build a GST filing platform for Indian SMEs")
        
        async with AsyncSessionLocal() as db:
            db_run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            db_run = db_run_res.scalars().first()
            assert db_run.status == "COMPLETED"
            
            art_res = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.project_id == "test-project-id",
                    ProjectArtifact.artifact_type == "REQUIREMENTS"
                )
            )
            artifact = art_res.scalars().first()
            assert artifact is not None
            assert "GST Filing Application" in artifact.content
            assert "Use SQLite for local" in artifact.content
            
            dec_res = await db.execute(select(Decision).where(Decision.run_id == run_id))
            decisions = dec_res.scalars().all()
            assert len(decisions) >= 4  # Expected minimum count (PM + Architect + Reviewer) is satisfied
            decision_titles = [d.title for d in decisions]
            # PM decisions exist
            assert "Use SQLite for local" in decision_titles
            assert "Use REST APIs" in decision_titles
            # Architect decisions exist
            assert "DB Selection" in decision_titles
            # Reviewer decisions exist
            assert "Authentication concerns" in decision_titles
            
            step_res = await db.execute(select(AgentStep).where(AgentStep.run_id == run_id))
            steps = step_res.scalars().all()
            agent_names = [s.agent_name for s in steps]
            assert "PM" in agent_names
            
        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
            
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "PM_THINKING" in statuses
        assert "PM_COMPLETED" in statuses
        assert "COMPLETED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)

@pytest.mark.asyncio
async def test_workflow_engine_gemini_failures():
    mock_provider = MockLLMProvider([
        Exception("Gemini API rate limit exceeded"),
        Exception("Gemini API connection timeout"),
    ])
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Fail Prompt",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
            
        sse_queue = sse_manager.subscribe(run_id)
        
        await run_workflow("test-project-id", run_id, "Fail Prompt")
        
        async with AsyncSessionLocal() as db:
            db_run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            db_run = db_run_res.scalars().first()
            assert db_run.status == "FAILED"
            
            step_res = await db.execute(select(AgentStep).where(AgentStep.run_id == run_id))
            steps = step_res.scalars().all()
            assert any("Workflow execution crashed" in s.content for s in steps)
            
        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
            
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "PM_THINKING" in statuses
        assert "PM_FAILED" in statuses
        assert "FAILED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)
