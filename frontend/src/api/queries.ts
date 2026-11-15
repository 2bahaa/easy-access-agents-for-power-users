import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { AgentWrite, ProviderConnectionWrite, Role, SkillWrite } from "./types";

export const keys = {
  health: ["health"] as const,
  agents: ["agents"] as const,
  agent: (id: string) => ["agents", id] as const,
  skills: ["skills"] as const,
  skill: (id: string) => ["skills", id] as const,
  tools: ["tools"] as const,
  providers: ["providers"] as const,
  models: (provider: string) => ["providers", provider, "models"] as const,
  allConversations: ["conversations", "all"] as const,
  conversations: (agentId: string) => ["conversations", { agentId }] as const,
  conversation: (id: string) => ["conversation", id] as const,
  runEvents: (runId: string) => ["runs", runId, "events"] as const,
  members: ["members"] as const,
  apiKeys: ["api-keys"] as const,
  audit: ["audit"] as const,
  workspaces: ["workspaces"] as const,
};

export const useHealth = () =>
  useQuery({ queryKey: keys.health, queryFn: api.health, refetchInterval: 15_000, retry: false });

export const useAgents = () => useQuery({ queryKey: keys.agents, queryFn: api.listAgents });

export const useAgent = (id: string | undefined) =>
  useQuery({ queryKey: keys.agent(id ?? ""), queryFn: () => api.getAgent(id!), enabled: !!id });

export const useSkills = () => useQuery({ queryKey: keys.skills, queryFn: api.listSkills });

export const useSkill = (id: string | undefined) =>
  useQuery({ queryKey: keys.skill(id ?? ""), queryFn: () => api.getSkill(id!), enabled: !!id });

export const useTools = () =>
  useQuery({ queryKey: keys.tools, queryFn: api.listTools, staleTime: Infinity });

export const useModels = (provider: string, enabled = true) =>
  useQuery({
    queryKey: keys.models(provider),
    queryFn: () => api.listModels(provider),
    staleTime: 30_000,
    retry: false,
    enabled: enabled && !!provider,
  });

export const useProviders = () =>
  useQuery({ queryKey: keys.providers, queryFn: api.listProviders, staleTime: 15_000 });

function useProviderMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.providers }),
  });
}

export const useCreateProvider = () =>
  useProviderMutation((data: ProviderConnectionWrite) => api.createProvider(data));
export const useUpdateProvider = () =>
  useProviderMutation(({ id, data }: { id: string; data: ProviderConnectionWrite }) => api.updateProvider(id, data));
export const useDeleteProvider = () => useProviderMutation((id: string) => api.deleteProvider(id));
export const useTestProvider = () => useProviderMutation((name: string) => api.testProvider(name));

export function useSetModelTools(provider: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ model, supportsTools }: { model: string; supportsTools: boolean | null }) =>
      api.setModelTools(provider, model, supportsTools),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.models(provider) }),
  });
}

export function useProbeModel(provider: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (model: string) => api.probeModel(provider, model),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.models(provider) }),
  });
}

export function useSaveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id?: string; data: AgentWrite }) =>
      id ? api.updateAgent(id, data) : api.createAgent(data),
    onSuccess: (agent) => {
      qc.setQueryData(keys.agent(agent.id), agent);
      void qc.invalidateQueries({ queryKey: keys.agents, exact: true });
    },
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteAgent,
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.agent(id) });
      void qc.invalidateQueries({ queryKey: keys.agents, exact: true });
    },
  });
}

export function useSaveSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id?: string; data: SkillWrite }) =>
      id ? api.updateSkill(id, data) : api.createSkill(data),
    onSuccess: (skill) => {
      qc.setQueryData(keys.skill(skill.id), skill);
      void qc.invalidateQueries({ queryKey: keys.skills, exact: true });
      // Agents embed skill names.
      void qc.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteSkill,
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.skill(id) });
      void qc.invalidateQueries({ queryKey: keys.skills, exact: true });
      void qc.invalidateQueries({ queryKey: keys.agents });
    },
  });
}

/** Most recent conversations across all agents (Overview, command palette). */
export const useAllConversations = () =>
  useQuery({ queryKey: keys.allConversations, queryFn: api.listAllConversations });

export const useConversations = (agentId: string | undefined) =>
  useQuery({
    queryKey: keys.conversations(agentId ?? ""),
    queryFn: () => api.listConversations(agentId!),
    enabled: !!agentId,
  });

export const useConversation = (id: string | undefined) =>
  useQuery({
    queryKey: keys.conversation(id ?? ""),
    queryFn: () => api.getConversation(id!),
    enabled: !!id,
  });

/** Persisted timeline of a finished run (immutable once the run has ended). */
export const useRunEvents = (runId: string | undefined, enabled = true) =>
  useQuery({
    queryKey: keys.runEvents(runId ?? ""),
    queryFn: () => api.listRunEvents(runId!),
    enabled: !!runId && enabled,
    staleTime: Infinity,
  });

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createConversation,
    onSuccess: (conversation) => {
      void qc.invalidateQueries({ queryKey: keys.conversations(conversation.agent_id) });
    },
  });
}

export function useDeleteConversation(agentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteConversation,
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: keys.conversation(id) });
      void qc.invalidateQueries({ queryKey: keys.conversations(agentId) });
    },
  });
}

// ---- organization ----

export const useMembers = (enabled = true) =>
  useQuery({ queryKey: keys.members, queryFn: api.listMembers, enabled });

export const useApiKeys = () => useQuery({ queryKey: keys.apiKeys, queryFn: api.listApiKeys });

export const useAudit = (enabled = true) =>
  useQuery({ queryKey: keys.audit, queryFn: () => api.listAudit(), enabled });

export function useAddMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: Role }) => api.addMember(email, role),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.members }),
  });
}

export function useUpdateMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) => api.updateMember(userId, role),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.members }),
  });
}

export function useRemoveMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => api.removeMember(userId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.members }),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; role: Exclude<Role, "owner">; expiresInDays: number | null }) =>
      api.createApiKey(v.name, v.role, v.expiresInDays),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.apiKeys }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.revokeApiKey(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.apiKeys }),
  });
}

export function useCreateWorkspace() {
  return useMutation({ mutationFn: (name: string) => api.createWorkspace(name) });
}
