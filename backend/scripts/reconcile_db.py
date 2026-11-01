"""Safe and idempotent database reconciliation script for FlowPilot AI.

Supports dry-run report mode and applied mode for demonstrably inconsistent records.
Preserves all historical records, audit events, and decisions.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from flowpilot.db.session import async_session_factory
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.scheduled_workflow import ScheduleType, ScheduledWorkflow
from flowpilot.models.user import User

sys.stdout.reconfigure(encoding="utf-8")


async def reconcile(apply_changes: bool = False) -> None:
    mode_str = "APPLYING CHANGES" if apply_changes else "DRY-RUN (Report Only)"
    print(f"=== FlowPilot Database Reconciliation [{mode_str}] ===")

    factory = async_session_factory()
    async with factory() as session:
        # 1. Inspect AgentRuns in AWAITING_APPROVAL state
        runs_stmt = select(AgentRun).where(
            AgentRun.status == AgentRunStatus.AWAITING_APPROVAL
        )
        runs = (await session.execute(runs_stmt)).scalars().all()

        runs_to_reconcile: list[tuple[AgentRun, str]] = []
        for r in runs:
            user = await session.get(User, r.user_id)
            user_email = user.email if user else str(r.user_id)

            # Check if this run has an execution plan or failed during intent/planning
            events_stmt = (
                select(AgentEvent)
                .where(AgentEvent.run_id == r.id)
                .order_by(AgentEvent.timestamp.desc())
            )
            events = (await session.execute(events_stmt)).scalars().all()
            failed_event = next(
                (e for e in events if "failed" in e.event_type.lower() or "error" in e.event_type.lower()),
                None,
            )

            is_broken = False
            reason = ""
            if r.execution_plan is None and failed_event:
                is_broken = True
                err_msg = failed_event.event_payload.get("error", "Workflow initialization failed")
                reason = f"Run failed at stage '{failed_event.agent_name}' ({err_msg}) but was left in 'awaiting_approval' without a valid execution plan."
            elif r.execution_plan is None and r.current_step == 0:
                is_broken = True
                reason = "Run has no execution plan and step is 0 while marked 'awaiting_approval'."

            if is_broken:
                runs_to_reconcile.append((r, reason))
                print(f"[INCONSISTENT RUN] Run ID: {r.id}")
                print(f"  Owner: {user_email}")
                print(f"  Current Status: {r.status}")
                print(f"  Diagnostic: {reason}")
                print(f"  Proposed Action: Set status -> '{AgentRunStatus.FAILED}'")
            else:
                print(f"[VALID ACTIONABLE RUN] Run ID: {r.id}")
                print(f"  Owner: {user_email}")
                print(f"  Current Status: {r.status}")
                print(f"  Execution Plan: {len(r.execution_plan or [])} steps, step {r.current_step}")

        # 2. Inspect One-Time Schedules with last_run_at set but is_active=True
        scheds_stmt = select(ScheduledWorkflow).where(
            ScheduledWorkflow.schedule_type == ScheduleType.ONE_TIME
        )
        schedules = (await session.execute(scheds_stmt)).scalars().all()

        schedules_to_reconcile: list[tuple[ScheduledWorkflow, str]] = []
        for s in schedules:
            user = await session.get(User, s.user_id)
            user_email = user.email if user else str(s.user_id)

            if s.last_run_at is not None and s.is_active is True:
                reason = f"One-time schedule has executed (last_run_at={s.last_run_at}) but is_active is still True."
                schedules_to_reconcile.append((s, reason))
                print(f"[INCONSISTENT SCHEDULE] Schedule ID: {s.id} ('{s.name}')")
                print(f"  Owner: {user_email}")
                print(f"  Diagnostic: {reason}")
                print("  Proposed Action: Set is_active -> False (move to Schedule History)")
            else:
                status_label = "Active (Upcoming)" if s.is_active and not s.last_run_at else "Historical (Executed)"
                print(f"[VALID SCHEDULE] Schedule ID: {s.id} ('{s.name}') - Type: {s.schedule_type} - {status_label}")

        # 3. Inspect Failed Runs with Succeeded External Actions (Post-Send Verification Failure)
        failed_runs_stmt = select(AgentRun).where(
            AgentRun.status == AgentRunStatus.FAILED
        )
        failed_runs = (await session.execute(failed_runs_stmt)).scalars().all()

        dispatched_runs_to_reconcile: list[tuple[AgentRun, ExternalAction, str]] = []
        for fr in failed_runs:
            user = await session.get(User, fr.user_id)
            user_email = user.email if user else str(fr.user_id)

            # Check if there is a successful external action linked to this run
            ea_stmt = (
                select(ExternalAction)
                .where(
                    ExternalAction.run_id == fr.id,
                    ExternalAction.status == ExternalActionStatus.SUCCEEDED,
                )
                .order_by(ExternalAction.created_at.desc())
            )
            ea_result = await session.execute(ea_stmt)
            succeeded_actions = ea_result.scalars().all()

            if succeeded_actions:
                primary_action = succeeded_actions[0]
                reason = (
                    f"Run was marked failed by internal post-send verification "
                    f"('{fr.error_message}'), but external dispatch operation "
                    f"'{primary_action.operation}' succeeded and was accepted by provider "
                    f"(Message ID: {primary_action.provider_action_id})."
                )
                dispatched_runs_to_reconcile.append((fr, primary_action, reason))
                print(f"\n[POST-SEND VERIFICATION FAILURE RUN] Run ID: {fr.id}")
                print(f"  Owner: {user_email}")
                print(f"  Current Run Status: {fr.status}")
                print(f"  External Action: {primary_action.operation} (ID: {primary_action.id})")
                print(f"  Provider Action ID: {primary_action.provider_action_id}")
                print(f"  Diagnostic: {reason}")
                print(f"  Proposed Action: Reconcile run status -> '{AgentRunStatus.COMPLETED}' (preserve audit history)")

        print("\n--- Summary ---")
        print(f"Inconsistent awaiting_approval runs found: {len(runs_to_reconcile)}")
        print(f"Inconsistent schedules found: {len(schedules_to_reconcile)}")
        print(f"Dispatched runs with post-send failure found: {len(dispatched_runs_to_reconcile)}")

        if not runs_to_reconcile and not schedules_to_reconcile and not dispatched_runs_to_reconcile:
            print("Database is consistent. No reconciliation needed.")
            return

        if apply_changes:
            now_utc = datetime.now(UTC)
            for r, reason in runs_to_reconcile:
                r.status = AgentRunStatus.FAILED
                r.completed_at = r.updated_at or now_utc
                if not r.error_message:
                    r.error_message = reason
                print(f"Applied fix to run {r.id}: status -> {r.status}")

            for s, _ in schedules_to_reconcile:
                s.is_active = False
                s.updated_at = now_utc
                print(f"Applied fix to schedule {s.id}: is_active -> False")

            for fr, ea, reason in dispatched_runs_to_reconcile:
                # 1. Record an audit event preserving historical failure and reconciliation details
                audit_event = AgentEvent(
                    run_id=fr.id,
                    agent_name="reconciliation",
                    event_type="run_reconciled",
                    event_payload={
                        "previous_status": AgentRunStatus.FAILED,
                        "reconciled_status": AgentRunStatus.COMPLETED,
                        "discrepancy": reason,
                        "operation": ea.operation,
                        "provider_action_id": ea.provider_action_id,
                        "original_error_message": fr.error_message,
                    },
                    timestamp=now_utc,
                )
                session.add(audit_event)

                # 2. Update run to accurately reflect external dispatch completion
                fr.status = AgentRunStatus.COMPLETED
                current_final = fr.final_result if isinstance(fr.final_result, dict) else {}
                current_final["reconciled"] = True
                current_final["reconciliation_note"] = (
                    "Reconciled: Email was successfully accepted by Gmail API before internal verification failure."
                )
                current_final["original_verification_critique"] = fr.error_message
                current_final["delivery_status"] = "api_accepted"
                current_final["message_id"] = ea.provider_action_id
                current_final["status"] = "completed"
                current_final["summary"] = (
                    f"Workflow completed. Email dispatched and accepted by Gmail API "
                    f"(Message ID: {ea.provider_action_id})."
                )
                fr.final_result = current_final
                fr.error_message = None
                print(f"Applied reconciliation to run {fr.id}: status -> {fr.status} (Message ID: {ea.provider_action_id})")

            await session.commit()
            print("Successfully committed reconciliation changes to database.")
        else:
            print("\nDry-run complete. Re-run with '--apply' to persist these changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FlowPilot AI Database Reconciliation")
    parser.add_argument("--apply", action="store_true", help="Apply proposed changes to database")
    args = parser.parse_args()

    asyncio.run(reconcile(apply_changes=args.apply))
