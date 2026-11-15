/**
 * Minimal host application for @easy-access/agent-ui: chats with one agent through
 * `createAgentClient` and renders the transcript and the live run timeline.
 *
 *   VITE_EAA_API=http://127.0.0.1:8001/api VITE_EAA_KEY=eaa_… VITE_EAA_AGENT=<agent id> npm run example:sdk
 *
 * Use an API key created under Organization → API keys. Keep keys server-side in production;
 * this example reads one from the environment for local testing only.
 */
import "@easy-access/agent-ui/styles.css";

import {
  AgentChat,
  AgentRunTimeline,
  buildTranscript,
  createAgentClient,
  initialRunState,
  liveTranscript,
  runReducer,
  type ChatItem,
} from "@easy-access/agent-ui";
import { StrictMode, useReducer, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

const client = createAgentClient({
  baseUrl: import.meta.env.VITE_EAA_API ?? "http://127.0.0.1:8001/api",
  getToken: () => import.meta.env.VITE_EAA_KEY ?? null,
});
const AGENT_ID: string = import.meta.env.VITE_EAA_AGENT ?? "";

export function App() {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const [history, setHistory] = useState<ChatItem[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const conversation = useRef<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const send = async (content: string) => {
    setError(null);
    setPending(content);
    abort.current = new AbortController();
    try {
      conversation.current ??= (await client.createConversation(AGENT_ID)).id;
      dispatch({ type: "local.start" });
      for await (const event of client.sendMessage(
        conversation.current,
        content,
        abort.current.signal,
      )) {
        dispatch(event);
      }
      const full = await client.getConversation(conversation.current);
      setHistory(buildTranscript(full.messages, full.runs));
    } catch (e) {
      if (!abort.current.signal.aborted) setError(String(e));
    } finally {
      setPending(null);
    }
  };

  const running = state.status === "streaming";
  const items = running
    ? [...history, ...liveTranscript(state, pending)]
    : history;
  return (
    <div className="grid h-screen grid-cols-[1fr_380px] bg-canvas text-fg">
      <AgentChat
        items={items}
        draft={running ? state.draft : null}
        running={running}
        onSend={(c) => void send(c)}
        onCancel={() => abort.current?.abort()}
        agentName="Assistant"
        error={error}
        disabledReason={
          AGENT_ID ? undefined : "Set VITE_EAA_AGENT to an agent id"
        }
      />
      <aside className="overflow-y-auto border-l border-line bg-surface p-4">
        <AgentRunTimeline
          items={state.items}
          status={state.status}
          emptyText="Send a message to see the run."
        />
      </aside>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
