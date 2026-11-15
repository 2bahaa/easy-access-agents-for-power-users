import { agent } from "../test/fixtures";
import { emptyAgentForm, fromAgent, toAgentWrite, validateAgentForm } from "./agentForm";

describe("agent form mapping", () => {
  it("round-trips an agent into the write payload", () => {
    const write = toAgentWrite(fromAgent(agent));
    expect(write).toEqual({
      name: "Research Assistant",
      description: "Reads my notes",
      provider: "ollama",
      connection_id: null, // built-in Ollama
      model: "qwen3:4b",
      model_params: { temperature: 0.3, num_ctx: 8192 }, // null think is omitted
      system_prompt: "Be careful.",
      skill_ids: ["s-cite"],
      tools: [{ name: "file_reader", config: { subdir: "notes" } }],
      max_tool_calls: 6,
      run_timeout_s: 90,
    });
  });

  it("never sends Ollama-only parameters to other providers", () => {
    const write = toAgentWrite({
      ...fromAgent(agent),
      provider: "openai",
      connectionId: "conn-1",
      maxTokens: 512,
    });
    expect(write.connection_id).toBe("conn-1");
    expect(write.model_params).toEqual({ temperature: 0.3, max_tokens: 512 });
  });

  it("validates max output tokens", () => {
    const values = { ...fromAgent(agent), maxTokens: 0 };
    expect(validateAgentForm(values).maxTokens).toMatch(/whole number/);
    expect(validateAgentForm({ ...values, maxTokens: 1024 }).maxTokens).toBeUndefined();
  });

  it("only blocks tools when the model is known not to support them", () => {
    const values = { ...fromAgent(agent), tools: [{ name: "calculator", config: {} }] };
    expect(validateAgentForm(values, { modelSupportsTools: false }).tools).toBeDefined();
    expect(validateAgentForm(values, { modelSupportsTools: null }).tools).toBeUndefined();
  });

  it("omits model params left at the model default and trims text", () => {
    const write = toAgentWrite({ ...emptyAgentForm(), name: "  Bot  ", model: " qwen3:4b " });
    expect(write.model_params).toEqual({});
    expect(write.name).toBe("Bot");
    expect(write.model).toBe("qwen3:4b");
  });

  it("does not share tool config objects with the source agent", () => {
    const values = fromAgent(agent);
    values.tools[0]!.config.subdir = "changed";
    expect(agent.tools[0]!.config.subdir).toBe("notes");
  });
});

describe("validateAgentForm", () => {
  const valid = { ...emptyAgentForm(), name: "Bot", model: "qwen3:4b" };

  it("accepts a valid form", () => {
    expect(validateAgentForm(valid)).toEqual({});
  });

  it("requires a name and a model", () => {
    const errors = validateAgentForm({ ...valid, name: " ", model: "" });
    expect(errors.name).toMatch(/name/i);
    expect(errors.model).toMatch(/model/i);
  });

  it.each([
    ["maxToolCalls", 0],
    ["maxToolCalls", 21],
    ["maxToolCalls", 2.5],
    ["maxToolCalls", Number.NaN],
    ["runTimeoutS", 4],
    ["runTimeoutS", 301],
  ] as const)("rejects %s = %s", (field, value) => {
    expect(validateAgentForm({ ...valid, [field]: value })[field]).toBeDefined();
  });

  it("rejects out-of-range temperature", () => {
    expect(validateAgentForm({ ...valid, temperature: 2.5 }).temperature).toBeDefined();
  });

  it("blocks tools on a model without tool support", () => {
    const withTools = { ...valid, tools: [{ name: "calculator", config: {} }] };
    expect(validateAgentForm(withTools, { modelSupportsTools: false }).tools).toBeDefined();
    expect(validateAgentForm(withTools, { modelSupportsTools: true }).tools).toBeUndefined();
    // Unknown capability (model list unavailable) is left to the backend.
    expect(validateAgentForm(withTools).tools).toBeUndefined();
  });
});
