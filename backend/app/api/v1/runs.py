import asyncio
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from datetime import datetime
from app.core.database import get_db, AsyncSessionLocal
from app.models.project import Project, Decision
from app.models.run import AgentRun, AgentStep, Approval
from app.models.artifact import ProjectArtifact
from app.schemas.run import RunTrigger, RunResponse, RunDetailResponse, ApprovalRequest, ApprovalResponse
from app.api.deps import get_current_user
from app.models.user import User
from app.workflow.engine import run_workflow, sse_manager

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/projects/{project_id}/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def trigger_run(
    project_id: str,
    payload: RunTrigger,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.creator_id == current_user.id)
    )
    project = result.scalars().first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
        
    # Check if there is already a running run
    active_result = await db.execute(
        select(AgentRun).where(AgentRun.project_id == project_id, AgentRun.status == "RUNNING")
    )
    if active_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is already a running agent workflow on this project."
        )
        
    run = AgentRun(
        project_id=project_id,
        initial_prompt=payload.initial_prompt,
        status="PENDING"
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    
    # Trigger background execution of PM + Architect workflow
    background_tasks.add_task(
        run_workflow,
        project_id=project_id,
        run_id=run.id,
        initial_prompt=payload.initial_prompt,
        start_stage="PM",
        approvals_enabled=True
    )
    
    return run

@router.get("/projects/{project_id}/runs", response_model=List[RunResponse])
async def list_runs(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify project ownership
    project_res = await db.execute(
        select(Project).where(Project.id == project_id, Project.creator_id == current_user.id)
    )
    if not project_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
        
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.project_id == project_id)
        .order_by(AgentRun.created_at.desc())
    )
    return result.scalars().all()

@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run_details(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Retrieve run with joined relations
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .options(
            selectinload(AgentRun.steps),
            selectinload(AgentRun.artifacts),
            selectinload(AgentRun.decisions),
            selectinload(AgentRun.approvals)
        )
    )
    run = result.scalars().first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent run not found"
        )
        
    # Verify project ownership
    project_res = await db.execute(
        select(Project).where(Project.id == run.project_id, Project.creator_id == current_user.id)
    )
    if not project_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this run's data"
        )
        
    # Ensure items are sorted properly
    run.steps = sorted(run.steps, key=lambda s: s.sequence_number)
    return run

@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: str,
    # Auth is typically done via query params for EventSource, but for simple local V1
    # we can bypass security check on the SSE stream itself to keep it easy to test,
    # or implement token verification. Let's make it open to avoid SSE browser CORS/header headaches.
):
    async def event_generator():
        # Yield past steps first so the client catches up immediately
        async with AsyncSessionLocal() as db:
            past_steps_res = await db.execute(
                select(AgentStep)
                .where(AgentStep.run_id == run_id)
                .order_by(AgentStep.sequence_number.asc())
            )
            past_steps = past_steps_res.scalars().all()
            for step in past_steps:
                data = {
                    "id": step.id,
                    "run_id": step.run_id,
                    "agent_name": step.agent_name,
                    "step_type": step.step_type,
                    "content": step.content,
                    "sequence_number": step.sequence_number,
                    "created_at": step.created_at.isoformat()
                }
                yield f"data: {import_json_dumps(data)}\n\n"
                
        # Subscribe to new live events
        queue = sse_manager.subscribe(run_id)
        try:
            while True:
                # Wait for new data from queue
                data = await queue.get()
                yield f"data: {import_json_dumps(data)}\n\n"
                
                # Check for termination status
                if data.get("status") in ["COMPLETED", "FAILED"]:
                    break
        except asyncio.CancelledError:
            logger.info(f"SSE connection closed for run {run_id}")
        finally:
            sse_manager.unsubscribe(run_id, queue)
            
    def import_json_dumps(data):
        import json
        return json.dumps(data)
        
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Encoding": "none",
        }
    )

