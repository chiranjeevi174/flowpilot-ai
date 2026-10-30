"""Development and E2E database seeding script."""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from flowpilot.core.config import get_settings
from flowpilot.core.encryption import encrypt_api_key, generate_key_fingerprint
from flowpilot.core.security import hash_password
from flowpilot.db.session import async_session_factory
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.llm_credential import LLMCredential
from flowpilot.models.llm_preference import LLMPreference
from flowpilot.models.user import User

settings = get_settings()


async def seed() -> None:
    """Seed test operator user and initial credentials for development and testing environments."""
    if settings.ENVIRONMENT.lower() == "production":
        raise RuntimeError(
            "CRITICAL SECURITY VIOLATION: seed_dev.py cannot be executed in production "
            "environment (ENVIRONMENT='production'). Use standard registration or provisioning."
        )

    factory = async_session_factory()
    async with factory() as session:
        # 1. Operator user
        result = await session.execute(select(User).where(User.email == "operator@flowpilot.ai"))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email="operator@flowpilot.ai",
                full_name="FlowPilot Operator",
                password_hash=hash_password("Password123!"),
                is_active=True,
            )
            session.add(user)
            await session.flush()
            print(f"Created operator user: {user.id}")
        else:
            print(f"Operator user already exists: {user.id}")

        # 2. Add LLM Credentials if missing
        providers = [
            ("gemini", "AIzaSyTestGeminiMockKey1234567890"),
            ("openai", "sk-proj-testOpenAIMockKey1234567890"),
            ("groq", "gsk_testGroqMockKey1234567890abcdef"),
        ]

        groq_cred_id = None
        for prov, mock_key in providers:
            cred_res = await session.execute(
                select(LLMCredential).where(
                    LLMCredential.user_id == user.id,
                    LLMCredential.provider == prov,
                )
            )
            cred = cred_res.scalar_one_or_none()
            if cred is None:
                cred = LLMCredential(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    provider=prov,
                    encrypted_api_key=encrypt_api_key(mock_key),
                    key_fingerprint=generate_key_fingerprint(mock_key),
                    last_validated_at=datetime.now(UTC),
                )
                session.add(cred)
                await session.flush()
                print(f"Connected {prov} credential: {cred.id}")
            if prov == "groq":
                groq_cred_id = cred.id

        # 3. Default preference
        pref_res = await session.execute(
            select(LLMPreference).where(LLMPreference.user_id == user.id)
        )
        pref = pref_res.scalar_one_or_none()
        if pref is None and groq_cred_id:
            pref = LLMPreference(
                id=uuid.uuid4(),
                user_id=user.id,
                credential_id=groq_cred_id,
                provider="groq",
                model_id="llama-3.3-70b-versatile",
            )
            session.add(pref)
            await session.flush()
            print("Set default preference to Groq llama-3.3-70b-versatile")

        # 4. Seed sample run in AWAITING_APPROVAL if none exists
        run_res = await session.execute(
            select(AgentRun).where(AgentRun.user_id == user.id).limit(1)
        )
        existing_run = run_res.scalars().first()
        if existing_run is None:
            sample_run_id = uuid.uuid4()
            sample_run = AgentRun(
                id=sample_run_id,
                user_id=user.id,
                thread_id=f"flowpilot_run_{sample_run_id}",
                original_request="Weekly Ops Briefing: Fetch metrics and post to Slack.",
                status=AgentRunStatus.AWAITING_APPROVAL,
                detected_intent={"intent": "weekly_ops_briefing", "confidence": 0.98},
                execution_plan=[
                    {"id": 1, "description": "Fetch metrics", "status": "completed"},
                    {
                        "id": 2,
                        "description": "Post executive summary to Slack",
                        "status": "pending_approval",
                    },
                ],
            )
            session.add(sample_run)
            await session.flush()

            event = AgentEvent(
                id=uuid.uuid4(),
                run_id=sample_run_id,
                agent_name="verifier",
                event_type="approval_requested",
                event_payload={"action": "slack_post_message", "target": "#general"},
            )
            session.add(event)
            await session.flush()
            print(f"Created sample approval run: {sample_run_id}")

        await session.commit()
        print("Database seeding completed successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
