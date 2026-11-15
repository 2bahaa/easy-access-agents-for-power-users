import { diffAgentConfigs } from "./configDiff";

describe("diffAgentConfigs", () => {
  const base = {
    name: "A",
    model: "qwen3:4b",
    model_params: { temperature: 0.2 },
    system_prompt: "Be exact.",
    skill_ids: ["s1"],
    tools: [{ name: "calculator", config: {} }],
  };

  it("reports changed fields with readable labels", () => {
    const changes = diffAgentConfigs(base, { ...base, system_prompt: "Be brief.", model: "llama3.2:1b" });
    expect(changes.map((c) => c.label)).toEqual(["Model", "Instructions"]);
    expect(changes[1]).toMatchObject({ before: "Be exact.", after: "Be brief." });
  });

  it("treats null and missing model params as equal", () => {
    const withNulls = { ...base, model_params: { temperature: 0.2, num_ctx: null, think: null } };
    expect(diffAgentConfigs(base, withNulls as never)).toEqual([]);
  });

  it("detects tool and skill changes", () => {
    const changes = diffAgentConfigs(base, { ...base, skill_ids: [], tools: [] });
    expect(changes.map((c) => c.field)).toEqual(["skill_ids", "tools"]);
  });
});
