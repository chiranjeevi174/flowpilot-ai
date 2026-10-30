import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")
from sqlalchemy import select
from flowpilot.db.session import async_session_factory
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.scheduled_workflow import ScheduledWorkflow, ScheduleType
from flowpilot.models.notification import Notification
from flowpilot.models.user import User

async def inspect():
    factory = async_session_factory()
    async with factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        print("=== USERS ===")
        for u in users:
            print(f"User: id={u.id}, email={u.email}")

        schedules = (await session.execute(select(ScheduledWorkflow))).scalars().all()
        print(f"\n=== SCHEDULED WORKFLOWS (Total: {len(schedules)}) ===")
        for s in schedules:
            user = await session.get(User, s.user_id)
            print(f"Schedule: id={s.id}, user={user.email if user else 'Unknown'}, name='{s.name}', type={s.schedule_type}, is_active={s.is_active}, last_run={s.last_run_at}, next_run={s.next_run_at}")

        runs = (await session.execute(select(AgentRun).where(AgentRun.status == "awaiting_approval"))).scalars().all()
        print(f"\n=== RUNS AWAITING APPROVAL (Total: {len(runs)}) ===")
        for r in runs:
            user = await session.get(User, r.user_id)
            print(f"Run: id={r.id}, user={user.email if user else 'Unknown'}, status={r.status}, schedule_id={r.schedule_id}")
            print(f"     request: {r.original_request[:80]}")
            print(f"     step: {r.current_step}, plan: {str(r.execution_plan)[:100]}")

if __name__ == "__main__":
    asyncio.run(inspect())
