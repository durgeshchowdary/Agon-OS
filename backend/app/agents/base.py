import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class BaseAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.ollama_url = f"{settings.OLLAMA_BASE_URL}/v1/chat/completions"
        
    async def is_ollama_available(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(settings.OLLAMA_BASE_URL, timeout=1.0)
                return response.status_code == 200
        except Exception:
            return False

    async def generate_response(self, system_prompt: str, user_prompt: str, timeout: float = 8.0) -> str:
        return self._generate_mock_content(user_prompt)

    def _generate_mock_content(self, user_prompt: str) -> str:
        # Extrapolate keywords from prompt to make mock content highly realistic
        prompt_lower = user_prompt.lower()
        topic = "Software Platform"
        if "gst" in prompt_lower:
            topic = "GST Filing Platform"
        elif "ecommerce" in prompt_lower or "shop" in prompt_lower:
            topic = "E-Commerce System"
        elif "school" in prompt_lower or "lms" in prompt_lower:
            topic = "Learning Management System"
            
        if self.name == "PM":
            return f"""# Product Requirements Document (PRD): {topic}
Version: 1.0
Status: Draft

## 1. Executive Summary
The goal is to build a production-grade {topic} tailored to address efficiency, security, and compliance.

## 2. Core Functional Requirements
- **FR1: User Onboarding & Auth**: Secure registration, multi-factor login, and role-based access control (RBAC).
- **FR2: Data Dashboard**: Real-time dashboard showing status logs, analytical charts, and compliance trackers.
- **FR3: Core Transactions Engine**: System should process transactions, generate invoices, and validate inputs against rules.
- **FR4: External Integration**: Standard REST APIs to sync with government portals/payment gateways.

## 3. User Stories
- **US101 (Merchant / User)**: As an owner, I want to upload financial statements so that the system automatically tags GST brackets.
- **US102 (Auditor)**: As an auditor, I want to export report logs as signed PDF/Excel sheets.
- **US103 (System Admin)**: As an admin, I want to manage system rate-limits and active sessions to maintain stability.
"""
        elif self.name == "Architect":
            return f"""# Architecture & Technical Design: {topic}
Version: 1.0
Status: Draft

## 1. System Topology
The system follows a modular monolith architecture built with FastAPI (Python) and React/Next.js.

```
[React/Next.js Client] ---> [FastAPI API Gateway]
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
            [Auth Module]  [Billing Engine]  [Report Sync]
                  │               │               │
                  └───────────────┼───────────────┘
                                  ▼
                            [PostgreSQL DB]
```

## 2. Database Design (PostgreSQL)
We model our database with strict constraints to ensure transactional integrity:
- **`users`**: `id` (UUID), `email` (VARCHAR), `password_hash` (VARCHAR), `role` (VARCHAR)
- **`accounts`**: `id` (UUID), `user_id` (UUID, FK), `company_name` (VARCHAR), `gstin` (VARCHAR)
- **`transactions`**: `id` (UUID), `account_id` (UUID, FK), `amount` (NUMERIC), `gst_amount` (NUMERIC), `status` (VARCHAR)

## 3. API Contract Specifications
- `POST /api/v1/billing/calculate`: Takes invoice entries and returns calculated taxes.
- `GET /api/v1/billing/reports/{id}`: Downloads pre-rendered compliance documents.
"""
        elif self.name == "Critic":
            return f"""# Architecture & Requirements Critique: {topic}
Review Stage: Debate Turn

## 1. Critical Concerns identified
- **Security Flaw**: The database schema proposes storing GSTIN as a plain VARCHAR without verification metadata. We need validation logs.
- **API Scalability**: `GET /api/v1/billing/reports/{{id}}` is synchronous. For heavy PDF generation, this will block FastAPI workers.
- **Missing Requirements**: There is no database audit log or ledger, which is vital for compliance systems.

## 2. Recommended Action Items
1. Add an `audit_logs` table: `id` (UUID), `actor_id` (UUID), `action` (TEXT), `timestamp` (TIMESTAMP).
2. Change the report API to an asynchronous processing pattern: return a ticket ID, generate PDF in background, notify client.
"""
        elif self.name == "CTO":
            return f"""# CTO Decision & Review Sign-Off: {topic}
Status: APPROVED
Approved Version: 1.0

## 1. Executive Arbitrations
Having reviewed the debate and the Critic's feedback, the following design mitigations are mandated:
- **Decided**: We will use PostgreSQL with an asynchronous database driver (`asyncpg`) and implement a task queue for heavy report generation.
- **Decided**: Auditing must be first-class. We will add the `audit_logs` table as requested by the Critic.

## 2. Approved Artifact Manifest
- **Requirements Document**: Approved v1.0 with revision for async job tickets.
- **System Architecture**: Approved v1.0 with PostgreSQL schema including verification logs and audit tracking.
"""
        return f"Mock response for {self.name} agent on topic: {topic}"
