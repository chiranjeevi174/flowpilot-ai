// ==============================================================================
// FlowPilot AI — TypeScript Type Definitions
// ==============================================================================

// --- User & Auth Types ---
export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

// --- Agent Run & Workflow Types ---
export type AgentRunStatus =
  | "pending"
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface PlanStep {
  step_id: string;
  operation: string;
  parameters: Record<string, any>;
  required_capability: string;
  approval_required: boolean;
  expected_outcome: string;
}

export interface DetectedIntent {
  intent: string;
  action: string;
  requires_clarification?: boolean;
  is_actionable?: boolean;
  parameters?: Record<string, any>;
  clarification_message?: string | null;
}

export interface AgentRun {
  id: string;
  user_id: string;
  thread_id: string;
  original_request: string;
  status: AgentRunStatus;
  current_step: number;
  detected_intent: DetectedIntent | null;
  execution_plan: PlanStep[] | null;
  final_result: any | null;
  error_message: string | null;
  location?: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface AgentRunListResponse {
  items: AgentRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface AgentEvent {
  id: string;
  run_id: string;
  agent_name: string;
  event_type: string;
  event_payload: Record<string, any>;
  timestamp: string;
}

// --- Multi-LLM BYOK Types ---
export interface LLMProvider {
  id: string;
  name: string;
  description: string;
}

export interface LLMCredential {
  id: string;
  provider: string;
  key_fingerprint: string;
  created_at: string;
  updated_at: string;
  last_validated_at: string | null;
}

export interface LLMPreference {
  id: string;
  credential_id: string;
  provider: string;
  model_id: string;
  updated_at: string;
}

export interface LLMModelInfo {
  id: string;
  name: string;
  provider?: string;
  description?: string;
  context_length?: number;
  context_window?: number;
  supports_tools?: boolean;
}

export interface LLMUsageRecord {
  id: string;
  provider: string;
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost: number | null;
  currency: string | null;
  status: string;
  latency_ms: number;
  created_at: string;
}

// --- Integrations & OAuth Types ---
export interface IntegrationProvider {
  id: string;
  name: string;
  category: string;
  supported_services: string[];
  supported_scopes: string[];
  is_configured: boolean;
  auth_type?: "oauth2" | "system_credentials";
  missing_fields?: string[];
}

export interface WhatsAppStatus {
  is_configured: boolean;
  phone_number_id_configured: boolean;
  masked_phone_number_id: string | null;
  business_account_id_configured: boolean;
  masked_business_account_id: string | null;
  graph_api_version: string;
  webhook_verify_token_configured: boolean;
  app_secret_configured: boolean;
  missing_fields: string[];
  supported_capabilities: string[];
}


export interface IntegrationConnection {
  id: string;
  user_id: string;
  provider: string;
  service: string | null;
  external_account_id: string | null;
  external_account_name: string | null;
  granted_scopes: string[];
  token_expires_at: string | null;
  status: "active" | "expired" | "revoked" | "error";
  last_verified_at: string | null;
  metadata_json: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ExternalAction {
  id: string;
  user_id: string;
  run_id: string | null;
  connection_id: string | null;
  operation: string;
  parameter_digest: string;
  idempotency_key: string;
  status: "executing" | "succeeded" | "failed";
  approval_reference: string | null;
  provider_action_id: string | null;
  provider_response: Record<string, any>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

// --- Workflow Scheduling Types ---
export type ScheduleType = "one_time" | "daily" | "weekly";

export interface ScheduledWorkflow {
  id: string;
  user_id: string;
  name: string;
  workflow_request: string;
  schedule_type: ScheduleType;
  timezone: string;
  schedule_configuration: Record<string, any>;
  is_active: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
  latest_run_id?: string | null;
  latest_run_status?: string | null;
}

// --- Notification Types ---
export type NotificationType =
  | "schedule_countdown"
  | "workflow_started"
  | "approval_required"
  | "system";

export type NotificationCategory = "schedule" | "approval" | "system" | "general";

export interface AppNotification {
  id: string;
  user_id: string;
  type: NotificationType;
  category: NotificationCategory;
  title: string;
  message: string;
  link_url?: string | null;
  meta_data: Record<string, any>;
  dedup_key: string;
  is_read: boolean;
  is_dismissed: boolean;
  created_at: string;
  updated_at: string;
}

// --- Monitoring & Diagnostics Types ---
export interface MonitoringHealth {
  database_connected: boolean;
  redis_connected: boolean;
  celery_queue_depth: number;
  runs_by_status: Record<string, number>;
  total_runs: number;
  active_schedules: number;
  average_duration_seconds: number | null;
  failed_outbox_count: number;
  pending_outbox_count: number;
  provider_failure_rates?: Record<string, number>;
  timestamp: string;
}

// --- App Connections Types ---
export type AppConnectionStatus =
  | "not_configured"
  | "credentials_saved"
  | "configuration_incomplete"
  | "authorization_required"
  | "connected"
  | "token_expired"
  | "error"
  | "restricted";

export interface AppConnectionOverviewItem {
  id: string; // 'gmail' | 'sheets' | 'slack' | 'whatsapp'
  name: string;
  category: string;
  icon: string;
  description: string;
  status: AppConnectionStatus;
  connection_id: string | null;
  connected_account: string | null;
  config_method: string | null;
  is_default: boolean;
  has_credentials: boolean;
  has_access_token: boolean;
  client_id?: string | null;
  client_id_preview: string | null;
  has_client_secret?: boolean;
  phone_number_id?: string | null;
  business_account_id?: string | null;
  graph_api_version?: string | null;
  has_app_secret?: boolean;
  last_verified_at: string | null;
  updated_at?: string | null;
  supported_methods: string[];
  platform_oauth_available: boolean;
  services: string[];
  callback_url?: string | null;
}

export interface ProviderSetupGuideStep {
  step_number: number;
  title: string;
  instructions: string;
  required_info: string[];
  portal_name: string;
  portal_url: string;
  callback_url?: string | null;
  tip?: string | null;
}

export interface RequiredFieldConfig {
  name: string;
  label: string;
  type: "text" | "password";
  placeholder: string;
  is_secret: boolean;
  required: boolean;
  help: string;
}

export interface ProviderSetupGuideResponse {
  provider: string;
  name: string;
  description: string;
  portal_name: string;
  portal_url: string;
  callback_url?: string | null;
  webhook_url?: string | null;
  supported_methods: string[];
  required_fields: RequiredFieldConfig[];
  steps: ProviderSetupGuideStep[];
}

export interface SaveCustomCredentialsRequest {
  provider: string;
  service?: string | null;
  client_id?: string | null;
  client_secret?: string | null;
  access_token?: string | null;
  phone_number_id?: string | null;
  business_account_id?: string | null;
  app_secret?: string | null;
  webhook_verify_token?: string | null;
  graph_api_version?: string;
  is_default?: boolean;
}

