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
from app.models.repo_intel import RepoFile, RepoClass, RepoFunction, RepoRoute
from app.models.user import User
from app.services.repo_intel import RepoIndexer, RepoIntelService
from app.main import app

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
        await db.execute(delete(RepoRoute))
        await db.execute(delete(RepoFunction))
        await db.execute(delete(RepoClass))
        await db.execute(delete(RepoFile))
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
async def test_ast_parsing_and_indexing():
    # Setup temporary file inside workspace root for testing the indexing process
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    WORKSPACE_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
    
    temp_filename = "backend/mock_api_index_test_file.py"
    temp_path = os.path.join(WORKSPACE_ROOT, temp_filename)
    
    code = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "class MockService:\n"
        "    \"\"\"Service mock class\"\"\"\n"
        "    def execute_payment(self, amount: float) -> bool:\n"
        "        return True\n\n"
        "@router.post('/api/v1/payments')\n"
        "def process_transaction(data: dict):\n"
        "    \"\"\"Process api request\"\"\"\n"
        "    return {'status': 'processed'}\n"
    )
    
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(code)
        
    try:
        async with AsyncSessionLocal() as db:
            # 1. Run indexer on the newly created temporary file
            await RepoIndexer.index_file(db, temp_filename)
            
            # 2. Verify File indexed
            file_res = await db.execute(select(RepoFile).where(RepoFile.path == temp_filename))
            db_file = file_res.scalars().first()
            assert db_file is not None
            assert db_file.sha256_hash is not None
            
            # 3. Verify Class indexed
            class_res = await db.execute(select(RepoClass).where(RepoClass.class_name == "MockService"))
            db_class = class_res.scalars().first()
            assert db_class is not None
            assert db_class.docstring == "Service mock class"
            
            # 4. Verify Function indexed
            func_res = await db.execute(select(RepoFunction).where(RepoFunction.function_name == "execute_payment"))
            db_func = func_res.scalars().first()
            assert db_func is not None
            assert db_func.class_name == "MockService"
            assert "def execute_payment(self, amount: float)" in db_func.signature
            
            # 5. Verify Route indexed
            route_res = await db.execute(select(RepoRoute).where(RepoRoute.handler == "process_transaction"))
            db_route = route_res.scalars().first()
            assert db_route is not None
            assert db_route.http_method == "POST"
            assert db_route.route_path == "/api/v1/payments"
            
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@pytest.mark.asyncio
async def test_duplicate_checks_and_similarities():
    async with AsyncSessionLocal() as db:
        # Pre-seed index tables with existing functions to verify matches
        f1 = RepoFunction(
            function_name="create_agent_run",
            class_name=None,
            file_path="backend/app/services/codegen.py",
            signature="def create_agent_run(db, run_id)",
            docstring="Core utility"
        )
        db.add(f1)
        await db.commit()
        
        # 1. Exact match duplicate checking
        dups_exact = await RepoIntelService.check_duplicates(db, "create_agent_run")
        assert len(dups_exact) == 1
        assert dups_exact[0]["type"] == "exact_name"
        assert dups_exact[0]["file_path"] == "backend/app/services/codegen.py"
        
        # 2. Similarity index matching
        dups_sim = await RepoIntelService.check_duplicates(db, "make_agent_run")
        assert len(dups_sim) == 1
        assert dups_sim[0]["type"] == "similar_name"
        assert dups_sim[0]["similarity"] >= 0.6

@pytest.mark.asyncio
async def test_search_repo_intel_endpoint(test_client, auth_headers):
    async with AsyncSessionLocal() as db:
        # Pre-seed class index to query via endpoint
        db_class = RepoClass(
            class_name="UserBillingManager",
            file_path="backend/app/services/billing.py",
            bases="BaseService",
            docstring="Billing operations"
        )
        db.add(db_class)
        await db.commit()
        
    resp = test_client.get(
        "/api/v1/repo-intel/search?query=Billing",
        headers=auth_headers
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert len(res_data["classes"]) == 1
    assert res_data["classes"][0]["class_name"] == "UserBillingManager"
    assert res_data["classes"][0]["file_path"] == "backend/app/services/billing.py"
