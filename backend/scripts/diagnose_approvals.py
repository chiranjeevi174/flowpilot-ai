import asyncio
import sys
import json
sys.stdout.reconfigure(encoding="utf-8")
from sqlalchemy import select
from flowpilot.db.session import async_session_factory
from flowpilot.models.agent_run import AgentRun
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.external_action import ExternalAction
from flowpilot.models.user import User

async def inspect_runs():
    factory = async_session_factory()
    async with factory() as session:
        runs = (await session.execute(
            select(AgentRun).where(AgentRun.status == "awaiting_approval")
        )).scalars().all()

        for r in runs:
            user = await session.get(User, r.user_id)
            print("=" * 60)
            print(f"RUN ID: {r.id}")
            print(f"User: {user.email if user else 'Unknown'} (id={r.user_id})")
            print(f"Status: {r.status}, Current Step: {r.current_step}")
            print(f"Created At: {r.created_at}, Updated At: {r.updated_at}")
            print(f"Original Request: {r.original_request}")
            print(f"Execution Plan: {json.dumps(r.execution_plan, indent=2) if r.execution_plan else 'None'}")
            
            # Events
            events = (await session.execute(
                select(AgentEvent).where(AgentEvent.run_id == r.id).order_by(AgentEvent.timestamp)
            )).scalars().all()
            print(f"Events count: {len(events)}")
            for e in events:
                print(f"  [{e.timestamp}] {e.agent_name} -> {e.event_type}: {e.event_payload}")
            
            # External actions
            actions = (await session.execute(
                select(ExternalAction).where(ExternalAction.run_id == r.id)
            )).scalars().all()
            print(f"External Actions count: {len(actions)}")
            for a in actions:
                print(f"  Action: id={a.id}, op={a.operation}, status={a.status}")

if __name__ == "__main__":
    asyncio.run(inspect_runs())