@router.post("/runs/{run_id}/approve", response_model=ApprovalResponse)
async def approve_run_stage(
    run_id: str,
    payload: ApprovalRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 1. Retrieve run
    run_res = await db.execute(
        select(AgentRun).where(AgentRun.id == run_id)
    )
    run = run_res.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
        
    # 2. Verify project ownership
    proj_res = await db.execute(
        select(Project).where(Project.id == run.project_id, Project.creator_id == current_user.id)
    )
    if not proj_res.scalars().first():
        raise HTTPException(status_code=403, detail="Access denied to this run")
        
    # 3. Validation
    if payload.stage not in ["PM", "Architect", "Reviewer", "Planner", "CodeGenerator", "CodeReviewer"]:
        raise HTTPException(status_code=400, detail="Invalid approval stage name")
    if run.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=400, detail="Run is not waiting for approval")
    if run.current_stage != payload.stage:
        raise HTTPException(status_code=400, detail=f"Cannot approve stage {payload.stage}. Current stage is {run.current_stage}")
        
    # 4. Find pending approval record
    app_res = await db.execute(
        select(Approval)
        .where(Approval.run_id == run_id, Approval.stage == payload.stage, Approval.status == "PENDING")
        .order_by(Approval.created_at.desc())
    )
    approval = app_res.scalars().first()
    if not approval:
        approval = Approval(run_id=run_id, stage=payload.stage, review_cycle_number=run.review_cycle_number or 1)
        db.add(approval)
        
    # Read the agent decision from approval comments before overwriting them
    agent_decision_approved = True
    if payload.stage == "Reviewer" and approval and approval.comments == "AGENT_REJECTED":
        agent_decision_approved = False
        
    # 5. Update approval record
    approval.status = "APPROVED"
    approval.approved_by = payload.approved_by or current_user.email
    approval.approved_at = datetime.now()
    approval.comments = payload.comments
    approval.rationale = payload.rationale
    db.add(approval)
    
    # 6. Update run & trigger next workflow stage
    if payload.stage == "PM":
        run.status = "RUNNING"
        run.current_stage = "Architect"
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "APPROVED", "stage": "PM"})
        await sse_manager.publish(run_id, {"status": "WORKFLOW_RESUMED", "stage": "Architect"})
        
        background_tasks.add_task(
            run_workflow,
            project_id=run.project_id,
            run_id=run.id,
            initial_prompt=run.initial_prompt,
            start_stage="Architect",
            approvals_enabled=True
        )
    elif payload.stage == "Architect":
        run.status = "RUNNING"
        run.current_stage = "Reviewer"
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "APPROVED", "stage": "Architect", "cycle": run.review_cycle_number})
        await sse_manager.publish(run_id, {"status": "WORKFLOW_RESUMED", "stage": "Reviewer", "cycle": run.review_cycle_number})
        
        background_tasks.add_task(
            run_workflow,
            project_id=run.project_id,
            run_id=run.id,
            initial_prompt=run.initial_prompt,
            start_stage="Reviewer",
            approvals_enabled=True
        )
    elif payload.stage == "Reviewer":
        review_cycle = run.review_cycle_number or 1
        MAX_REVIEW_CYCLES = 3
        
        if agent_decision_approved or review_cycle >= MAX_REVIEW_CYCLES:
            run.status = "RUNNING"
            run.current_stage = "Planner"
            db.add(run)
            await db.commit()
            await db.refresh(run)
            await sse_manager.publish(run_id, {"status": "APPROVED", "stage": "Reviewer", "cycle": review_cycle})
            await sse_manager.publish(run_id, {"status": "WORKFLOW_RESUMED", "stage": "Planner"})
            
            background_tasks.add_task(
                run_workflow,
                project_id=run.project_id,
                run_id=run.id,
                initial_prompt=run.initial_prompt,
                start_stage="Planner",
                approvals_enabled=True
            )
        else:
            # Re-route to Architect Revision
            run.status = "RUNNING"
            run.current_stage = "Architect"
            run.review_cycle_number = review_cycle + 1
            db.add(run)
            
            # Create pending approval for next cycle's Architect stage
            new_arch_pending = Approval(
                run_id=run_id,
                stage="Architect",
                status="PENDING",
                review_cycle_number=review_cycle + 1
            )
            db.add(new_arch_pending)
            await db.commit()
            await db.refresh(run)
            
            await sse_manager.publish(run_id, {"status": "APPROVED", "stage": "Reviewer", "cycle": review_cycle})
            await sse_manager.publish(run_id, {"status": "WORKFLOW_RESUMED", "stage": "Architect", "cycle": review_cycle + 1})
            
            background_tasks.add_task(
                run_workflow,
                project_id=run.project_id,
                run_id=run.id,
                initial_prompt=run.initial_prompt,
                start_stage="Architect",
                approvals_enabled=True
            )
    elif payload.stage == "Planner":
        run.status = "RUNNING"
        run.current_stage = "CodeGenerator"
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "APPROVED", "stage": "Planner"})
        await sse_manager.publish(run_id, {"status": "WORKFLOW_RESUMED", "stage": "CodeGenerator"})
        
        background_tasks.add_task(
            run_workflow,
            project_id=run.project_id,
            run_id=run.id,
            initial_prompt=run.initial_prompt,
            start_stage="CodeGenerator",
            approvals_enabled=True
        )
    elif payload.stage in ("CodeGenerator", "CodeReviewer"):
        # 1. Fetch generated file artifacts for current run
        art_res = await db.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.run_id == run_id,
                ProjectArtifact.artifact_type == "GENERATED_FILE"
            )
        )
        gen_files = art_res.scalars().all()
        files_to_write = [{"path": g.title, "content": g.content} for g in gen_files]

        # 2. Run Safety Disk Writer (creates backups, checks traversal, verifies syntax, rolls back on exception)
        try:
            from app.services.codegen import write_generated_files
            write_generated_files(run_id, files_to_write)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Safety Disk Writer execution failed: {str(e)}"
            )

        # 2.5 Re-index repository codebase
        try:
            from app.services.repo_intel import RepoIndexer
            await RepoIndexer.index_all(db)
        except Exception as e:
            # Import logger if needed or log as warning
            import logging
            logging.getLogger(__name__).warning(f"Re-indexing failed after approval write: {e}")

        # 3. Transition to completed
        run.status = "COMPLETED"
        run.completed_at = datetime.now()
        db.add(run)
        await db.commit()
        await db.refresh(run)
        
        await sse_manager.publish(run_id, {"status": "APPROVED", "stage": "CodeGenerator"})
        await sse_manager.publish(run_id, {"status": "COMPLETED"})
        
    return approval

