from pydantic import BaseModel, ConfigDict
from typing import List, Optional

class ClassSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    class_name: str
    file_path: str
    bases: Optional[str] = None
    docstring: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None

class FunctionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    function_name: str
    class_name: Optional[str] = None
    file_path: str
    signature: Optional[str] = None
    docstring: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None

class RouteSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    http_method: str
    route_path: str
    handler: str
    file_path: str

class RepoSearchResponse(BaseModel):
    classes: List[ClassSchema]
    functions: List[FunctionSchema]
    routes: List[RouteSchema]
