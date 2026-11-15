import { teamSpec } from "./teamTemplates";

const AGENTS = [
  { id: "a1", name: "Researcher" },
  { id: "a2", name: "Writer" },
];

describe("team templates", () => {
  it("builds a supervisor team with named members", () => {
    const spec = teamSpec("supervisor", AGENTS);
    const team = spec.nodes.find((n) => n.type === "supervisor")!;
    expect(team.config.members).toEqual([
      { name: "researcher", agent_id: "a1", role: "Researcher" },
      { name: "writer", agent_id: "a2", role: "Writer" },
    ]);
    expect(spec.edges.map((e) => `${e.source}>${e.target}`)).toEqual(["start>team", "team>end"]);
  });

  it("chains a sequential pipeline", () => {
    const spec = teamSpec("sequential", AGENTS);
    expect(spec.edges.map((e) => `${e.source}>${e.target}`)).toEqual(["start>agent_1", "agent_1>agent_2", "agent_2>end"]);
    expect(spec.nodes.find((n) => n.id === "agent_2")!.config.prompt).toBe("{{ agent_1 }}");
  });

  it("fans out in parallel and aggregates", () => {
    const spec = teamSpec("parallel", AGENTS);
    expect(spec.edges.filter((e) => e.target === "merge").map((e) => e.source)).toEqual(["agent_1", "agent_2"]);
    expect(String(spec.nodes.find((n) => n.id === "merge")!.config.prompt)).toContain("{{ agent_2 }}");
  });
});
