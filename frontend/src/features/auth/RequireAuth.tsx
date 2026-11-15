import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { Spinner } from "../../components/ui/Spinner";
import { useAuth } from "./auth-context";

/** Gate for the app shell: signed-out users go to /login and come back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return (
      <div className="grid min-h-screen place-items-center" aria-busy="true">
        <Spinner />
      </div>
    );
  }
  if (status === "anonymous") {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}
