import asyncio
import logging
from datetime import datetime
from typing import Dict, Set

from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.run import AgentRun, AgentStep, Approval
from app.models.artifact import ProjectArtifact
from app.models.project import Decision
from app.agents import PMAgent, ArchitectAgent, CriticAgent

logger = logging.getLogger(__name__)


class SSEManager:
    def __init__(self):
        self.listeners: Dict[str, Set[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        if run_id not in self.listeners:
            self.listeners[run_id] = set()
        queue = asyncio.Queue()
        self.listeners[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue):
        if run_id in self.listeners:
            self.listeners[run_id].discard(queue)
            if not self.listeners[run_id]:
                del self.listeners[run_id]

    async def publish(self, run_id: str, data: dict):
        if run_id in self.listeners:
            for queue in self.listeners[run_id]:
                await queue.put(data)


sse_manager = SSEManager()


async def save_step(run_id: str, agent_name: str, step_type: str, content: str) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run_id)
            .order_by(AgentStep.sequence_number.desc())
        )
        last_step = result.scalars().first()
        seq = (last_step.sequence_number + 1) if last_step else 1

        step = AgentStep(
            run_id=run_id,
            agent_name=agent_name,
            step_type=step_type,
            content=content,
            sequence_number=seq,
        )
        db.add(step)
        await db.commit()
        await db.refresh(step)

        event_data = {
            "id": step.id,
            "run_id": run_id,
            "agent_name": agent_name,
            "step_type": step_type,
            "content": content,
            "sequence_number": seq,
            "created_at": step.created_at.isoformat(),
        }
        await sse_manager.publish(run_id, event_data)
        return seq


async def save_artifact(
    project_id: str,
    run_id: str,
    artifact_type: str,
    title: str,
    content: str,
    status: str = "DRAFT",
    review_cycle_number: int = 1,
):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.project_id == project_id,
                ProjectArtifact.artifact_type == artifact_type,
            )
            .order_by(ProjectArtifact.version.desc())
        )
        last_artifact = result.scalars().first()
        next_ver = (last_artifact.version + 1) if last_artifact else 1

        if last_artifact and last_artifact.content == content:
            last_artifact.run_id = run_id
            last_artifact.status = status
            last_artifact.review_cycle_number = review_cycle_number
            db.add(last_artifact)
            await db.commit()
            return

        artifact = ProjectArtifact(
            project_id=project_id,
            run_id=run_id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            version=next_ver,
            review_cycle_number=review_cycle_number,
            status=status,
        )
        db.add(artifact)
        await db.commit()


async def save_decisions(project_id: str, run_id: str, decisions: list):
    async with AsyncSessionLocal() as db:
        for d in decisions:
            if isinstance(d, str):
                decision = Decision(
                    project_id=project_id,
                    run_id=run_id,
                    title=d[:255],
                    description=d,
                )
            else:
                if hasattr(d, "model_dump"):
                    d_dict = d.model_dump()
                elif hasattr(d, "dict"):
                    d_dict = d.dict()
                elif isinstance(d, dict):
                    d_dict = d
                else:
                    d_dict = getattr(d, "__dict__", {})
                
                title = d_dict.get("title", "")
                description = d_dict.get("description", None) or d_dict.get("recommendation", "")
                options = d_dict.get("options", [])
                selected_option = d_dict.get("selected_option", None) or d_dict.get("severity", "")
                rationale = d_dict.get("rationale", "")
                
                decision = Decision(
                    project_id=project_id,
                    run_id=run_id,
                    title=title[:255],
                    description=description,
                    options=options,
                    selected_option=selected_option,
                    rationale=rationale,
                )
            db.add(decision)
        await db.commit()


