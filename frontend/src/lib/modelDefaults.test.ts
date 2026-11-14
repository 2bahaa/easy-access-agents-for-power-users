import type { ModelInfo } from "../api/types";
import { emptyAgentForm } from "./agentForm";
import { applyAdjustments, LARGE_MODEL_BYTES, modelAdjustments, revertAdjustments } from "./modelDefaults";

const model = (overrides: Partial<ModelInfo>): ModelInfo => ({
  name: "m",
  size: 1_000_000_000,
  supports_tools: true,
  supports_thinking: false,
  ...overrides,
});

const base = { ...emptyAgentForm(), name: "Bot", tools: [{ name: "calculator", config: {} }] };

describe("modelAdjustments", () => {
  it("turns thinking on and raises the timeout for thinking models", () => {
    const changes = modelAdjustments(model({ supports_thinking: true }), base);
    expect(changes.map((c) => [c.field, c.to])).toEqual([
      ["think", true],
      ["runTimeoutS", 300],
    ]);
    expect(changes[1]!.reason).toMatch(/thinking models/);
  });

  it("raises the timeout for large models", () => {
    const changes = modelAdjustments(model({ size: LARGE_MODEL_BYTES }), base);
    expect(changes).toEqual([
      expect.objectContaining({ field: "runTimeoutS", to: 300, reason: expect.stringMatching(/large models/) }),
    ]);
  });

  it("resets thinking for models without a thinking mode", () => {
    const changes = modelAdjustments(model({}), { ...base, think: true });
    expect(changes).toEqual([expect.objectContaining({ field: "think", from: true, to: null })]);
  });

  it("removes tools for models that cannot call tools", () => {
    const changes = modelAdjustments(model({ supports_tools: false }), base);
    expect(changes).toEqual([expect.objectContaining({ field: "tools", to: [] })]);
  });

  it("changes nothing for a small, plain, tool-capable model or an unknown model", () => {
    expect(modelAdjustments(model({}), base)).toEqual([]);
    expect(modelAdjustments(undefined, base)).toEqual([]);
  });

  it("does not lower a timeout that is already at the maximum or repeat applied settings", () => {
    const tuned = { ...base, think: true, runTimeoutS: 300 };
    expect(modelAdjustments(model({ supports_thinking: true }), tuned)).toEqual([]);
  });

  it("applies and reverts exactly the changed fields", () => {
    const changes = modelAdjustments(model({ supports_thinking: true, supports_tools: false }), base);
    const applied = applyAdjustments(base, changes);
    expect(applied).toMatchObject({ think: true, runTimeoutS: 300, tools: [] });
    expect(applied.name).toBe("Bot");
    expect(revertAdjustments(applied, changes)).toEqual(base);
  });
});
