from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.core.database import get_db
from app.schemas.repo_intel import RepoSearchResponse, ClassSchema, FunctionSchema, RouteSchema
from app.services.repo_intel import RepoIntelService, RepoIndexer

router = APIRouter(prefix="/repo-intel", tags=["repo-intel"])

@router.get("/search", response_model=RepoSearchResponse)
async def search_repo_intelligence(
    query: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Search classes, functions, or API routes in the indexed repository.
    """
    if len(query) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query must be at least 2 characters long"
        )
        
    classes, funcs, routes = await RepoIntelService.search(db, query)
    
    return RepoSearchResponse(
        classes=[ClassSchema.model_validate(c) for c in classes],
        functions=[FunctionSchema.model_validate(f) for f in funcs],
        routes=[RouteSchema.model_validate(r) for r in routes]
    )

@router.post("/reindex", status_code=status.HTTP_200_OK)
async def trigger_reindex(
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger static analysis re-indexing of the entire backend codebase.
    """
    try:
        await RepoIndexer.index_all(db)
        return {"status": "SUCCESS", "message": "Codebase successfully indexed"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reindexing failed: {str(e)}"
        )