@router.post("/runs/{run_id}/reject", response_model=ApprovalResponse)
async def reject_run_stage(
    run_id: str,
    payload: ApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 1. Retrieve run
    run_res = await db.execute(
        select(AgentRun).where(AgentRun.id == run_id)
    )
    run = run_res.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
        
    # 2. Verify project ownership
    proj_res = await db.execute(
        select(Project).where(Project.id == run.project_id, Project.creator_id == current_user.id)
    )
    if not proj_res.scalars().first():
        raise HTTPException(status_code=403, detail="Access denied to this run")
        
    # 3. Validation
    if payload.stage not in ["PM", "Architect", "Reviewer", "Planner", "CodeGenerator", "CodeReviewer"]:
        raise HTTPException(status_code=400, detail="Invalid rejection stage name")
    if run.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=400, detail="Run is not waiting for approval")
    if run.current_stage != payload.stage:
        raise HTTPException(status_code=400, detail=f"Cannot reject stage {payload.stage}. Current stage is {run.current_stage}")
        
    # 4. Find pending approval record
    app_res = await db.execute(
        select(Approval)
        .where(Approval.run_id == run_id, Approval.stage == payload.stage, Approval.status == "PENDING")
        .order_by(Approval.created_at.desc())
    )
    approval = app_res.scalars().first()
    if not approval:
        approval = Approval(run_id=run_id, stage=payload.stage, review_cycle_number=run.review_cycle_number or 1)
        db.add(approval)
        
    # 5. Update approval record to REJECTED
    approval.status = "REJECTED"
    approval.approved_by = payload.approved_by or current_user.email
    approval.approved_at = datetime.now()
    approval.comments = payload.comments
    approval.rationale = payload.rationale
    db.add(approval)
    
    # 6. Update run to return to previous stage
    if payload.stage == "PM":
        run.status = "PENDING"
        run.current_stage = None
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "REJECTED", "stage": "PM"})
    elif payload.stage == "Architect":
        run.status = "WAITING_APPROVAL"
        run.current_stage = "PM"
        
        # Insert a new PENDING approval record for PM
        new_pm_pending = Approval(
            run_id=run_id,
            stage="PM",
            status="PENDING",
            review_cycle_number=1
        )
        db.add(new_pm_pending)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "REJECTED", "stage": "Architect", "cycle": run.review_cycle_number})
        await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "PM"})
        await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "PM"})
    elif payload.stage == "Reviewer":
        run.status = "WAITING_APPROVAL"
        run.current_stage = "Architect"
        
        # Insert a new PENDING approval record for Architect in current cycle
        new_arch_pending = Approval(
            run_id=run_id,
            stage="Architect",
            status="PENDING",
            review_cycle_number=run.review_cycle_number or 1
        )
        db.add(new_arch_pending)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "REJECTED", "stage": "Reviewer", "cycle": run.review_cycle_number})
        await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "Architect", "cycle": run.review_cycle_number})
        await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "Architect", "cycle": run.review_cycle_number})
    elif payload.stage == "Planner":
        run.status = "WAITING_APPROVAL"
        run.current_stage = "Reviewer"
        
        # Insert a new PENDING approval record for Reviewer
        new_rev_pending = Approval(
            run_id=run_id,
            stage="Reviewer",
            status="PENDING",
            review_cycle_number=run.review_cycle_number or 1
        )
        db.add(new_rev_pending)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "REJECTED", "stage": "Planner"})
        await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "Reviewer"})
        await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "Reviewer"})
    elif payload.stage == "CodeGenerator":
        run.status = "WAITING_APPROVAL"
        run.current_stage = "Planner"
        
        # Insert a new PENDING approval record for Planner
        new_plan_pending = Approval(
            run_id=run_id,
            stage="Planner",
            status="PENDING",
            review_cycle_number=1
        )
        db.add(new_plan_pending)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "REJECTED", "stage": "CodeGenerator"})
        await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "Planner"})
        await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "Planner"})
    elif payload.stage == "CodeReviewer":
        run.status = "WAITING_APPROVAL"
        run.current_stage = "CodeGenerator"
        
        # Insert a new PENDING approval record for CodeGenerator
        new_gen_pending = Approval(
            run_id=run_id,
            stage="CodeGenerator",
            status="PENDING",
            review_cycle_number=1
        )
        db.add(new_gen_pending)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        await sse_manager.publish(run_id, {"status": "REJECTED", "stage": "CodeReviewer"})
        await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "CodeGenerator"})
        await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "CodeGenerator"})
        
    return approval

