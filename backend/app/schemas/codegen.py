from pydantic import BaseModel
from typing import List

class GeneratedFile(BaseModel):
    path: str
    content: str
    type: str  # code, test, doc, migration

class CodegenOutput(BaseModel):
    implementation_plan: str
    files: List[GeneratedFile]
    confidence: float
