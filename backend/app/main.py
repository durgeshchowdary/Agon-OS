import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import init_db
from app.api.v1 import auth, projects, runs, repo_intel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set CORS origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for V1 development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully.")
    
    logger.info("Running Repository Intelligence codebase indexing sweep...")
    from app.services.repo_intel import RepoIndexer
    from app.core.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            await RepoIndexer.index_all(db)
        logger.info("Repository Intelligence indexing complete.")
    except Exception as e:
        logger.error("Repository Intelligence indexing failed during startup: %s", str(e))

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}

# Include routers
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(projects.router, prefix=f"{settings.API_V1_STR}/projects", tags=["Projects"])
# Incorporate runs routing
app.include_router(runs.router, prefix=settings.API_V1_STR, tags=["Agent Runs"])
app.include_router(repo_intel.router, prefix=settings.API_V1_STR, tags=["Repository Intelligence"])
