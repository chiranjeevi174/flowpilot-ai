import type { Metadata } from "next";
import { WorkflowsClient } from "./workflows-client";

export const metadata: Metadata = {
  title: "New Workflow Execution | FlowPilot AI",
  description:
    "Describe what you want the multi-agent system to accomplish in natural language. Intent, planning, and verification agents will coordinate execution.",
};

export default function WorkflowsPage() {
  return <WorkflowsClient />;
}
