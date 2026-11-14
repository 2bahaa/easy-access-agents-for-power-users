import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { api, errorMessage, streamMessage } from "../../api/client";
import { TERMINAL_EVENTS } from "../../api/events";
import { keys } from "../../api/queries";
import { initialRunState, runReducer } from "../../lib/runReducer";

export interface PendingMessage {
  conversationId: string;
  content: string;
}

/**
 * Drives one streamed run at a time: sends the message, reduces SSE events into run
 * state, and refreshes the persisted conversation when the run ends.
 *
 * Leaving the page aborts the request; the server treats the disconnect as a cancel.
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

  const start = useCallback(
    async (conversationId: string, content: string) => {
      if (abortRef.current) return; // one run at a time
      const controller = new AbortController();
      abortRef.current = controller;
      runIdRef.current = null;
      setSendError(null);
      setPending({ conversationId, content });
      dispatch({ type: "local.start" });

      let sawTerminal = false;
      try {
        for await (const event of streamMessage(conversationId, content, controller.signal)) {
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

  const cancel = useCallback(async () => {
    const runId = runIdRef.current;
    if (runId) {
      try {
        await api.cancelRun(runId); // the stream then ends with run.cancelled
        return;
      } catch {
        // Fall through: closing the connection also cancels the run.
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
    cancel,
  };
}
