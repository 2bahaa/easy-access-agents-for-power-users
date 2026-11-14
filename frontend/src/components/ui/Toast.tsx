import { CheckCircle2, X, XCircle } from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { ToastContext, type ToastInput } from "./toast-context";

interface ToastItem extends ToastInput {
  id: number;
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((items) => items.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (toast: ToastInput) => {
      const id = nextId++;
      setToasts((items) => [...items.slice(-3), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), toast.tone === "error" ? 6000 : 3500);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className="pointer-events-auto flex animate-slide-up items-start gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-pop"
          >
            {t.tone === "error" ? (
              <XCircle className="mt-0.5 size-4 shrink-0 text-red-500" />
            ) : (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
            )}
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-medium">{t.title}</p>
              {t.description && (
                <p className={cn("mt-0.5 text-muted", t.tone === "error" && "break-words")}>
                  {t.description}
                </p>
              )}
            </div>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => dismiss(t.id)}
              className="rounded-md p-0.5 text-subtle hover:bg-surface-2 hover:text-fg"
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
