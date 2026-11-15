/**
 * @easy-access/agent-ui — the public SDK surface.
 *
 * Everything exported here is prop-driven (no data fetching, no router, no app state), so a
 * host application can render agents, runs, approvals and workflows with its own data layer.
 * `createAgentClient` is an optional transport for talking to an Easy Access Agents API.
 * The Studio itself uses these same components; this file is the boundary that
 * `npm run build:sdk` packages into `packages/agent-ui`.
 */

// Components
export { AgentChat, type AgentChatProps } from "../components/AgentChat";
export {
  AgentRunTimeline,
  type AgentRunTimelineProps,
} from "../components/AgentRunTimeline";
export {
  AgentBuilder,
  type AgentBuilderProps,
} from "../components/AgentBuilder";
export {
  ApprovalCard,
  type ApprovalCardProps,
} from "../components/ApprovalCard";
export { ModelPicker, type ModelPickerProps } from "../components/ModelPicker";
export { ToolPicker, type ToolPickerProps } from "../components/ToolPicker";
export {
  SkillSelector,
  type SkillSelectorProps,
} from "../components/SkillSelector";
export { Markdown } from "../components/Markdown";
export { UsageChart, type UsageChartProps } from "../components/UsageChart";
export { WorkflowEditor } from "../components/workflow/WorkflowEditor";
export type { WorkflowCatalogs } from "../components/workflow/NodeInspector";

// State helpers: turn the event stream into what the components render.
export {
  initialRunState,
  replayRunEvents,
  runReducer,
  type RunState,
  type TimelineItem,
} from "../lib/runReducer";
export {
  buildTranscript,
  liveTranscript,
  type ChatItem,
} from "../lib/transcript";
export {
  initialRunView,
  reduceRunEvent,
  type RunView,
} from "../lib/workflowGraph";
export { emptyAgentForm, fromAgent } from "../lib/agentForm";

// Protocol types (mirror the backend's Pydantic models).
export type * from "../api/events";
export type * from "../api/types";

// Optional transport.
export {
  createAgentClient,
  type AgentClient,
  type AgentClientOptions,
} from "./client";
export { SSEParser, readSSE, type SSEMessage } from "../api/sse";
