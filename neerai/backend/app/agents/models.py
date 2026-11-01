"""Model providers for the Strands agents.

- BedrockModel (Amazon Nova Pro by default) for AWS mode.
- ScriptedModel for offline demo/test mode: a real `strands.models.Model` implementation whose "decisions" come from a
  deterministic policy. The Strands event loop, tool registry, tool execution, hooks and agent-to-agent delegation all
  run for real; only the language model is replaced, so the demo works without AWS credentials.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable

from strands.models import Model

from ..core.config import Settings


@dataclass
class Call:
    tool: str
    input: dict


@dataclass
class Say:
    text: str


# policy(n_tool_calls_so_far, last_tool_result_text) -> Call | Say
Policy = Callable[[int, str], "Call | Say"]


def _count_tool_calls(messages: list[dict]) -> int:
    return sum(1 for m in messages for b in m.get("content", []) if isinstance(b, dict) and "toolUse" in b)


def _last_tool_result(messages: list[dict]) -> str:
    for m in reversed(messages):
        for b in m.get("content", []):
            if isinstance(b, dict) and "toolResult" in b:
                return " ".join(c.get("text", "") for c in b["toolResult"].get("content", []) if isinstance(c, dict))
    return ""


class ScriptedModel(Model):
    """Deterministic stand-in for an LLM that emits genuine tool-use / text events to the Strands event loop."""

    def __init__(self, policy: Policy, name: str = "neerai-scripted"):
        self.policy = policy
        self.config = {"model_id": name}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError("ScriptedModel does not implement structured_output; results are captured from tools")
        yield  # noqa

    async def stream(self, messages, tool_specs=None, system_prompt=None, *, tool_choice=None, **kwargs) -> AsyncGenerator[dict, None]:
        step = self.policy(_count_tool_calls(messages), _last_tool_result(messages))
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, Call):
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"tooluse_{uuid.uuid4().hex[:12]}", "name": step.tool}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(step.input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": step.text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}, "metrics": {"latencyMs": 0}}}


def bedrock_model(settings: Settings) -> Model:
    """Amazon Bedrock model via Strands. Credentials come from the default boto3 chain (IAM role / profile)."""
    from botocore.config import Config
    from strands.models import BedrockModel

    return BedrockModel(
        model_id=settings.bedrock_model_id,
        region_name=settings.bedrock_region,
        temperature=settings.bedrock_temperature,
        boto_client_config=Config(
            read_timeout=int(settings.agent_timeout_s), connect_timeout=5,
            retries={"max_attempts": settings.bedrock_max_attempts, "mode": "standard"},  # exponential backoff + jitter
        ),
    )
