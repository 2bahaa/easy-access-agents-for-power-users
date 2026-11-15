import type { AgentEvent } from "../api/events";
import type { WorkflowSpec } from "../api/types";
import { autoLayout, flowToSpec, initialRunView, nextNodeId, outputHandles, reduceRunEvent, specToFlow } from "./workflowGraph";

const SPEC: WorkflowSpec = {
  schema_version: 1,
  nodes: [
    { id: "start", type: "start", label: "Start", config: { inputs: [] }, position: { x: 0, y: 0 } },
    { id: "c", type: "condition", label: "", config: { expression: "true" }, position: { x: 200, y: 0 } },
    { id: "end", type: "end", label: "", config: { output: "" }, position: { x: 400, y: 0 } },
  ],
  edges: [
    { source: "start", target: "c", source_handle: null },
    { source: "c", target: "end", source_handle: "true" },
  ],
};

describe("workflow graph helpers", () => {
  it("round-trips a spec through the canvas representation", () => {
    const { nodes, edges } = specToFlow(SPEC);
    expect(edges[1]).toMatchObject({ sourceHandle: "true", label: "true" });
    expect(flowToSpec(nodes, edges)).toEqual(SPEC);
  });

  it("names new nodes uniquely and readably", () => {
    expect(nextNodeId("llm", ["start"])).toBe("llm");
    expect(nextNodeId("llm", ["llm", "llm_2"])).toBe("llm_3");
    expect(nextNodeId("start", [])).toBe("start_2");
  });

  it("knows each node's branches", () => {
    expect(outputHandles("condition", {})).toEqual(["true", "false"]);
    expect(outputHandles("router", { routes: ["q", "", "c"] })).toEqual(["q", "c"]);
    expect(outputHandles("end", {})).toEqual([]);
    expect(outputHandles("llm", {})).toEqual(["out"]);
  });

  it("lays nodes out left to right", () => {
    const { nodes, edges } = specToFlow({ ...SPEC, nodes: SPEC.nodes.map((n) => ({ ...n, position: { x: 0, y: 0 } })) });
    const laid = autoLayout(nodes, edges);
    const x = Object.fromEntries(laid.map((n) => [n.id, n.position.x]));
    expect(x.start!).toBeLessThan(x.c!);
    expect(x.c!).toBeLessThan(x.end!);
  });

  it("reduces run events into node statuses", () => {
    const base = { run_id: "r", ts: "" };
    const events = [
      { type: "run.started", seq: 1, agent_id: null, model: null, ...base },
      { type: "node.started", seq: 2, node_id: "c", node_type: "condition", label: "Check", ...base },
      { type: "node.completed", seq: 3, node_id: "c", output: "true", duration_ms: 3, ...base },
      { type: "node.failed", seq: 4, node_id: "end", error: "boom", ...base },
      { type: "run.failed", seq: 5, code: "node_failed", message: "boom", ...base },
    ] as unknown as AgentEvent[];
    const view = events.reduce(reduceRunEvent, initialRunView);
    expect(view.status).toBe("failed");
    expect(view.nodes.c).toMatchObject({ status: "completed", output: "true" });
    expect(view.nodes.end).toMatchObject({ status: "failed", error: "boom" });
    expect(view.log.map((l) => l.tone)).toEqual(["info", "info", "success", "error", "error"]);
  });
});
