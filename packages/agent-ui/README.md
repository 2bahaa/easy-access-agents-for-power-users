# @easy-access/agent-ui

Themeable, prop-driven React components for Easy Access Agents. They render chats, run timelines, approvals, agent configuration, usage and workflows. They contain no data fetching, router or global state, so a host app supplies the data. An optional `createAgentClient` covers hosts that want a ready-made transport.

## Build

The package is built from the Studio sources (one source of truth, so the Studio and the SDK cannot drift apart):

```bash
cd frontend
npm run build:sdk       # → packages/agent-ui/dist (ESM, styles.css, .d.ts)
npm run example:sdk     # example host app against the built package (http://127.0.0.1:5175)
```

## Use

```tsx
import "@easy-access/agent-ui/styles.css";
import { AgentChat, AgentRunTimeline, createAgentClient, initialRunState, liveTranscript, runReducer } from "@easy-access/agent-ui";

const client = createAgentClient({ baseUrl: "https://agents.example.com/api", getToken: () => apiKey });
// for await (const event of client.sendMessage(conversationId, text)) dispatch(event);
```

`frontend/examples/host-app/main.tsx` is a complete chat with a live timeline in about 80 lines.

| Export | Purpose |
|---|---|
| `AgentChat`, `AgentRunTimeline`, `ApprovalCard` | Streaming chat, step-by-step run trace, approve/reject card |
| `AgentBuilder`, `ModelPicker`, `ToolPicker`, `SkillSelector` | Agent configuration UI |
| `WorkflowEditor` | Drag-and-drop workflow canvas (needs `@xyflow/react` and `@dagrejs/dagre`) |
| `UsageChart`, `Markdown` | Daily usage bars; safe Markdown rendering |
| `runReducer`, `replayRunEvents`, `liveTranscript`, `buildTranscript`, `reduceRunEvent` | Turn the SSE event stream or stored events into component props |
| `createAgentClient` | Fetch-based client: conversations, streamed messages, run follow/cancel, approvals, workflow runs |
| Types | The `AgentEvent` union and API types, mirroring the backend's Pydantic models |

**Peer dependencies:** `react` and `react-dom` 19, `lucide-react`, `@xyflow/react`, `@dagrejs/dagre`.

**Theming:** override the `--color-*` CSS variables (`--color-surface`, `--color-brand-500`, …) and add or remove `dark` on `<html>` for dark mode.

**Security:** API keys (`eaa_…`) carry the permissions of the user who created them. Use them from server-side code or a backend proxy, never ship them to browsers. In browsers, use a user's short-lived access token through `getToken`.
