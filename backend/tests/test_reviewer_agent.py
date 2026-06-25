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

from app.agents.critic import CriticAgent, ReviewerOutput
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
        return (
            '{"executive_summary": "Summary", "strengths": ["Str"], "weaknesses": ["Weak"], '
            '"scalability_issues": ["Scale"], "security_concerns": ["Security"], "cost_risks": ["Cost"], '
            '"architectural_gaps": ["Gap"], "alternative_approaches": ["Alt"], '
            '"review_decisions": [{"title": "Single point of failure", "severity": "High", "recommendation": "Redundancy"}], '
            '"confidence": 0.95}'
        )

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
async def test_reviewer_agent_validation_success():
    mock_json = (
        '```json\n'
        '{"executive_summary": "Review summary", "strengths": ["High auth speed"], '
        '"weaknesses": ["Sync database writes"], "scalability_issues": ["No DB read replication"], '
        '"security_concerns": ["Storing plaintext keys"], "cost_risks": ["High VM cost"], '
        '"architectural_gaps": ["No audit trail"], "alternative_approaches": ["Write to queues"], '
        '"review_decisions": [{"title": "Authentication concerns", "severity": "Medium", "recommendation": "Encrypt payload"}], '
        '"confidence": 0.91}\n'
        '```'
    )
    mock_provider = MockLLMProvider([mock_json])
    
    reviewer = CriticAgent(llm_provider=mock_provider)
    output = await reviewer.run("GST Platform", "PM Content", "Arch Content")
    
    assert isinstance(output, ReviewerOutput)
    assert output.executive_summary == "Review summary"
    assert "High auth speed" in output.strengths
    assert output.confidence == 0.91
    assert len(output.review_decisions) == 1
    assert output.review_decisions[0].title == "Authentication concerns"

@pytest.mark.asyncio
async def test_reviewer_agent_retry_on_validation_failure():
    invalid_json = '{"executive_summary": "Broken json",'
    valid_json = (
        '{"executive_summary": "Review valid on retry", "strengths": [], "weaknesses": [], '
        '"scalability_issues": [], "security_concerns": [], "cost_risks": [], '
        '"architectural_gaps": [], "alternative_approaches": [], '
        '"review_decisions": [], "confidence": 0.85}'
    )
    
    mock_provider = MockLLMProvider([invalid_json, valid_json])
    reviewer = CriticAgent(llm_provider=mock_provider)
    output = await reviewer.run("GST Platform", "PM Content", "Arch Content")
    
    assert mock_provider.call_count == 2
    assert output.executive_summary == "Review valid on retry"

@pytest.mark.asyncio
async def test_reviewer_agent_validation_max_failures():
    invalid_json = '{"executive_summary": "Broken json",'
    mock_provider = MockLLMProvider([invalid_json, invalid_json])
    reviewer = CriticAgent(llm_provider=mock_provider)
    
    with pytest.raises(ValueError) as excinfo:
        await reviewer.run("GST Platform", "PM Content", "Arch Content")
    
    assert "Failed to generate valid Reviewer output after 2 attempts" in str(excinfo.value)
    assert mock_provider.call_count == 2

