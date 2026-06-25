from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    domain: str = "software_engineering"

class ProjectResponse(BaseModel):
    id: str
    creator_id: str
    name: str
    description: Optional[str] = None
    domain: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DecisionResponse(BaseModel):
    id: str
    project_id: str
    run_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    options: Optional[Any] = None
    selected_option: Optional[str] = None
    rationale: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ArtifactResponse(BaseModel):
    id: str
    project_id: str
    run_id: Optional[str] = None
    artifact_type: str
    title: str
    content: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
