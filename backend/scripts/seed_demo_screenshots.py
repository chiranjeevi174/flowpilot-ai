"""Seed clean demo data for screenshots."""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from flowpilot.db.session import async_session_factory
from flowpilot.models.user import User
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.scheduled_workflow import ScheduledWorkflow
from flowpilot.models.notification import Notification

async def seed_demo():
    factory = async_session_factory()
    async with factory() as session:
        user = (await session.execute(select(User).where(User.email == "operator@flowpilot.ai"))).scalar_one()

        # Check if approval run already exists
        app_run = (await session.execute(
            select(AgentRun).where(
                AgentRun.user_id == user.id,
                AgentRun.status == AgentRunStatus.AWAITING_APPROVAL
            )
        )).scalars().first()

        if not app_run:
            app_run_id = uuid.uuid4()
            app_run = AgentRun(
                id=app_run_id,
                user_id=user.id,
                thread_id=f"flowpilot_run_{app_run_id.hex[:12]}",
                original_request="Weekly Ops Briefing: Fetch telemetry metrics, synthesize executive summary, and post to Slack #general",
                status=AgentRunStatus.AWAITING_APPROVAL,
                current_step=1,
                detected_intent={"intent": "weekly_ops_briefing", "action": "slack_post_message", "confidence": 0.98},
                execution_plan=[
                    {
                        "step_id": "step_1",
                        "operation": "telemetry_fetch_metrics",
                        "expected_outcome": "Collect API response latencies, worker queue depths, and uptime stats for the trailing 7 days.",
                        "status": "completed",
                        "approval_required": False,
                        "parameters": {"window": "7d", "services": ["api", "workers", "redis", "postgres"]}
                    },
                    {
                        "step_id": "step_2",
                        "operation": "slack_post_message",
                        "expected_outcome": "Post the verified executive briefing to Slack channel #general.",
                        "status": "pending_approval",
                        "approval_required": True,
                        "parameters": {
                            "channel": "#general",
                            "message": "📊 *FlowPilot AI Weekly Briefing*: Platform uptime at 99.98%. 1,240 automated workflows executed. All 4 integration channels healthy."
                        }
                    }
                ]
            )
            session.add(app_run)
            await session.flush()

            # Add event
            ev1 = AgentEvent(
                id=uuid.uuid4(),
                run_id=app_run_id,
                agent_name="verifier",
                event_type="approval_requested",
                event_payload={
                    "step": 2,
                    "operation": "slack_post_message",
                    "channel": "#general",
                    "reason": "External dispatch to public Slack channel requires operator consent."
                }
            )
            session.add(ev1)

            # Add external action
            ext1 = ExternalAction(
                id=uuid.uuid4(),
                user_id=user.id,
                run_id=app_run_id,
                operation="slack_post_message",
                parameter_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                idempotency_key=f"slack_briefing_{uuid.uuid4().hex[:8]}",
                status=ExternalActionStatus.PENDING,
                provider_response={}
            )
            session.add(ext1)
            print("Added awaiting_approval run:", app_run_id)

        # Check completed run for workflow-execution view
        comp_run = (await session.execute(
            select(AgentRun).where(
                AgentRun.user_id == user.id,
                AgentRun.status == AgentRunStatus.COMPLETED
            )
        )).scalars().first()

        if not comp_run:
            comp_run_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            comp_run = AgentRun(
                id=comp_run_id,
                user_id=user.id,
                thread_id=f"flowpilot_run_{comp_run_id.hex[:12]}",
                original_request="Synchronize Q4 Customer Survey Insights from Google Sheets and Generate Multi-Agent Analysis",
                status=AgentRunStatus.COMPLETED,
                current_step=3,
                created_at=now - timedelta(minutes=12),
                completed_at=now - timedelta(minutes=11, seconds=45),
                detected_intent={"intent": "data_analysis_sync", "action": "sheets_read_and_analyze", "confidence": 0.99},
                execution_plan=[
                    {
                        "step_id": "step_1",
                        "operation": "sheets_read_range",
                        "expected_outcome": "Fetch 250 response records from Sheet Q4_Survey_Feedback range A2:G251.",
                        "status": "completed",
                        "approval_required": False,
                        "parameters": {"spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms", "range": "Q4_Survey_Feedback!A2:G251"}
                    },
                    {
                        "step_id": "step_2",
                        "operation": "llm_synthesize_sentiment",
                        "expected_outcome": "Extract themes, sentiment distribution, and top 5 feature requests using Gemini 2.5 Flash.",
                        "status": "completed",
                        "approval_required": False,
                        "parameters": {"model": "gemini-2.5-flash", "temperature": 0.2}
                    },
                    {
                        "step_id": "step_3",
                        "operation": "sheets_append_summary",
                        "expected_outcome": "Append verified executive summary and KPI rows to Q4_Survey_Feedback Summary tab.",
                        "status": "completed",
                        "approval_required": False,
                        "parameters": {"spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms", "range": "Summary!A1:D10"}
                    }
                ],
                final_result={
                    "status": "verified",
                    "summary": "Successfully processed 250 customer survey responses. Net sentiment score: +78. Top requested enhancement: Multi-LLM BYOK token caching. Executive report appended to spreadsheet.",
                    "metrics": {
                        "total_responses_processed": 250,
                        "sentiment_positive": "84.8%",
                        "sentiment_neutral": "11.2%",
                        "sentiment_negative": "4.0%"
                    },
                    "verification_signature": "sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
                }
            )
            session.add(comp_run)
            await session.flush()

            # Add rich events
            evs = [
                ("orchestrator", "workflow_started", {"thread_id": comp_run.thread_id, "user": "operator@flowpilot.ai"}),
                ("planner", "plan_synthesized", {"total_steps": 3, "strategy": "batch_read_synthesize_append"}),
                ("google_sheets_agent", "data_extracted", {"rows_read": 250, "columns": 7, "range": "Q4_Survey_Feedback!A2:G251"}),
                ("analysis_agent", "synthesis_completed", {"model": "gemini-2.5-flash", "tokens_prompt": 1840, "tokens_completion": 412}),
                ("verifier", "verification_passed", {"integrity": "100%", "discrepancies": 0, "checksum": "passed"}),
                ("orchestrator", "workflow_completed", {"status": "completed", "total_duration_sec": 14.8})
            ]
            for idx, (ag, ev_type, pl) in enumerate(evs):
                session.add(AgentEvent(
                    id=uuid.uuid4(),
                    run_id=comp_run_id,
                    agent_name=ag,
                    event_type=ev_type,
                    event_payload=pl,
                    timestamp=now - timedelta(minutes=12 - idx)
                ))

            # Add completed external action
            session.add(ExternalAction(
                id=uuid.uuid4(),
                user_id=user.id,
                run_id=comp_run_id,
                operation="sheets_append_summary",
                parameter_digest="b8c3a55928fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b112",
                idempotency_key=f"sheets_sync_{uuid.uuid4().hex[:8]}",
                status=ExternalActionStatus.SUCCEEDED,
                provider_action_id="sheets_row_summary_14",
                approval_reference="pre_authorized_data_sync",
                provider_response={"updatedRange": "Summary!A1:D10", "updatedRows": 10, "status": "200 OK"}
            ))
            print("Added completed run:", comp_run_id)

        # Check schedules
        schedules = (await session.execute(
            select(ScheduledWorkflow).where(ScheduledWorkflow.user_id == user.id)
        )).scalars().all()

        if len(schedules) == 0:
            now = datetime.now(timezone.utc)
            s1 = ScheduledWorkflow(
                id=uuid.uuid4(),
                user_id=user.id,
                name="Daily Infrastructure & Error Telemetry Sync",
                workflow_request="Collect daily error telemetry from monitoring, summarize failure patterns, and dispatch report.",
                schedule_type="daily",
                timezone="America/New_York",
                schedule_configuration={"cron": "0 8 * * *", "description": "Every day at 8:00 AM Eastern"},
                next_run_at=now + timedelta(hours=11, minutes=25),
                is_active=True
            )
            s2 = ScheduledWorkflow(
                id=uuid.uuid4(),
                user_id=user.id,
                name="Weekly Executive Briefing & KPI Sync",
                workflow_request="Synthesize weekly system performance metrics and post to team channel.",
                schedule_type="weekly",
                timezone="UTC",
                schedule_configuration={"cron": "0 17 * * 5", "description": "Every Friday at 5:00 PM UTC"},
                next_run_at=now + timedelta(days=2, hours=4),
                is_active=True
            )
            s3 = ScheduledWorkflow(
                id=uuid.uuid4(),
                user_id=user.id,
                name="Quarterly Performance Audit",
                workflow_request="One-time comprehensive audit of all multi-agent latencies and cost breakdown.",
                schedule_type="one_time",
                timezone="UTC",
                schedule_configuration={"type": "one_time"},
                next_run_at=now - timedelta(days=7),
                last_run_at=now - timedelta(days=7),
                is_active=False
            )
            session.add_all([s1, s2, s3])
            print("Added 3 schedules")

        # Check notifications
        notifs = (await session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )).scalars().all()

        if len(notifs) == 0:
            now = datetime.now(timezone.utc)
            run_link_id = str(comp_run.id) if comp_run else ""
            n1 = Notification(
                id=uuid.uuid4(),
                user_id=user.id,
                type="approval_required",
                category="security",
                title="Action Authorization Required",
                message="Weekly Ops Briefing requires approval to dispatch message to Slack #general.",
                link_url="/approvals",
                dedup_key=f"approval_notif_{uuid.uuid4().hex[:8]}",
                is_read=False,
                created_at=now - timedelta(minutes=15)
            )
            n2 = Notification(
                id=uuid.uuid4(),
                user_id=user.id,
                type="schedule_countdown",
                category="workflow",
                title="Upcoming Scheduled Workflow",
                message="Daily Infrastructure & Error Telemetry Sync is scheduled to run at 8:00 AM.",
                link_url="/schedules",
                dedup_key=f"schedule_notif_{uuid.uuid4().hex[:8]}",
                is_read=False,
                created_at=now - timedelta(minutes=45)
            )
            n3 = Notification(
                id=uuid.uuid4(),
                user_id=user.id,
                type="workflow_started",
                category="general",
                title="Workflow Execution Completed",
                message="Customer Survey Insights execution finished with 0 errors.",
                link_url=f"/executions/{run_link_id}",
                dedup_key=f"completed_notif_{uuid.uuid4().hex[:8]}",
                is_read=True,
                created_at=now - timedelta(hours=2)
            )
            session.add_all([n1, n2, n3])
            print("Added 3 notifications")

        await session.commit()
        print("Seed demo data completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed_demo())
