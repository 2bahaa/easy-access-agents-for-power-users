import { Compass } from "lucide-react";

import { LinkButton } from "../components/ui/LinkButton";
import { EmptyState } from "../components/ui/States";

export function NotFoundPage() {
  return (
    <EmptyState
      icon={<Compass />}
      title="Page not found"
      description="The page you are looking for does not exist."
      action={<LinkButton to="/agents">Back to agents</LinkButton>}
    />
  );
}