@pytest.mark.asyncio
async def test_workflow_engine_reviewer_integration():
    pm_response = '{"summary": "PRD summary", "requirements": ["Req A"], "user_stories": ["Story A"], "risks": ["Risk A"], "decisions": ["PM dec"], "confidence": 0.95}'
    arch_response = (
        '{"executive_summary": "Arch summary", "architecture_overview": "Overview", '
        '"recommended_stack": ["React", "SQLite"], "database_design": ["DDL"], '
        '"api_design": ["GET /api"], "system_components": ["API Gateway"], '
        '"tradeoffs": ["NoSQL"], "risks": ["Auth latency"], "scalability_considerations": ["Scaling"], '
        '"decisions": [{"title": "DBChoice", "description": "Relational choice", "options": ["Postgres", "SQLite"], "selected_option": "SQLite", "rationale": "Simple"}], '
        '"confidence": 0.95}'
    )
    rev_response = (
        '{"executive_summary": "Review summary", "strengths": ["Str"], "weaknesses": ["Weak"], '
        '"scalability_issues": ["Scale"], "security_concerns": ["Security"], "cost_risks": ["Cost"], '
        '"architectural_gaps": ["Gap"], "alternative_approaches": ["Alt"], '
        '"review_decisions": [{"title": "Authentication concerns", "severity": "Medium", "recommendation": "Encrypt payload"}], '
        '"confidence": 0.92}'
    )

    class FullMockLLMProvider(LLMProvider):
        def __init__(self):
            self.call_count = 0
        async def generate(self, system_prompt: str, user_prompt: str) -> str:
            self.call_count += 1
            if "Lead Product Manager" in system_prompt:
                return pm_response
            elif "Principal System Architect" in system_prompt:
                return arch_response
            elif "Design Reviewer and QA" in system_prompt:
                return rev_response
            return ""

    mock_provider = FullMockLLMProvider()
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Full Flow Prompt",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
            
        sse_queue = sse_manager.subscribe(run_id)
        
        await run_workflow("test-project-id", run_id, "Full Flow Prompt")
        
        async with AsyncSessionLocal() as db:
            db_run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            db_run = db_run_res.scalars().first()
            assert db_run.status == "COMPLETED"
            
            # Verify ARCHITECTURE_REVIEW artifact was saved
            art_res = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.project_id == "test-project-id",
                    ProjectArtifact.artifact_type == "ARCHITECTURE_REVIEW"
                )
            )
            artifact = art_res.scalars().first()
            assert artifact is not None
            assert "Architecture Review & Security Audit" in artifact.content
            assert "Review summary" in artifact.content
            
            # Verify decisions table
            dec_res = await db.execute(select(Decision).where(Decision.run_id == run_id))
            decisions = dec_res.scalars().all()
            # 1 PM decision (string), 1 Architect decision, 1 Reviewer decision
            assert len(decisions) == 3
            
            review_decision = [d for d in decisions if d.title == "Authentication concerns"][0]
            assert review_decision.selected_option == "Medium"  # severity mapped to selected_option
            assert review_decision.description == "Encrypt payload"  # recommendation mapped to description
            
        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
            
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "ARCHITECT_STARTED" in statuses
        assert "REVIEWER_STARTED" in statuses
        assert "REVIEWER_THINKING" in statuses
        assert "REVIEWER_COMPLETED" in statuses
        assert "COMPLETED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)

@pytest.mark.asyncio
async def test_workflow_engine_reviewer_failures():
    # PM & Architect succeed, but Reviewer fails
    pm_response = '{"summary": "PRD summary", "requirements": ["Req A"], "user_stories": ["Story A"], "risks": ["Risk A"], "decisions": ["PM dec"], "confidence": 0.95}'
    arch_response = (
        '{"executive_summary": "Arch summary", "architecture_overview": "Overview", '
        '"recommended_stack": ["React", "SQLite"], "database_design": ["DDL"], '
        '"api_design": ["GET /api"], "system_components": ["API Gateway"], '
        '"tradeoffs": ["NoSQL"], "risks": ["Auth latency"], "scalability_considerations": ["Scaling"], '
        '"decisions": [], "confidence": 0.95}'
    )

    class FailedReviewerMockProvider(LLMProvider):
        async def generate(self, system_prompt: str, user_prompt: str) -> str:
            if "Lead Product Manager" in system_prompt:
                return pm_response
            elif "Principal System Architect" in system_prompt:
                return arch_response
            elif "Design Reviewer and QA" in system_prompt:
                raise Exception("Gemini rate limits during QA review")
            return ""

    mock_provider = FailedReviewerMockProvider()
    
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Fail Flow Prompt",
                status="PENDING"
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id
            
        sse_queue = sse_manager.subscribe(run_id)
        
        await run_workflow("test-project-id", run_id, "Fail Flow Prompt")
        
        async with AsyncSessionLocal() as db:
            db_run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            db_run = db_run_res.scalars().first()
            assert db_run.status == "FAILED"
            
            # Check REQUIREMENTS & ARCHITECTURE persisted, but ARCHITECTURE_REVIEW not
            types_ok = ["REQUIREMENTS", "ARCHITECTURE"]
            for art_type in types_ok:
                art_res = await db.execute(
                    select(ProjectArtifact).where(
                        ProjectArtifact.project_id == "test-project-id",
                        ProjectArtifact.artifact_type == art_type
                    )
                )
                assert art_res.scalars().first() is not None
                
            rev_res = await db.execute(
                select(ProjectArtifact).where(
                    ProjectArtifact.project_id == "test-project-id",
                    ProjectArtifact.artifact_type == "ARCHITECTURE_REVIEW"
                )
            )
            assert rev_res.scalars().first() is None
            
        emitted_events = []
        while not sse_queue.empty():
            emitted_events.append(await sse_queue.get())
            
        statuses = [e.get("status") for e in emitted_events if "status" in e]
        assert "PM_STARTED" in statuses
        assert "ARCHITECT_STARTED" in statuses
        assert "REVIEWER_STARTED" in statuses
        assert "REVIEWER_THINKING" in statuses
        assert "REVIEWER_FAILED" in statuses
        assert "FAILED" in statuses
        
        sse_manager.unsubscribe(run_id, sse_queue)
