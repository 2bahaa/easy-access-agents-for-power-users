import { createBrowserRouter, Navigate, type RouteObject } from "react-router";

import { AgentEditorPage } from "./features/agents/AgentEditorPage";
import { AgentsPage } from "./features/agents/AgentsPage";
import { ChatPage } from "./features/chat/ChatPage";
import { NotFoundPage } from "./features/NotFoundPage";
import { OverviewPage } from "./features/overview/OverviewPage";
import { SkillsPage } from "./features/skills/SkillsPage";
import { ToolsPage } from "./features/tools/ToolsPage";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { LoginPage, RegisterPage } from "./features/auth/AuthPages";
import { RequireAuth } from "./features/auth/RequireAuth";
import { ProvidersPage } from "./features/providers/ProvidersPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { AppLayout } from "./layout/AppLayout";

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
      { path: "agents", element: <AgentsPage /> },
      { path: "agents/new", element: <AgentEditorPage /> },
      { path: "agents/:agentId", element: <AgentEditorPage /> },
      // One route with an optional segment, so starting a new chat (URL change) does not
      // remount the page and interrupt the stream.
      { path: "agents/:agentId/chat/:conversationId?", element: <ChatPage /> },
      { path: "skills", element: <SkillsPage /> },
      { path: "skills/:skillId", element: <SkillsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "approvals", element: <ApprovalsPage /> },
      { path: "providers", element: <ProvidersPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
