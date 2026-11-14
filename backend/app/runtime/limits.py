"""Effective limits: agent settings clamped to global caps."""

from dataclasses import dataclass

from app.runtime.types import AgentConfig, RuntimeCaps


@dataclass(frozen=True)
class EffectiveLimits:
    max_tool_calls: int
    run_timeout_s: float
    tool_timeout_s: float

    @property
    def recursion_limit(self) -> int:
        # Each tool round is 2 graph steps (agent + tools); +1 final agent step, +2 slack.
        # Hitting this is a backstop; the tool node normally stops the run first.
        return 2 * self.max_tool_calls + 3

    def tool_timeout(self, tool_timeout_s: float | None) -> float:
        return min(tool_timeout_s, self.tool_timeout_s) if tool_timeout_s else self.tool_timeout_s


def effective_limits(config: AgentConfig, caps: RuntimeCaps) -> EffectiveLimits:
    return EffectiveLimits(
        max_tool_calls=max(1, min(config.max_tool_calls, caps.max_tool_calls)),
        run_timeout_s=min(float(config.run_timeout_s), caps.run_timeout_s),
        tool_timeout_s=caps.tool_timeout_s,
    )
