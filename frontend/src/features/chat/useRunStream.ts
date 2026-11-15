import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { api, errorMessage, followRun, streamMessage } from "../../api/client";
import type { AgentEvent } from "../../api/events";
import { TERMINAL_EVENTS } from "../../api/events";
import { keys } from "../../api/queries";
import { initialRunState, runReducer } from "../../lib/runReducer";

export interface PendingMessage {
  conversationId: string;
  content: string;
}

/**
 * Drives one streamed run at a time: sends the message (or reattaches to a run that is
 * still active on the server), reduces SSE events into run state, and refreshes the
 * persisted conversation when the run ends.
 *
 * Runs are durable on the server: leaving the page only stops following the run. Use
 * `cancel()` to stop it.
 */
export function useRunStream() {
  const queryClient = useQueryClient();
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const [pending, setPending] = useState<PendingMessage | null>(null);
  /** Error that prevented the message from being sent (e.g. 409 run in progress). */
  const [sendError, setSendError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const consume = useCallback(
    async (
      conversationId: string,
      content: string,
      open: (signal: AbortSignal) => AsyncGenerator<AgentEvent>,
      knownRunId: string | null,
    ) => {
      if (abortRef.current) return; // one run at a time
      const controller = new AbortController();
      abortRef.current = controller;
      runIdRef.current = knownRunId;
      setSendError(null);
      setPending({ conversationId, content });
      dispatch({ type: "local.start" });

      let sawTerminal = false;
      try {
        for await (const event of open(controller.signal)) {
          if (event.type === "run.started") runIdRef.current = event.run_id;
          if (TERMINAL_EVENTS.has(event.type)) sawTerminal = true;
          dispatch(event);
        }
        if (!sawTerminal) {
          dispatch({ type: "local.error", message: "The connection closed before the run finished." });
        }
      } catch (error) {
        if (controller.signal.aborted) {
          dispatch({ type: "local.aborted" });
        } else {
          const message = errorMessage(error);
          dispatch({ type: "local.error", message });
          if (!runIdRef.current) setSendError(message);
        }
      } finally {
        abortRef.current = null;
        // Swap the live view for the persisted transcript once it has been refetched.
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: keys.conversation(conversationId) }),
          queryClient.invalidateQueries({ queryKey: ["conversations"] }),
        ]);
        setPending(null);
      }
    },
    [queryClient],
  );

  const start = useCallback(
    (conversationId: string, content: string) =>
      consume(conversationId, content, (signal) => streamMessage(conversationId, content, signal), null),
    [consume],
  );

  /** Reattach to a run that is queued or running on the server (e.g. after a reload). */
  const attach = useCallback(
    (conversationId: string, runId: string, content: string) =>
      consume(conversationId, content, (signal) => followRun(runId, signal), runId),
    [consume],
  );

  const cancel = useCallback(async () => {
    const runId = runIdRef.current;
    if (runId) {
      try {
        await api.cancelRun(runId); // the stream then ends with run.cancelled
        return;
      } catch {
        // Fall through: stop following (the run id is unknown or the request failed).
      }
    }
    abortRef.current?.abort();
  }, []);

  return {
    state,
    pending,
    running: pending !== null,
    sendError,
    clearSendError: () => setSendError(null),
    start,
    attach,
    cancel,
  };
}
