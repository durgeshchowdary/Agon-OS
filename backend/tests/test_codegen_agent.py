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

from app.agents.codegen import CodegenAgent, CodegenOutput
from app.services.codegen import verify_path_safety, validate_python_syntax, write_generated_files, rollback_writes
from app.workflow.engine import run_workflow, sse_manager
from app.core.database import AsyncSessionLocal, init_db
from app.models.run import AgentRun, AgentStep, Approval
from app.models.project import Project, Decision
from app.models.artifact import ProjectArtifact
from app.models.user import User

from fastapi.testclient import TestClient
from app.main import app
from tests.mock_responses import code_review_response

class MockCodegenLLMProvider:
    async def generate(self, system_prompt: str, user_prompt: str, response_schema=None) -> str:
        if response_schema and getattr(response_schema, "__name__", "") == "CodeReviewOutput":
            return code_review_response()
        if "Automated Code Reviewer" in system_prompt or "CodeReviewer" in system_prompt:
            return code_review_response()
        return (
            '{"implementation_plan": "### Plan", '
            '"files": [{"path": "backend/app/api/v1/mock_billing.py", "content": "class MockBilling:\\n    pass\\n", "type": "code"}], '
            '"confidence": 0.99}'
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

def test_path_safety_check():
    # Strict workspace prefix check
    verify_path_safety("backend/app/api/v1/billing.py")
    verify_path_safety("frontend/src/App.tsx")
    
    # Path traversal should raise PermissionError
    with pytest.raises(PermissionError):
        verify_path_safety("../outside_workspace.txt")
        
    with pytest.raises(PermissionError):
        verify_path_safety("C:/Windows/System32/cmd.exe")

def test_syntax_validation():
    # Valid Python code
    validate_python_syntax("def hello():\n    print('world')\n")
    validate_python_syntax("class Test:\n    pass\n")
    
    # Invalid syntax throws SyntaxError
    with pytest.raises(SyntaxError):
        validate_python_syntax("def hello(:\n    print('world')\n")

def test_filesystem_writes_and_rollback():
    # Verify that a write works and backups are created, and rollback reverts cleanly
    run_id = "test-run-safety-1"
    rel_path = "backend/app/api/v1/mock_temp_test.py"
    
    # Dynamic workspace root
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    WORKSPACE_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
    abs_path = os.path.join(WORKSPACE_ROOT, rel_path)
    
    # Cleanup previous leftovers if any
    if os.path.exists(abs_path):
        os.remove(abs_path)
        
    files_list = [{"path": rel_path, "content": "class Temp:\n    pass\n"}]
    
    # 1. Write the new file
    written_paths, created_paths = write_generated_files(run_id, files_list)
    assert len(created_paths) == 1
    assert created_paths[0] == os.path.abspath(abs_path)
    assert os.path.exists(abs_path)
    
    # 2. Rollback the write (deletes the newly created file)
    rollback_writes(run_id, written_paths, created_paths)
    assert not os.path.exists(abs_path)

@pytest.mark.asyncio
async def test_codegen_approval_gates_and_rejections(test_client, auth_headers):
    mock_provider = MockCodegenLLMProvider()
    with patch("app.llm.factory.LLMFactory.get_provider", return_value=mock_provider):
        async with AsyncSessionLocal() as db:
            run = AgentRun(
                project_id="test-project-id",
                initial_prompt="Codegen gate prompt",
                status="PENDING",
                review_cycle_number=1
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            run_id = run.id

        # Insert required previous artifacts for Codegen stage
        async with AsyncSessionLocal() as db:
            prd_art = ProjectArtifact(
                project_id="test-project-id", run_id=run_id, artifact_type="REQUIREMENTS",
                title="PRD", content="PRD content", version=1
            )
            arch_art = ProjectArtifact(
                project_id="test-project-id", run_id=run_id, artifact_type="ARCHITECTURE",
                title="Architecture", content="Arch content", version=1
            )
            db_art = ProjectArtifact(
                project_id="test-project-id", run_id=run_id, artifact_type="DATABASE",
                title="Database", content="Database content", version=1
            )
            api_art = ProjectArtifact(
                project_id="test-project-id", run_id=run_id, artifact_type="API",
                title="API", content="API content", version=1
            )
            backlog_art = ProjectArtifact(
                project_id="test-project-id", run_id=run_id, artifact_type="BACKLOG",
                title="Backlog", content='{"epic_title":"Epic"}', version=1
            )
            db.add(prd_art)
            db.add(arch_art)
            db.add(db_art)
            db.add(api_art)
            db.add(backlog_art)
            await db.commit()

        # Run CodeGenerator stage with approvals on
        await run_workflow("test-project-id", run_id, "Codegen gate prompt", start_stage="CodeGenerator", approvals_enabled=True)

        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "CodeReviewer"
            
            # Check for generated files in the DB (type = GENERATED_FILE)
            art_res = await db.execute(
                select(ProjectArtifact).where(ProjectArtifact.run_id == run_id, ProjectArtifact.artifact_type == "GENERATED_FILE")
            )
            g_files = art_res.scalars().all()
            assert len(g_files) == 1
            assert g_files[0].title == "backend/app/api/v1/mock_billing.py"

        # Reject the CodeReviewer stage -> Reverts to CodeGenerator stage
        resp = test_client.post(
            f"/api/v1/runs/{run_id}/reject",
            json={"stage": "CodeReviewer", "approved_by": "test_pm"},
            headers=auth_headers
        )
        assert resp.status_code == 200
        
        async with AsyncSessionLocal() as db:
            db_run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalars().first()
            assert db_run.status == "WAITING_APPROVAL"
            assert db_run.current_stage == "CodeGenerator"
            
            codegen_app = (await db.execute(select(Approval).where(Approval.run_id == run_id, Approval.stage == "CodeGenerator"))).scalars().first()
            assert codegen_app.status == "PENDING"
