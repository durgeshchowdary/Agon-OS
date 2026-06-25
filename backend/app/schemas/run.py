from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from app.schemas.project import ArtifactResponse, DecisionResponse

class RunTrigger(BaseModel):
    initial_prompt: str

class RunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    initial_prompt: str
    current_stage: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class StepResponse(BaseModel):
    id: str
    run_id: str
    agent_name: str
    step_type: str
    content: str
    sequence_number: int
    created_at: datetime

    class Config:
        from_attributes = True

class ApprovalRequest(BaseModel):
    stage: str
    approved_by: Optional[str] = None
    comments: Optional[str] = None
    rationale: Optional[str] = None

class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    stage: str
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    comments: Optional[str] = None
    rationale: Optional[str] = None

    class Config:
        from_attributes = True

class RunDetailResponse(RunResponse):
    steps: List[StepResponse] = []
    artifacts: List[ArtifactResponse] = []
    decisions: List[DecisionResponse] = []
    approvals: List[ApprovalResponse] = []

    class Config:
        from_attributes = True

