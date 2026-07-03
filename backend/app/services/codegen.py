import os
import ast
import logging
import shutil
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

# Determine the absolute workspace root dynamically
# The file is at: backend/app/services/codegen.py
# Parent directories: backend/app/services -> backend/app -> backend -> workspace_root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".."))
BACKUPS_DIR = os.path.join(WORKSPACE_ROOT, "backend", ".agon_backups")

def validate_python_syntax(content: str, filename: str = "<generated>") -> bool:
    """
    Parses the Python code content using AST to verify syntax correctness.
    Raises SyntaxError if the content is not valid Python.
    """
    try:
        ast.parse(content, filename=filename)
        return True
    except SyntaxError as e:
        logger.error(f"Python syntax validation failed for {filename}: {e}")
        raise e

def verify_path_safety(relative_path: str, workspace_root: str = WORKSPACE_ROOT) -> str:
    """
    Validates that the target relative path resolves strictly inside the workspace root
    to prevent path traversal attacks. Returns the normalized absolute path.
    """
    # Clean up relative path formatting (e.g. leading slashes/backslashes)
    clean_rel_path = relative_path.lstrip("/\\")
    abs_workspace = os.path.abspath(workspace_root)
    abs_target = os.path.abspath(os.path.join(workspace_root, clean_rel_path))

    # Verify that abs_workspace is a common prefix of abs_target
    common = os.path.commonpath([abs_workspace, abs_target])
    if os.path.abspath(common) != abs_workspace:
        raise PermissionError(f"Path traversal detected! Path '{relative_path}' is outside workspace '{workspace_root}'.")

    return abs_target

def write_generated_files(run_id: str, files: List[Dict]) -> Tuple[List[str], List[str]]:
    """
    Writes a list of files to the local filesystem.
    Before overwriting existing files, copies them to a backup folder.
    Returns:
        tuple (written_abs_paths, newly_created_abs_paths)
    """
    run_backup_dir = os.path.join(BACKUPS_DIR, run_id)
    os.makedirs(run_backup_dir, exist_ok=True)

    written_paths = []
    created_paths = []
    
    try:
        for f in files:
            rel_path = f.get("path")
            content = f.get("content", "")
            
            # 1. Path Safety Check
            abs_path = verify_path_safety(rel_path)
            
            # 2. Syntax Validation (Python only)
            if rel_path.endswith(".py"):
                validate_python_syntax(content, filename=rel_path)
                
            # 3. Handle Backups if exists
            if os.path.exists(abs_path):
                # Target path in backups
                rel_clean = rel_path.lstrip("/\\")
                backup_file_path = os.path.join(run_backup_dir, rel_clean)
                os.makedirs(os.path.dirname(backup_file_path), exist_ok=True)
                shutil.copy2(abs_path, backup_file_path)
                logger.info(f"Backed up existing file '{rel_path}' to '{backup_file_path}'")
                written_paths.append(abs_path)
            else:
                created_paths.append(abs_path)
                
            # 4. Write new content
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as file_out:
                file_out.write(content)
            logger.info(f"Successfully wrote generated file: '{rel_path}'")

        return written_paths, created_paths

    except Exception as e:
        logger.error(f"Error during file write phase: {e}. Executing immediate rollback...")
        # Rollback using whatever files were successfully processed
        rollback_writes(run_id, written_paths, created_paths)
        raise e

def rollback_writes(run_id: str, written_paths: List[str], created_paths: List[str]):
    """
    Rolls back filesystem changes:
    - Deletes files that were newly created.
    - Restores files that were overwritten from the backup directory.
    """
    run_backup_dir = os.path.join(BACKUPS_DIR, run_id)
    logger.info(f"Rolling back filesystem changes for run {run_id}...")

    # 1. Delete newly created files
    for path in created_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Rollback: Deleted newly created file '{path}'")
        except Exception as e:
            logger.error(f"Rollback failed to delete file '{path}': {e}")

    # 2. Restore modified files from backups
    for path in written_paths:
        # Re-derive relative path of the file to locate backup
        abs_workspace = os.path.abspath(WORKSPACE_ROOT)
        rel_path = os.path.relpath(path, abs_workspace)
        backup_file_path = os.path.join(run_backup_dir, rel_path)
        
        try:
            if os.path.exists(backup_file_path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                shutil.copy2(backup_file_path, path)
                logger.info(f"Rollback: Restored file '{path}' from backup")
            else:
                logger.warning(f"Rollback: Backup file for '{path}' not found at '{backup_file_path}'")
        except Exception as e:
            logger.error(f"Rollback failed to restore file '{path}': {e}")

    # 3. Clean up the backup directory
    try:
        if os.path.exists(run_backup_dir):
            shutil.rmtree(run_backup_dir)
            logger.info(f"Rollback: Cleaned backup directory '{run_backup_dir}'")
    except Exception as e:
        logger.error(f"Rollback failed to delete backup dir '{run_backup_dir}': {e}")
