from pydantic import BaseModel
from typing import List, Optional

class SubTask(BaseModel):
    id: str
    title: str
    description: str
    complexity: str
    priority: str
    estimate: str
    dependencies: List[str] = []
    acceptance_criteria: List[str] = []

class Task(BaseModel):
    id: str
    title: str
    description: str
    complexity: str
    priority: str
    estimate: str
    dependencies: List[str] = []
    acceptance_criteria: List[str] = []
    subtasks: List[SubTask] = []

class PlannerOutput(BaseModel):
    epic_title: str
    epic_description: str
    tasks: List[Task]
    confidence: float
