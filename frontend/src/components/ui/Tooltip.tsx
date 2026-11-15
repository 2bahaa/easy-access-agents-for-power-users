import * as RadixTooltip from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";

/** Wrap the app once so tooltips share open/close delays. */
export const TooltipProvider = ({ children }: { children: ReactNode }) => (
  <RadixTooltip.Provider delayDuration={300}>{children}</RadixTooltip.Provider>
);

/** Accessible tooltip (hover + keyboard focus). `children` must be a single focusable element. */
export function Tooltip({
  content,
  side = "top",
  children,
}: {
  content: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  children: ReactElement;
}) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className="z-[60] animate-fade-in rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-fg shadow-pop"
        >
          {content}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
