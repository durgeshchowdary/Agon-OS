import os
import ast
import hashlib
from datetime import datetime
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.repo_intel import RepoFile, RepoClass, RepoFunction, RepoRoute
from app.core.database import AsyncSessionLocal

# Resolve workspace root (3 levels up from backend/app/services)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".."))

def calculate_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def get_ast_signature(node: ast.FunctionDef) -> str:
    # Compile a simple string representation of arguments
    args = []
    for arg in node.args.args:
        ann = ""
        if arg.annotation:
            ann = f": {ast.unparse(arg.annotation)}"
        args.append(f"{arg.arg}{ann}")
    ret = ""
    if node.returns:
        ret = f" -> {ast.unparse(node.returns)}"
    return f"def {node.name}({', '.join(args)}){ret}"

class RepoIndexer:
    @staticmethod
    async def index_file(db: AsyncSession, rel_path: str):
        abs_path = os.path.join(WORKSPACE_ROOT, rel_path)
        if not os.path.exists(abs_path):
            return
            
        file_hash = calculate_sha256(abs_path)
        
        # Check if already indexed and unchanged
        res = await db.execute(select(RepoFile).where(RepoFile.path == rel_path))
        existing_file = res.scalars().first()
        if existing_file and existing_file.sha256_hash == file_hash:
            return # Skip indexing as file content is identical
            
        # Parse AST
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content)
        except Exception:
            return # Ignore files with invalid syntax to prevent workflow blocks
            
        # Clean previous indexes for this file
        await db.execute(delete(RepoClass).where(RepoClass.file_path == rel_path))
        await db.execute(delete(RepoFunction).where(RepoFunction.file_path == rel_path))
        await db.execute(delete(RepoRoute).where(RepoRoute.file_path == rel_path))
        
        # Traverse AST and extract elements
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases_list = [ast.unparse(b) for b in node.bases]
                bases_str = ",".join(bases_list) if bases_list else None
                doc = ast.get_docstring(node)
                
                db_class = RepoClass(
                    class_name=node.name,
                    file_path=rel_path,
                    bases=bases_str,
                    docstring=doc,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno)
                )
                db.add(db_class)
                
            elif isinstance(node, ast.FunctionDef):
                # Check parent class if nested
                parent_class = None
                # Basic search for class nesting
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        if node in parent.body:
                            parent_class = parent.name
                            break
                            
                sig = get_ast_signature(node)
                doc = ast.get_docstring(node)
                
                db_func = RepoFunction(
                    function_name=node.name,
                    class_name=parent_class,
                    file_path=rel_path,
                    signature=sig,
                    docstring=doc,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno)
                )
                db.add(db_func)
                
                # Check for FastAPI route decorators
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                        attr = decorator.func.attr
                        if attr in ["get", "post", "put", "delete", "patch", "options", "head"]:
                            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                                path = decorator.args[0].value
                                db_route = RepoRoute(
                                    http_method=attr.upper(),
                                    route_path=str(path),
                                    handler=node.name,
                                    file_path=rel_path
                                )
                                db.add(db_route)
                                
        # Update or create RepoFile record
        if existing_file:
            existing_file.sha256_hash = file_hash
            existing_file.last_indexed_at = datetime.now()
            db.add(existing_file)
        else:
            new_file = RepoFile(path=rel_path, sha256_hash=file_hash)
            db.add(new_file)
            
        await db.commit()

    @staticmethod
    async def index_all(db: AsyncSession):
        # Scan entire backend workspace
        exclude_dirs = {".git", ".pytest_cache", ".agon_backups", "__pycache__", "venv", "node_modules"}
        
        for root, dirs, files in os.walk(WORKSPACE_ROOT):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith(".py"):
                    abs_p = os.path.join(root, file)
                    rel_p = os.path.relpath(abs_p, WORKSPACE_ROOT).replace("\\", "/")
                    await RepoIndexer.index_file(db, rel_p)

def string_similarity(s1: str, s2: str) -> float:
    s1, s2 = s1.lower(), s2.lower()
    if s1 == s2:
        return 1.0
    parts1 = set(s1.split("_"))
    parts2 = set(s2.split("_"))
    common = parts1 & parts2
    if not common:
        return 0.0
    return len(common) / max(len(parts1), len(parts2))

class RepoIntelService:
    @staticmethod
    async def search(db: AsyncSession, query: str):
        # Query class name, function name, or route matches
        classes_res = await db.execute(select(RepoClass).where(RepoClass.class_name.like(f"%{query}%")))
        classes = classes_res.scalars().all()
        
        funcs_res = await db.execute(select(RepoFunction).where(RepoFunction.function_name.like(f"%{query}%")))
        funcs = funcs_res.scalars().all()
        
        routes_res = await db.execute(select(RepoRoute).where(RepoRoute.route_path.like(f"%{query}%") | RepoRoute.handler.like(f"%{query}%")))
        routes = routes_res.scalars().all()
        
        return classes, funcs, routes

    @staticmethod
    async def check_duplicates(db: AsyncSession, new_func_name: str) -> list:
        # Checks classes and functions for duplicate names or high similarity
        funcs_res = await db.execute(select(RepoFunction))
        all_funcs = funcs_res.scalars().all()
        
        duplicates = []
        for f in all_funcs:
            # Skip constructor
            if f.function_name == "__init__":
                continue
            if f.function_name == new_func_name:
                duplicates.append({
                    "type": "exact_name",
                    "file_path": f.file_path,
                    "name": f.function_name,
                    "class": f.class_name,
                    "signature": f.signature
                })
            else:
                sim = string_similarity(f.function_name, new_func_name)
                if sim >= 0.6:
                    duplicates.append({
                        "type": "similar_name",
                        "file_path": f.file_path,
                        "name": f.function_name,
                        "class": f.class_name,
                        "similarity": sim,
                        "signature": f.signature
                    })
        return duplicates
