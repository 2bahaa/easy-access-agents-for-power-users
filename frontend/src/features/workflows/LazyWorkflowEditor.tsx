import { lazy, Suspense } from "react";

import { Spinner } from "../../components/ui/Spinner";

// The canvas editor pulls in React Flow: load it only when a workflow is opened.
const WorkflowEditorPage = lazy(() =>
  import("./WorkflowEditorPage").then((m) => ({ default: m.WorkflowEditorPage })),
);

export function LazyWorkflowEditor() {
  return (
    <Suspense fallback={<Spinner />}>
      <WorkflowEditorPage />
    </Suspense>
  );
}
