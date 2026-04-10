"""OpenAI-compatible backend (routes through cliproxyapi by default).

Two code paths:
- Structured output via client.beta.chat.completions.parse(response_format=NextStep)
- Manual-parse fallback via client.chat.completions.create + json_object mode

The agent's P3 pattern (validation retry with critique) covers any
ValidationError raised in the fallback path, so the fallback is not a
correctness risk.
"""
from __future__ import annotations

from typing import Sequence

import openai
from openai import OpenAI
from pydantic import ValidationError

from bitgn_contest_agent.backend.base import Backend, Message, TransientBackendError
from bitgn_contest_agent.schemas import NextStep


_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class OpenAIChatBackend(Backend):
    def __init__(
        self,
        *,
        client: OpenAI,
        model: str,
        reasoning_effort: str,
        use_structured_output: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._use_structured_output = use_structured_output

    @classmethod
    def from_config(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        reasoning_effort: str,
    ) -> "OpenAIChatBackend":
        client = OpenAI(base_url=base_url, api_key=api_key)
        return cls(
            client=client,
            model=model,
            reasoning_effort=reasoning_effort,
            use_structured_output=True,
        )

    def next_step(
        self,
        messages: Sequence[Message],
        response_schema: type[NextStep],
        timeout_sec: float,
    ) -> NextStep:
        payload = [{"role": m.role, "content": m.content} for m in messages]
        try:
            if self._use_structured_output:
                completion = self._client.beta.chat.completions.parse(
                    model=self._model,
                    messages=payload,
                    response_format=response_schema,
                    timeout=timeout_sec,
                    extra_body={"reasoning": {"effort": self._reasoning_effort}},
                )
                parsed = completion.choices[0].message.parsed
                if parsed is None:
                    # Structured output mode returned no parsed value — fall
                    # back to parsing the raw content. Raises ValidationError
                    # on bad JSON, caught by the agent loop's P3 path.
                    raw = completion.choices[0].message.content or ""
                    parsed = response_schema.model_validate_json(raw)
                return parsed
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=payload,
                response_format={"type": "json_object"},
                timeout=timeout_sec,
                extra_body={"reasoning": {"effort": self._reasoning_effort}},
            )
            raw = completion.choices[0].message.content or ""
            return response_schema.model_validate_json(raw)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBackendError(str(exc)) from exc
        except ValidationError:
            # Caller handles via P3 critique-injection retry.
            raise
