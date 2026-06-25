from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.models.project import Project, Decision
from app.models.artifact import ProjectArtifact
from app.schemas.project import ProjectCreate, ProjectResponse, ArtifactResponse, DecisionResponse
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()

@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    project = Project(
        creator_id=current_user.id,
        name=project_in.name,
        description=project_in.description,
        domain=project_in.domain
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project

@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Project).where(Project.creator_id == current_user.id)
    )
    return result.scalars().all()

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.creator_id == current_user.id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    return project

@router.get("/{project_id}/artifacts", response_model=List[ArtifactResponse])
async def list_project_artifacts(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership first
    project_res = await db.execute(
        select(Project).where(Project.id == project_id, Project.creator_id == current_user.id)
    )
    if not project_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
        
    # Get all artifacts, ordered by version descending so we can filter down to latest
    # Or just return all versions and let the client process. Let's return all.
    result = await db.execute(
        select(ProjectArtifact)
        .where(ProjectArtifact.project_id == project_id)
        .order_by(ProjectArtifact.artifact_type, ProjectArtifact.version.desc())
    )
    return result.scalars().all()

@router.get("/{project_id}/decisions", response_model=List[DecisionResponse])
async def list_project_decisions(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership first
    project_res = await db.execute(
        select(Project).where(Project.id == project_id, Project.creator_id == current_user.id)
    )
    if not project_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
        
    result = await db.execute(
        select(Decision)
        .where(Decision.project_id == project_id)
        .order_by(Decision.created_at.desc())
    )
    return result.scalars().all()
