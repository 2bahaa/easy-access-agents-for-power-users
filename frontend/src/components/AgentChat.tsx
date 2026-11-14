import {
  AlertTriangle,
  ArrowUp,
  Ban,
  Check,
  ChevronRight,
  Copy,
  Info,
  Loader2,
  Sparkles,
  Square,
  XCircle,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { prettyToolName } from "../lib/tools";
import type { ChatItem } from "../lib/transcript";
import { Markdown } from "./Markdown";
import { ToolIcon } from "./ToolIcon";

export interface AgentChatProps {
  items: ChatItem[];
  /** Assistant text currently streaming; null when no run is in progress. */
  draft: string | null;
  running: boolean;
  onSend: (content: string) => void;
  onCancel: () => void;
  agentName: string;
  /** Rendered as the assistant's avatar. */
  avatar?: ReactNode;
  suggestions?: string[];
  onSelectRun?: (runId: string) => void;
  selectedRunId?: string | null;
  /** Shown above the composer (e.g. a send error). */
  error?: string | null;
  disabledReason?: string;
  loading?: boolean;
}

/** Streaming chat transcript with inline tool calls and a composer. Prop-driven. */
export function AgentChat({
  items,
  draft,
  running,
  onSend,
  onCancel,
  agentName,
  avatar,
  suggestions = [],
  onSelectRun,
  selectedRunId,
  error,
  disabledReason,
  loading,
}: AgentChatProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [items, draft]);

  const empty = items.length === 0 && draft === null && !loading;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6"
        aria-live="polite"
      >
        {empty ? (
          <EmptyChat agentName={agentName} suggestions={suggestions} onPick={onSend} disabled={!!disabledReason || running} />
        ) : (
          <ol aria-label="Messages" className="mx-auto flex max-w-3xl flex-col gap-4">
            {items.map((item) => (
              <li key={item.id}>
                <ChatRow
                  item={item}
                  avatar={avatar}
                  agentName={agentName}
                  onSelectRun={onSelectRun}
                  selected={!!item.runId && item.runId === selectedRunId}
                />
              </li>
            ))}
            {draft !== null && (
              <li>
                <AssistantBubble avatar={avatar} agentName={agentName} streaming>
                  {draft ? (
                    <Markdown text={draft} />
                  ) : (
                    <span className="flex items-center gap-1 py-1" aria-label="Agent is thinking">
                      <Dot delay="0ms" />
                      <Dot delay="150ms" />
                      <Dot delay="300ms" />
                    </span>
                  )}
                </AssistantBubble>
              </li>
            )}
          </ol>
        )}
      </div>
      <Composer
        running={running}
        onSend={onSend}
        onCancel={onCancel}
        error={error}
        disabledReason={disabledReason}
        agentName={agentName}
      />
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return <span className="size-1.5 animate-bounce rounded-full bg-subtle" style={{ animationDelay: delay }} />;
}

