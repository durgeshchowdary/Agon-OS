import json
import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import ProjectArtifact
from app.models.run import AgentRun, AgentStep, Approval
from app.agents.code_reviewer import CodeReviewAgent
from app.schemas.code_reviewer import CodeReviewOutput
from app.workflow.engine import save_step, save_artifact

logger = logging.getLogger(__name__)

class CodeReviewService:
    @staticmethod
    async def review_code(
        db: AsyncSession,
        project_id: str,
        run_id: str
    ) -> CodeReviewOutput:
        # 1. Fetch input artifacts
        # Requirements
        prd_res = await db.execute(
            select(ProjectArtifact)
            .where(ProjectArtifact.project_id == project_id, ProjectArtifact.artifact_type == "REQUIREMENTS")
            .order_by(ProjectArtifact.version.desc())
        )
        prd = prd_res.scalars().first()
        prd_content = prd.content if prd else ""

        # Architecture
        arch_res = await db.execute(
            select(ProjectArtifact)
            .where(ProjectArtifact.project_id == project_id, ProjectArtifact.artifact_type == "ARCHITECTURE")
            .order_by(ProjectArtifact.version.desc())
        )
        arch = arch_res.scalars().first()
        arch_content = arch.content if arch else ""

        # Backlog
        backlog_res = await db.execute(
            select(ProjectArtifact)
            .where(ProjectArtifact.project_id == project_id, ProjectArtifact.artifact_type == "BACKLOG")
            .order_by(ProjectArtifact.version.desc())
        )
        backlog = backlog_res.scalars().first()
        backlog_content = backlog.content if backlog else ""

        # Generated Files
        files_res = await db.execute(
            select(ProjectArtifact)
            .where(ProjectArtifact.run_id == run_id, ProjectArtifact.artifact_type == "GENERATED_FILE")
        )
        gen_files = files_res.scalars().all()
        
        generated_files_list = []
        for gf in gen_files:
            generated_files_list.append(f"File: {gf.title}\nContent:\n{gf.content}\n")
        generated_files_content = "\n".join(generated_files_list)

        # Existing codebase indices from RIL
        from app.models.repo_intel import RepoRoute, RepoClass, RepoFunction
        
        routes_res = await db.execute(select(RepoRoute))
        routes = routes_res.scalars().all()
        
        classes_res = await db.execute(select(RepoClass))
        classes = classes_res.scalars().all()
        
        funcs_res = await db.execute(select(RepoFunction).where(RepoFunction.class_name == None))
        funcs = funcs_res.scalars().all()
        
        indices_list = ["API Routes:"]
        for r in routes:
            indices_list.append(f"- {r.http_method} {r.route_path} ({r.file_path})")
        indices_list.append("\nClasses:")
        for c in classes:
            indices_list.append(f"- {c.class_name} ({c.file_path})")
        indices_list.append("\nTop-level Functions:")
        for f in funcs:
            indices_list.append(f"- {f.function_name} ({f.file_path})")
        existing_codebase_indices = "\n".join(indices_list)

        # 2. Invoke CodeReviewAgent
        agent = CodeReviewAgent()
        review_output = await agent.run(
            prd_content=prd_content,
            architecture_content=arch_content,
            backlog_content=backlog_content,
            generated_files_content=generated_files_content,
            existing_codebase_indices=existing_codebase_indices
        )

        # 3. Recalculate score & status based on primary criteria (findings severity)
        score = 100.0
        has_critical_or_high = False
        has_medium = False
        
        for f in review_output.findings:
            sev = f.severity.upper()
            if sev == "CRITICAL":
                score -= 30.0
                has_critical_or_high = True
            elif sev == "HIGH":
                score -= 15.0
                has_critical_or_high = True
            elif sev == "MEDIUM":
                score -= 5.0
                has_medium = True
            elif sev == "LOW":
                score -= 2.0
                
        score = max(0.0, score)
        review_output.score = score

        # Primary PASS/WARNING/FAIL decision mechanism:
        if has_critical_or_high:
            review_output.status = "FAIL"
        elif has_medium:
            review_output.status = "WARNING"
        else:
            review_output.status = "PASS"

        # 4. Save review artifact
        review_json = review_output.model_dump_json(indent=2)
        
        # Save step details
        formatted_report = (
            f"### Code Review Report\n\n"
            f"**Status**: {review_output.status}\n"
            f"**Score**: {review_output.score}/100.0\n\n"
            f"#### Summary\n{review_output.summary}\n\n"
            f"#### Findings\n"
        )
        if not review_output.findings:
            formatted_report += "*No issues found.*\n"
        else:
            formatted_report += "| Category | Severity | File Path | Finding | Recommendation |\n"
            formatted_report += "|---|---|---|---|---|\n"
            for f in review_output.findings:
                line_str = f" (Line {f.line_number})" if f.line_number else ""
                formatted_report += f"| {f.category} | {f.severity} | {f.file_path}{line_str} | **{f.finding_title}**: {f.description} | {f.recommendation} |\n"

        await save_step(run_id, "CodeReviewer", "ARTIFACT_PROPOSAL", formatted_report)
        
        # Save as CODE_REVIEW artifact
        # Note: we need to fetch the next version for this project's code review
        await save_artifact(
            project_id,
            run_id,
            "CODE_REVIEW",
            "Automated Code Review Report",
            review_json,
            "DRAFT"
        )
        
        return review_output
