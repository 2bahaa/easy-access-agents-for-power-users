import { BookOpen, Bot, Building2, LayoutDashboard, Plug, ShieldCheck, Wrench, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Extra words the command palette matches on. */
  keywords?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Single source for sidebar and command palette navigation. Later phases append items here. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [{ to: "/overview", label: "Overview", icon: LayoutDashboard, keywords: "dashboard home" }],
  },
  {
    label: "Build",
    items: [
      { to: "/agents", label: "Agents", icon: Bot, keywords: "builder assistants" },
      { to: "/skills", label: "Skills", icon: BookOpen, keywords: "prompts markdown" },
      { to: "/tools", label: "Tools", icon: Wrench, keywords: "calculator file reader" },
    ],
  },
  {
    label: "Run",
    items: [{ to: "/approvals", label: "Approvals", icon: ShieldCheck, keywords: "review human in the loop pending" }],
  },
  {
    label: "Admin",
    items: [
      { to: "/providers", label: "Providers", icon: Plug, keywords: "models llm openai anthropic gemini api keys connections" },
      { to: "/settings", label: "Organization", icon: Building2, keywords: "settings members api keys audit workspaces" },
    ],
  },
];