function EmptyChat({
  agentName,
  suggestions,
  onPick,
  disabled,
}: {
  agentName: string;
  suggestions: string[];
  onPick: (s: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center text-center">
      <div className="relative mb-5">
        <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-brand-500 to-accent-500 opacity-30 blur-2xl" />
        <div className="relative grid size-16 place-items-center rounded-3xl bg-gradient-to-br from-brand-500 to-accent-500 text-white shadow-lg shadow-brand-500/30">
          <Sparkles className="size-7" />
        </div>
      </div>
      <h2 className="text-xl font-semibold tracking-tight">Chat with {agentName}</h2>
      <p className="mt-1.5 text-sm text-muted">
        Responses stream live. Tool calls appear inline and in the run timeline.
      </p>
      {suggestions.length > 0 && (
        <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              disabled={disabled}
              onClick={() => onPick(s)}
              className="rounded-xl border border-line bg-surface px-3.5 py-3 text-left text-sm text-muted shadow-card transition-all hover:-translate-y-0.5 hover:border-brand-500/40 hover:text-fg disabled:opacity-50"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ChatRow({
  item,
  avatar,
  agentName,
  onSelectRun,
  selected,
}: {
  item: ChatItem;
  avatar?: ReactNode;
  agentName: string;
  onSelectRun?: (runId: string) => void;
  selected: boolean;
}) {
  switch (item.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-brand-500 to-accent-500 px-4 py-2.5 text-[14.5px] leading-relaxed whitespace-pre-wrap text-white shadow-md shadow-brand-500/20">
            {item.content}
          </div>
        </div>
      );
    case "assistant":
      return (
        <AssistantBubble avatar={avatar} agentName={agentName} copyText={item.content}>
          <Markdown text={item.content} />
        </AssistantBubble>
      );
    case "tool":
      return <ToolChip item={item} onSelectRun={onSelectRun} selected={selected} />;
    case "notice":
      return <Notice item={item} />;
  }
}

function AssistantBubble({
  avatar,
  agentName,
  streaming,
  copyText,
  children,
}: {
  avatar?: ReactNode;
  agentName: string;
  streaming?: boolean;
  copyText?: string;
  children: ReactNode;
}) {
  return (
    <div className="group flex gap-3">
      <div className="mt-0.5 shrink-0" aria-hidden="true">
        {avatar}
      </div>
      <div className="min-w-0 flex-1">
        <p className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
          {agentName}
          {streaming && <Loader2 className="size-3 animate-spin text-brand-500" aria-label="Streaming" />}
          {copyText && <CopyButton text={copyText} />}
        </p>
        <div className="rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3 shadow-card">
          {children}
        </div>
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);
  return (
    <button
      type="button"
      aria-label="Copy message"
      onClick={() => void navigator.clipboard?.writeText(text).then(() => setCopied(true))}
      className="ml-auto rounded-md p-1 text-subtle opacity-0 transition-opacity group-hover:opacity-100 hover:bg-surface-2 hover:text-fg focus-visible:opacity-100"
    >
      {copied ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
    </button>
  );
}

function ToolChip({
  item,
  onSelectRun,
  selected,
}: {
  item: Extract<ChatItem, { kind: "tool" }>;
  onSelectRun?: (runId: string) => void;
  selected: boolean;
}) {
  const argText = Object.values(item.args).map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ");
  const clickable = !!onSelectRun && !!item.runId;
  return (
    <div className="flex justify-start pl-11">
      <button
        type="button"
        disabled={!clickable}
        onClick={() => item.runId && onSelectRun?.(item.runId)}
        aria-label={`${prettyToolName(item.tool)} tool call, ${item.status}`}
        className={cn(
          "group/chip flex max-w-full items-center gap-2 rounded-xl border px-3 py-1.5 text-left text-xs transition-colors",
          item.status === "failed"
            ? "border-red-500/30 bg-red-500/5"
            : item.status === "running"
              ? "border-brand-500/30 bg-brand-500/5"
              : "border-line bg-surface-2/60",
          clickable && "hover:border-brand-500/40",
          selected && "ring-2 ring-brand-500/25",
        )}
      >
        <span
          className={cn(
            "grid size-5 shrink-0 place-items-center rounded-md",
            item.status === "failed" ? "text-red-500" : item.status === "running" ? "text-brand-500" : "text-emerald-600 dark:text-emerald-400",
          )}
        >
          {item.status === "running" ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : item.status === "failed" ? (
            <XCircle className="size-3.5" />
          ) : (
            <ToolIcon name={item.tool} className="size-3.5" />
          )}
        </span>
        <span className="font-medium">{prettyToolName(item.tool)}</span>
        {argText && <span className="max-w-[16rem] truncate font-mono text-muted">{argText}</span>}
        {item.status !== "running" && item.result !== undefined && (
          <>
            <ChevronRight className="size-3 shrink-0 text-subtle" />
            <span
              className={cn(
                "max-w-[14rem] truncate font-mono",
                item.status === "failed" ? "text-red-600 dark:text-red-400" : "text-fg",
              )}
            >
              {item.result.replace(/^Error:\s*/, "")}
            </span>
          </>
        )}
      </button>
    </div>
  );
}

function Notice({ item }: { item: Extract<ChatItem, { kind: "notice" }> }) {
  const styles = {
    info: { icon: <Ban className="size-3.5" />, cls: "border-line bg-surface-2/60 text-muted" },
    warning: { icon: <AlertTriangle className="size-3.5" />, cls: "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300" },
    error: { icon: <XCircle className="size-3.5" />, cls: "border-red-500/25 bg-red-500/5 text-red-700 dark:text-red-300" },
  }[item.tone];
  return (
    <div className="flex justify-center">
      <p role={item.tone === "error" ? "alert" : "status"} className={cn("flex items-center gap-2 rounded-full border px-3 py-1 text-xs", styles.cls)}>
        {styles.icon}
        {item.text}
      </p>
    </div>
  );
}

function Composer({
  running,
  onSend,
  onCancel,
  error,
  disabledReason,
  agentName,
}: {
  running: boolean;
  onSend: (content: string) => void;
  onCancel: () => void;
  error?: string | null;
  disabledReason?: string;
  agentName: string;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const send = () => {
    const content = value.trim();
    if (!content || running || disabledReason) return;
    onSend(content);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="border-t border-line bg-surface/80 px-4 pt-3 pb-4 backdrop-blur sm:px-6">
      <div className="mx-auto max-w-3xl">
        {(error || disabledReason) && (
          <p
            role="alert"
            className={cn(
              "mb-2 flex items-center gap-2 rounded-lg px-3 py-2 text-xs",
              error ? "bg-red-500/10 text-red-700 dark:text-red-300" : "bg-amber-500/10 text-amber-800 dark:text-amber-300",
            )}
          >
            {error ? <XCircle className="size-3.5 shrink-0" /> : <Info className="size-3.5 shrink-0" />}
            {error ?? disabledReason}
          </p>
        )}
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-surface p-2 shadow-card transition-colors focus-within:border-brand-500 focus-within:ring-4 focus-within:ring-brand-500/15">
          <textarea
            ref={ref}
            rows={1}
            value={value}
            aria-label={`Message ${agentName}`}
            placeholder={`Message ${agentName}…`}
            disabled={!!disabledReason}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            className="scrollbar-thin max-h-[200px] min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[14.5px] leading-relaxed placeholder:text-subtle focus:outline-none disabled:cursor-not-allowed"
          />
          {running ? (
            <button
              type="button"
              onClick={onCancel}
              aria-label="Stop generating"
              title="Stop"
              className="grid size-10 shrink-0 place-items-center rounded-xl bg-fg text-canvas transition-opacity hover:opacity-85"
            >
              <Square className="size-3.5 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              onClick={send}
              disabled={!value.trim() || !!disabledReason}
              aria-label="Send message"
              title="Send (Enter)"
              className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 text-white shadow-sm shadow-brand-500/30 transition-all hover:brightness-110 disabled:opacity-40 disabled:shadow-none"
            >
              <ArrowUp className="size-4" />
            </button>
          )}
        </div>
        <p className="mt-1.5 text-center text-[11px] text-subtle">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </div>
  );
}
