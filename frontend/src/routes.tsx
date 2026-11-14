import { createBrowserRouter, Navigate, type RouteObject } from "react-router";

import { AgentEditorPage } from "./features/agents/AgentEditorPage";
import { AgentsPage } from "./features/agents/AgentsPage";
import { ChatPage } from "./features/chat/ChatPage";
import { NotFoundPage } from "./features/NotFoundPage";
import { SkillsPage } from "./features/skills/SkillsPage";
import { ToolsPage } from "./features/tools/ToolsPage";
import { AppLayout } from "./layout/AppLayout";

export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/agents" replace /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "agents/new", element: <AgentEditorPage /> },
      { path: "agents/:agentId", element: <AgentEditorPage /> },
      // One route with an optional segment, so starting a new chat (URL change) does not
      // remount the page and interrupt the stream.
      { path: "agents/:agentId/chat/:conversationId?", element: <ChatPage /> },
      { path: "skills", element: <SkillsPage /> },
      { path: "skills/:skillId", element: <SkillsPage /> },
      { path: "tools", element: <ToolsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export const createRouter = () => createBrowserRouter(routes);
