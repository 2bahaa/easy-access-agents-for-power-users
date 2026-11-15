import type { ComponentType } from "react";
import { createBrowserRouter, Navigate, type RouteObject } from "react-router";

import { NotFoundPage } from "./features/NotFoundPage";
import { OverviewPage } from "./features/overview/OverviewPage";
import { LoginPage, RegisterPage } from "./features/auth/AuthPages";
import { LazyWorkflowEditor } from "./features/workflows/LazyWorkflowEditor";
import { RequireAuth } from "./features/auth/RequireAuth";
import { AppLayout } from "./layout/AppLayout";

/** Route-level code splitting: each page loads on first visit. */
function page<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M & string) {
  return async () => ({ Component: (await load())[name] as ComponentType });
}

export const routes: RouteObject[] = [
  { path: "login", element: <LoginPage /> },
  { path: "register", element: <RegisterPage /> },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "agents", lazy: page(() => import("./features/agents/AgentsPage"), "AgentsPage") },
      { path: "agents/new", lazy: page(() => import("./features/agents/AgentEditorPage"), "AgentEditorPage") },
      { path: "agents/:agentId", lazy: page(() => import("./features/agents/AgentEditorPage"), "AgentEditorPage") },
      // One route with an optional segment, so starting a new chat (URL change) does not
      // remount the page and interrupt the stream.
      { path: "agents/:agentId/chat/:conversationId?", lazy: page(() => import("./features/chat/ChatPage"), "ChatPage") },
      { path: "skills", lazy: page(() => import("./features/skills/SkillsPage"), "SkillsPage") },
      { path: "skills/:skillId", lazy: page(() => import("./features/skills/SkillsPage"), "SkillsPage") },
      { path: "tools", lazy: page(() => import("./features/tools/ToolsPage"), "ToolsPage") },
      { path: "approvals", lazy: page(() => import("./features/approvals/ApprovalsPage"), "ApprovalsPage") },
      { path: "runs", lazy: page(() => import("./features/runs/RunsPage"), "RunsPage") },
      { path: "knowledge", lazy: page(() => import("./features/knowledge/KnowledgePage"), "KnowledgePage") },
      { path: "workflows", lazy: page(() => import("./features/workflows/WorkflowsPage"), "WorkflowsPage") },
      { path: "workflows/:workflowId", element: <LazyWorkflowEditor /> },
      { path: "providers", lazy: page(() => import("./features/providers/ProvidersPage"), "ProvidersPage") },
      { path: "settings", lazy: page(() => import("./features/settings/SettingsPage"), "SettingsPage") },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