async def run_workflow(project_id: str, run_id: str, initial_prompt: str, start_stage: str = "PM", approvals_enabled: bool = False):
    logger.info("Starting workflow run %s (stage: %s, approvals: %s) for project %s", run_id, start_stage, approvals_enabled, project_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalars().first()
        if run:
            run.status = "RUNNING"
            run.current_stage = start_stage
            if start_stage == "PM" and not run.started_at:
                run.started_at = datetime.now()
            db.add(run)
            await db.commit()

    try:
        current_executing_stage = start_stage

        # --- PM STAGE ---
        if current_executing_stage == "PM":
            await sse_manager.publish(run_id, {"status": "PM_STARTED"})
            await sse_manager.publish(run_id, {"status": "PM_THINKING"})
            await save_step(run_id, "PM", "THOUGHT", "Analyzing prompt and generating Product Requirements...")
            await asyncio.sleep(0.8)

            pm = PMAgent()
            pm_output = await pm.run(initial_prompt)
            prd = pm.format_to_markdown(pm_output)
            
            await save_step(run_id, "PM", "ARTIFACT_PROPOSAL", prd)
            await save_artifact(
                project_id, run_id, "REQUIREMENTS", "Product Requirements Document (PRD)", prd, "DRAFT"
            )
            
            await save_decisions(project_id, run_id, pm_output.decisions)
            await sse_manager.publish(run_id, {"status": "PM_COMPLETED"})
            
            if approvals_enabled:
                async with AsyncSessionLocal() as db:
                    run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                    run_obj = run_res.scalars().first()
                    if run_obj:
                        run_obj.status = "WAITING_APPROVAL"
                        run_obj.current_stage = "PM"
                        approval = Approval(run_id=run_id, stage="PM", status="PENDING", review_cycle_number=1)
                        db.add(approval)
                        db.add(run_obj)
                        await db.commit()
                
                await save_step(run_id, "System", "THOUGHT", "Product requirements generated. Waiting for human approval to proceed to System Architecture design.")
                await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "PM"})
                await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "PM"})
                return
            else:
                current_executing_stage = "Architect"
                await asyncio.sleep(0.5)

        # --- ARCHITECT & REVIEWER LOOP ---
        MAX_REVIEW_CYCLES = 3
        while current_executing_stage in ("Architect", "Reviewer"):
            # Get current review cycle
            async with AsyncSessionLocal() as db:
                run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                run_obj = run_res.scalars().first()
                review_cycle = run_obj.review_cycle_number if run_obj else 1

            # --- ARCHITECT STAGE ---
            if current_executing_stage == "Architect":
                # Fetch requirements content
                async with AsyncSessionLocal() as db:
                    art_res = await db.execute(
                        select(ProjectArtifact)
                        .where(
                            ProjectArtifact.project_id == project_id,
                            ProjectArtifact.run_id == run_id,
                            ProjectArtifact.artifact_type == "REQUIREMENTS"
                        )
                        .order_by(ProjectArtifact.version.desc())
                    )
                    prd_art = art_res.scalars().first()
                    prd = prd_art.content if prd_art else ""

                await sse_manager.publish(run_id, {"status": "ARCHITECT_STARTED", "cycle": review_cycle})
                if review_cycle > 1:
                    await sse_manager.publish(run_id, {"status": "ARCHITECT_REVISION_STARTED", "cycle": review_cycle})
                    await save_step(
                        run_id, "Architect", "THOUGHT", f"Revising system design based on reviewer feedback (Cycle {review_cycle})..."
                    )
                else:
                    await sse_manager.publish(run_id, {"status": "ARCHITECT_THINKING"})
                    await save_step(
                        run_id, "Architect", "THOUGHT", "Designing system topology, database models, and API endpoints..."
                    )
                await asyncio.sleep(0.8)

                arch = ArchitectAgent()
                if review_cycle > 1:
                    # Fetch previous architecture and reviewer feedback
                    async with AsyncSessionLocal() as db:
                        # Latest architecture
                        arch_art_res = await db.execute(
                            select(ProjectArtifact)
                            .where(
                                ProjectArtifact.project_id == project_id,
                                ProjectArtifact.run_id == run_id,
                                ProjectArtifact.artifact_type == "ARCHITECTURE"
                            )
                            .order_by(ProjectArtifact.version.desc())
                        )
                        prev_arch_obj = arch_art_res.scalars().first()
                        prev_arch = prev_arch_obj.content if prev_arch_obj else ""

                        # Reviewer decisions
                        dec_res = await db.execute(
                            select(Decision).where(Decision.run_id == run_id)
                        )
                        all_dec = dec_res.scalars().all()
                        reviewer_decisions = [d for d in all_dec if d.selected_option in ("High", "Medium", "Low", "Critical")]
                        reviewer_issues = [f"{d.title} (Severity: {d.selected_option})" for d in reviewer_decisions]
                        reviewer_recs = [d.description for d in reviewer_decisions if d.description]

                        # Fetch human rejection comments
                        app_res = await db.execute(
                            select(Approval)
                            .where(Approval.run_id == run_id, Approval.status == "REJECTED")
                            .order_by(Approval.created_at.desc())
                        )
                        latest_rejection = app_res.scalars().first()
                        if latest_rejection and latest_rejection.comments:
                            reviewer_issues.append(f"Human Feedback: {latest_rejection.comments}")
                            if latest_rejection.rationale:
                                reviewer_recs.append(latest_rejection.rationale)

                    architect_output = await arch.run(
                        initial_prompt=initial_prompt,
                        prd_content=prd,
                        revision_mode=True,
                        previous_architecture=prev_arch,
                        reviewer_issues=reviewer_issues,
                        reviewer_recommendations=reviewer_recs
                    )
                else:
                    architect_output = await arch.run(initial_prompt, prd)
                
                architecture_md = arch.format_architecture(architect_output)
                database_md = arch.format_database(architect_output)
                api_md = arch.format_api(architect_output)
                
                await save_step(run_id, "Architect", "ARTIFACT_PROPOSAL", architecture_md)
                await save_artifact(
                    project_id, run_id, "ARCHITECTURE", "System Architecture Design", architecture_md, "DRAFT", review_cycle_number=review_cycle
                )
                await save_artifact(
                    project_id, run_id, "DATABASE", "Database Design & Normalization", database_md, "DRAFT", review_cycle_number=review_cycle
                )
                await save_artifact(
                    project_id, run_id, "API", "API Structure & Contracts", api_md, "DRAFT", review_cycle_number=review_cycle
                )

                await save_decisions(project_id, run_id, architect_output.decisions)
                await sse_manager.publish(run_id, {"status": "ARCHITECT_COMPLETED", "cycle": review_cycle})
                if review_cycle > 1:
                    await sse_manager.publish(run_id, {"status": "ARCHITECT_REVISION_COMPLETED", "cycle": review_cycle})
                
                if approvals_enabled:
                    async with AsyncSessionLocal() as db:
                        run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                        run_obj = run_res.scalars().first()
                        if run_obj:
                            run_obj.status = "WAITING_APPROVAL"
                            run_obj.current_stage = "Architect"
                            approval = Approval(run_id=run_id, stage="Architect", status="PENDING", review_cycle_number=review_cycle)
                            db.add(approval)
                            db.add(run_obj)
                            await db.commit()
                            
                    await save_step(run_id, "System", "THOUGHT", f"System architecture designed (Cycle {review_cycle}). Waiting for human approval to proceed to QA Review.")
                    await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "Architect"})
                    await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "Architect"})
                    return
                else:
                    current_executing_stage = "Reviewer"
                    await asyncio.sleep(0.5)

            # --- REVIEWER STAGE ---
            if current_executing_stage == "Reviewer":
                # Fetch requirements and architecture content
                async with AsyncSessionLocal() as db:
                    prd_res = await db.execute(
                        select(ProjectArtifact)
                        .where(
                            ProjectArtifact.project_id == project_id,
                            ProjectArtifact.run_id == run_id,
                            ProjectArtifact.artifact_type == "REQUIREMENTS"
                        )
                        .order_by(ProjectArtifact.version.desc())
                    )
                    prd_art = prd_res.scalars().first()
                    prd = prd_art.content if prd_art else ""

                    arch_res = await db.execute(
                        select(ProjectArtifact)
                        .where(
                            ProjectArtifact.project_id == project_id,
                            ProjectArtifact.run_id == run_id,
                            ProjectArtifact.artifact_type == "ARCHITECTURE"
                        )
                        .order_by(ProjectArtifact.version.desc())
                    )
                    arch_art = arch_res.scalars().first()
                    architecture_md = arch_art.content if arch_art else ""

                await sse_manager.publish(run_id, {"status": "REVIEWER_STARTED", "cycle": review_cycle})
                await sse_manager.publish(run_id, {"status": "REVIEWER_THINKING"})
                await save_step(
                    run_id, "Reviewer", "THOUGHT", f"Challenging design choices, scalability bounds, and security risks (Cycle {review_cycle})..."
                )
                await asyncio.sleep(0.8)

                reviewer = CriticAgent()
                reviewer_output = await reviewer.run(initial_prompt, prd, architecture_md)
                reviewer_md = reviewer.format_review(reviewer_output)

                await save_step(run_id, "Reviewer", "ARTIFACT_PROPOSAL", reviewer_md)
                await save_artifact(
                    project_id, run_id, "ARCHITECTURE_REVIEW", "Architecture Review & Security Audit", reviewer_md, "DRAFT", review_cycle_number=review_cycle
                )

                await save_decisions(project_id, run_id, reviewer_output.review_decisions)
                await sse_manager.publish(run_id, {"status": "REVIEWER_COMPLETED", "cycle": review_cycle})
                await sse_manager.publish(run_id, {"status": "REVIEW_CYCLE_COMPLETED", "cycle": review_cycle})

                is_approved = reviewer_output.approved
                if not is_approved:
                    await sse_manager.publish(run_id, {"status": "REVIEW_REJECTED", "cycle": review_cycle})
                    await save_step(run_id, "System", "THOUGHT", f"Design Reviewer rejected architecture design in cycle {review_cycle}.")

                if approvals_enabled:
                    async with AsyncSessionLocal() as db:
                        run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                        run_obj = run_res.scalars().first()
                        if run_obj:
                            run_obj.status = "WAITING_APPROVAL"
                            run_obj.current_stage = "Reviewer"
                            # Store reviewer's approval status in comments dynamically so API approve endpoint can read it
                            agent_status_str = "AGENT_APPROVED" if is_approved else "AGENT_REJECTED"
                            approval = Approval(
                                run_id=run_id,
                                stage="Reviewer",
                                status="PENDING",
                                review_cycle_number=review_cycle,
                                comments=agent_status_str
                            )
                            db.add(approval)
                            db.add(run_obj)
                            await db.commit()
                            
                    await save_step(run_id, "System", "THOUGHT", f"QA Review completed (Cycle {review_cycle}). Waiting for human approval to proceed.")
                    await sse_manager.publish(run_id, {"status": "APPROVAL_REQUIRED", "stage": "Reviewer"})
                    await sse_manager.publish(run_id, {"status": "WAITING_APPROVAL", "current_stage": "Reviewer"})
                    return
                else:
                    if is_approved:
                        async with AsyncSessionLocal() as db:
                            result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                            run_obj = result.scalars().first()
                            if run_obj:
                                run_obj.status = "COMPLETED"
                                run_obj.completed_at = datetime.now()
                                db.add(run_obj)
                                await db.commit()

                        await sse_manager.publish(run_id, {"status": "COMPLETED"})
                        logger.info("Workflow run %s completed successfully", run_id)
                        return
                    else:
                        if review_cycle < MAX_REVIEW_CYCLES:
                            async with AsyncSessionLocal() as db:
                                run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                                run_obj = run_res.scalars().first()
                                if run_obj:
                                    run_obj.review_cycle_number = review_cycle + 1
                                    db.add(run_obj)
                                    await db.commit()
                            current_executing_stage = "Architect"
                            await asyncio.sleep(0.5)
                        else:
                            # Max review cycles reached without approval
                            async with AsyncSessionLocal() as db:
                                run_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                                run_obj = run_res.scalars().first()
                                if run_obj:
                                    run_obj.status = "FAILED"
                                    run_obj.completed_at = datetime.now()
                                    db.add(run_obj)
                                    await db.commit()
                            await save_step(run_id, "System", "CRITIQUE", f"Workflow execution failed: maximum review cycles ({MAX_REVIEW_CYCLES}) reached without approval.")
                            await sse_manager.publish(run_id, {"status": "FAILED", "error": "Max review cycles reached"})
                            return

    except Exception as e:
        logger.error("Workflow run %s stage failed: %s", run_id, str(e), exc_info=True)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
            run_obj = result.scalars().first()
            if run_obj:
                run_obj.status = "FAILED"
                run_obj.completed_at = datetime.now()
                db.add(run_obj)
                await db.commit()

        await save_step(run_id, "System", "CRITIQUE", f"Workflow execution crashed: {str(e)}")
        if current_executing_stage:
            stage_failed_status = f"{current_executing_stage.upper()}_FAILED"
            await sse_manager.publish(run_id, {"status": stage_failed_status, "error": str(e)})
        await sse_manager.publish(run_id, {"status": "FAILED", "error": str(e)})


