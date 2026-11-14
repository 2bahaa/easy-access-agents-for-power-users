import { createContext, useContext } from "react";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: "success" | "error";
}

export const ToastContext = createContext<{ push: (toast: ToastInput) => void }>({
  push: () => undefined,
});

export function useToast() {
  return useContext(ToastContext);
}
