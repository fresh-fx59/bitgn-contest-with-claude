"""Thin wrapper around the BitGN HarnessService.

Three-step flow:
  1. harness.get_benchmark(...)   → discover task list
  2. harness.start_playground(...) → get trial_id + harness_url (per-task runtime)
  3. harness.end_trial(...)       → submit and receive score

Authentication is a ConnectRPC metadata interceptor (taken from the
sibling bitgn_pac1_adapter.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Tuple

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    GetBenchmarkRequest,
    StartPlaygroundRequest,
)
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
# PLAN DEVIATION: the plan imports MetadataInterceptorSync from
# connectrpc.client_sync, but the installed connectrpc wheel exposes it
# under connectrpc.interceptor. The sibling bitgn_pac1_adapter.py used
# an older path. Verified via pkgutil.iter_modules on 2026-04-10.
from connectrpc.interceptor import MetadataInterceptorSync  # type: ignore[import-not-found]


class _AuthHeaderInterceptor(MetadataInterceptorSync[None]):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def on_start_sync(self, ctx: Any) -> None:  # pragma: no cover — thin glue
        ctx.request_headers()["authorization"] = f"Bearer {self._api_key}"
        return None


@dataclass(frozen=True, slots=True)
class StartedTask:
    trial_id: str
    task_id: str
    benchmark_id: str
    instruction: str
    harness_url: str
    runtime_client: PcmRuntimeClientSync


class BitgnHarness:
    def __init__(
        self,
        *,
        harness_client: HarnessServiceClientSync,
        runtime_client_factory: Callable[[str], PcmRuntimeClientSync],
        benchmark: str,
    ) -> None:
        self._harness = harness_client
        self._runtime_factory = runtime_client_factory
        self._benchmark = benchmark

    @classmethod
    def from_env(cls, *, benchmark: str, bitgn_base_url: str, bitgn_api_key: str) -> "BitgnHarness":
        interceptors = (_AuthHeaderInterceptor(bitgn_api_key),)
        harness_client = HarnessServiceClientSync(bitgn_base_url, interceptors=interceptors)
        return cls(
            harness_client=harness_client,
            runtime_client_factory=lambda url: PcmRuntimeClientSync(url, interceptors=interceptors),
            benchmark=benchmark,
        )

    def list_task_ids(self) -> List[str]:
        resp = self._harness.get_benchmark(GetBenchmarkRequest(benchmark_id=self._benchmark))
        return [t.task_id for t in resp.tasks]

    def start_task(self, task_id: str) -> StartedTask:
        resp = self._harness.start_playground(
            StartPlaygroundRequest(benchmark_id=self._benchmark, task_id=task_id)
        )
        runtime = self._runtime_factory(resp.harness_url)
        return StartedTask(
            trial_id=resp.trial_id,
            task_id=resp.task_id,
            benchmark_id=resp.benchmark_id,
            instruction=resp.instruction,
            harness_url=resp.harness_url,
            runtime_client=runtime,
        )

    def end_task(self, started: StartedTask) -> Tuple[float, list[Any]]:
        resp = self._harness.end_trial(EndTrialRequest(trial_id=started.trial_id))
        return float(resp.score), list(resp.score_detail)
