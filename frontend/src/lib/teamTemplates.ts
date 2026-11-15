import type { WorkflowNodeSpec, WorkflowSpec } from "../api/types";

export type TeamPattern = "supervisor" | "sequential" | "parallel";

export const TEAM_PATTERNS: Array<{ id: TeamPattern; name: string; description: string; min: number }> = [
  { id: "supervisor", name: "Supervisor team", description: "A coordinator delegates tasks to the members and writes the answer.", min: 1 },
  { id: "sequential", name: "Sequential pipeline", description: "Each agent works on the previous agent's output.", min: 2 },
  { id: "parallel", name: "Parallel specialists", description: "All agents work at once; a model merges their answers.", min: 2 },
];

interface TeamAgent {
  id: string;
  name: string;
}

const memberName = (name: string, i: number) => {
  const base = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return /^[a-z]/.test(base) ? base.slice(0, 32) : `member${i + 1}`;
};

/** A valid, runnable workflow implementing a multi-agent pattern with the chosen agents. */
export function teamSpec(pattern: TeamPattern, agents: TeamAgent[], model = "qwen3:4b"): WorkflowSpec {
  const start: WorkflowNodeSpec = { id: "start", type: "start", label: "Task", config: { inputs: [{ name: "task", description: "" }] }, position: { x: 0, y: 0 } };
  const end = (output: string, x: number): WorkflowNodeSpec => ({ id: "end", type: "end", label: "Result", config: { output }, position: { x, y: 0 } });

  if (pattern === "supervisor") {
    const seen = new Set<string>();
    const members = agents.map((a, i) => {
      let name = memberName(a.name, i);
      while (seen.has(name)) name = `${name}_${i + 1}`;
      seen.add(name);
      return { name, agent_id: a.id, role: a.name };
    });
    return {
      schema_version: 1,
      nodes: [
        start,
        { id: "team", type: "supervisor", label: "Supervisor", config: { provider: "ollama", model, instructions: "", task: "{{ input.task }}", members, max_delegations: Math.min(20, members.length * 2), share_task_with_members: false }, position: { x: 260, y: 0 } },
        end("{{ team }}", 520),
      ],
      edges: [
        { source: "start", target: "team", source_handle: null },
        { source: "team", target: "end", source_handle: null },
      ],
    };
  }

  const steps: WorkflowNodeSpec[] = agents.map((a, i) => ({
    id: `agent_${i + 1}`,
    type: "agent",
    label: a.name,
    config: { agent_id: a.id, prompt: pattern === "sequential" && i > 0 ? `{{ agent_${i} }}` : "{{ input.task }}", use_draft: false },
    position: pattern === "sequential" ? { x: 260 * (i + 1), y: 0 } : { x: 260, y: i * 140 },
  }));

  if (pattern === "sequential") {
    const ids = ["start", ...steps.map((s) => s.id), "end"];
    return {
      schema_version: 1,
      nodes: [start, ...steps, end(`{{ ${steps.at(-1)!.id} }}`, 260 * (steps.length + 1))],
      edges: ids.slice(1).map((target, i) => ({ source: ids[i]!, target, source_handle: null })),
    };
  }

  const answers = steps.map((s) => `${s.label}:\n{{ ${s.id} }}`).join("\n\n");
  return {
    schema_version: 1,
    nodes: [
      start,
      ...steps,
      { id: "merge", type: "llm", label: "Aggregate", config: { provider: "ollama", model, system: "Combine the specialists' answers into one consistent answer.", prompt: `Task: {{ input.task }}\n\n${answers}` }, position: { x: 520, y: 0 } },
      end("{{ merge }}", 780),
    ],
    edges: [
      ...steps.map((s) => ({ source: "start", target: s.id, source_handle: null })),
      ...steps.map((s) => ({ source: s.id, target: "merge", source_handle: null })),
      { source: "merge", target: "end", source_handle: null },
    ],
  };
}
