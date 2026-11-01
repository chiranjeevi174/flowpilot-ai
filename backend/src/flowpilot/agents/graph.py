"""LangGraph multi-agent workflow definition with conditional routing and durable checkpointer."""

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from flowpilot.agents.approval import approval_gate_node
from flowpilot.agents.executor import execute_plan_node
from flowpilot.agents.intent import analyze_intent_node
from flowpilot.agents.planner import plan_workflow_node
from flowpilot.agents.state import AgentState
from flowpilot.agents.verifier import verify_execution_node

# ==============================================================================
# Conditional Routing Functions
# ==============================================================================


def route_after_intent(state: AgentState) -> Literal["planner", "__end__"]:
    """Determine routing after intent analysis."""
    if state.get("execution_status") == "failed":
        return "__end__"
    return "planner"


def route_after_planner(state: AgentState) -> Literal["approval_gate", "__end__"]:
    """Determine routing after planning."""
    if state.get("execution_status") == "failed":
        return "__end__"
    return "approval_gate"


def route_after_approval(state: AgentState) -> Literal["executor", "__end__"]:
    """Determine routing after approval evaluation."""
    if state.get("approval_status") == "rejected" or state.get("execution_status") == "rejected":
        return "__end__"
    return "executor"


def route_after_executor(
    state: AgentState,
) -> Literal["approval_gate", "executor", "verifier", "__end__"]:
    """Determine routing after execution."""
    if state.get("execution_status") in ("failed", "rejected"):
        return "__end__"

    executed = set(state.get("executed_step_ids") or [])
    plan = state.get("execution_plan") or []
    unexecuted = [s for s in plan if s.get("step_id") not in executed]

    if unexecuted:
        from flowpilot.workflows.tools import is_operation_sensitive

        next_step = unexecuted[0]
        if next_step.get("approval_required") or is_operation_sensitive(
            next_step.get("operation", ""), next_step.get("parameters")
        ):
            return "approval_gate"
        return "executor"

    return "verifier"


def route_after_verifier(state: AgentState) -> Literal["executor", "__end__"]:
    """Determine routing after verification (bounded correction loop)."""
    # If verifier requested correction and attempts have not been exhausted, loop back to executor
    # ONLY if no sensitive external actions have already been dispatched.
    if state.get("execution_status") == "running":
        step_results = state.get("step_results") or []
        for r in step_results:
            if (
                r.get("operation")
                in ("gmail_send_email", "slack_send_message", "whatsapp_send_message")
                and r.get("status") == "success"
            ):
                return "__end__"
        return "executor"
    return "__end__"


# ==============================================================================
# Graph Construction Factory
# ==============================================================================


def create_agent_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Construct and compile the FlowPilot multi-agent StateGraph.

    Args:
        checkpointer: Optional checkpointer instance (e.g. AsyncPostgresSaver or MemorySaver).

    Returns:
        CompiledStateGraph ready for execution.
    """
    workflow = StateGraph(AgentState)

    # 1. Register specialized agent nodes
    workflow.add_node("intent_analyzer", analyze_intent_node)
    workflow.add_node("planner", plan_workflow_node)
    workflow.add_node("approval_gate", approval_gate_node)
    workflow.add_node("executor", execute_plan_node)
    workflow.add_node("verifier", verify_execution_node)

    # 2. Register deterministic and conditional edges
    workflow.add_edge(START, "intent_analyzer")

    workflow.add_conditional_edges(
        "intent_analyzer",
        route_after_intent,
        {
            "planner": "planner",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "approval_gate": "approval_gate",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "executor": "executor",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "approval_gate": "approval_gate",
            "executor": "executor",
            "verifier": "verifier",
            "__end__": END,
        },
    )

    workflow.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {
            "executor": "executor",
            "__end__": END,
        },
    )

    return workflow.compile(checkpointer=checkpointer)
