import logging
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.artifact import ProjectArtifact
from app.models.project import Decision
from app.models.run import AgentRun

logger = logging.getLogger(__name__)

class ProjectMemoryContext(BaseModel):
    previous_requirements: List[str] = []
    previous_architectures: List[str] = []
    previous_reviews: List[str] = []
    previous_decisions: List[str] = []
    summary: str = ""

async def load_project_memory(project_id: str) -> ProjectMemoryContext:
    async with AsyncSessionLocal() as db:
        # 1. Fetch any existing MEMORY_SUMMARY artifact (latest version)
        summary_res = await db.execute(
            select(ProjectArtifact)
            .where(
                ProjectArtifact.project_id == project_id, 
                ProjectArtifact.artifact_type == "MEMORY_SUMMARY"
            )
            .order_by(ProjectArtifact.version.desc())
        )
        latest_summary_art = summary_res.scalars().first()
        summary_text = latest_summary_art.content if latest_summary_art else ""

        # 2. Fetch the last completed run for the project to get the immediate previous state
        run_res = await db.execute(
            select(AgentRun)
            .where(AgentRun.project_id == project_id, AgentRun.status == "COMPLETED")
            .order_by(AgentRun.completed_at.desc())
        )
        last_completed_run = run_res.scalars().first()

        previous_requirements = []
        previous_architectures = []
        previous_reviews = []
        previous_decisions = []

        if last_completed_run:
            # Fetch artifacts for the last completed run
            art_res = await db.execute(
                select(ProjectArtifact)
                .where(
                    ProjectArtifact.project_id == project_id, 
                    ProjectArtifact.run_id == last_completed_run.id
                )
            )
            artifacts = art_res.scalars().all()
            for art in artifacts:
                if art.artifact_type == "REQUIREMENTS":
                    previous_requirements.append(art.content)
                elif art.artifact_type in ["ARCHITECTURE", "DATABASE", "API"]:
                    previous_architectures.append(f"{art.title}:\n{art.content}")
                elif art.artifact_type == "ARCHITECTURE_REVIEW":
                    previous_reviews.append(art.content)

            # Fetch decisions for the last completed run
            dec_res = await db.execute(
                select(Decision)
                .where(
                    Decision.project_id == project_id, 
                    Decision.run_id == last_completed_run.id
                )
            )
            decisions = dec_res.scalars().all()
            for dec in decisions:
                opts_str = ", ".join(dec.options) if dec.options else ""
                prev_dec_str = f"Decision: {dec.title} | Selected: {dec.selected_option} | Options: [{opts_str}] | Rationale: {dec.rationale}"
                previous_decisions.append(prev_dec_str)

        return ProjectMemoryContext(
            previous_requirements=previous_requirements,
            previous_architectures=previous_architectures,
            previous_reviews=previous_reviews,
            previous_decisions=previous_decisions,
            summary=summary_text
        )

async def summarize_memory(project_id: str, memory_context: ProjectMemoryContext, llm_provider) -> str:
    system_prompt = (
        "You are the Project Memory Summarizer at AGON OS. Your task is to analyze the history of a software project, "
        "including previous requirements, architectural designs, reviewer critiques, and key decisions. "
        "Synthesize and summarize this history into a single concise text block. "
        "Highlight the progress, key architectural choices made, reviewer feedback, and next steps. "
        "Keep it compact to prevent prompt bloating in subsequent runs."
    )
    
    user_prompt = (
        f"Project History to Summarize:\n\n"
        f"Previous Requirements:\n" + "\n".join(memory_context.previous_requirements) + "\n\n"
        f"Previous Architectures:\n" + "\n".join(memory_context.previous_architectures) + "\n\n"
        f"Previous Reviewer Critique:\n" + "\n".join(memory_context.previous_reviews) + "\n\n"
        f"Previous Decisions:\n" + "\n".join(memory_context.previous_decisions) + "\n\n"
        f"Existing Summary:\n{memory_context.summary}"
    )
    
    summary = await llm_provider.generate(system_prompt, user_prompt)
    return summary
