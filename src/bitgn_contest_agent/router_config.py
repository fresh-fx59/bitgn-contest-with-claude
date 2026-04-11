"""Router tier-2 classifier configuration.

Resolved in M0 task 3 after probing the cliproxyapi model catalog on
2026-04-12. The env var `BITGN_CLASSIFIER_MODEL` overrides.

Available classifier-sized models in the local cliproxyapi catalog:

    gpt-5.4-mini            (OpenAI, newest — DEFAULT)
    gpt-5.1-codex-mini      (OpenAI)
    gpt-5-codex-mini        (OpenAI)
    claude-haiku-4-5        (Anthropic)
    claude-3-5-haiku        (Anthropic)

`gpt-5.4-mini` is picked as the default because it's (a) the newest
OpenAI mini, (b) provider-consistent with the main-agent model
family (`gpt-5.3-codex`), and (c) cheap enough to run once per task
without meaningfully adding to the per-task latency budget. The
confidence threshold and router-enabled flag are both env-tunable.
"""
from __future__ import annotations

import os

# Filled in from the M0 task 3 probe result. Update this constant when
# the cliproxyapi catalog changes.
DEFAULT_CLASSIFIER_MODEL = "gpt-5.4-mini"

# Confidence threshold below which a classifier response is treated as
# UNKNOWN. Set to 0.6 in the spec §5.3.
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


def classifier_model() -> str:
    return os.environ.get("BITGN_CLASSIFIER_MODEL", DEFAULT_CLASSIFIER_MODEL)


def confidence_threshold() -> float:
    raw = os.environ.get("BITGN_CLASSIFIER_CONFIDENCE_THRESHOLD")
    if raw is None:
        return DEFAULT_CONFIDENCE_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_CONFIDENCE_THRESHOLD


def router_enabled() -> bool:
    return os.environ.get("BITGN_ROUTER_ENABLED", "1") not in ("0", "false", "False")
