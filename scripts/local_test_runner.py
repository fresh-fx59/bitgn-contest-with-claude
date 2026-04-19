#!/usr/bin/env -S .venv/bin/python3 -u
"""Run agent tasks against local workspace snapshots using the mock PCM.

Tests preflight + routing logic WITHOUT calling PROD or consuming LLM
tokens for the main agent loop. Validates that:
  1. Schema discovery finds all roots correctly
  2. Router classifies the task correctly
  3. Routed preflight returns useful data
  4. Preflight match points to the right files

Usage:
    # Test a specific task from the catalogue
    python scripts/local_test_runner.py \
        --catalogue artifacts/test_cases/eac8b36_full.json \
        --task-id t001

    # Test all tasks that have workspace snapshots
    python scripts/local_test_runner.py \
        --catalogue artifacts/test_cases/eac8b36_full.json \
        --all-with-snapshots

    # Test preflight only (no LLM agent loop)
    python scripts/local_test_runner.py \
        --catalogue artifacts/test_cases/eac8b36_full.json \
        --task-id t001 \
        --preflight-only

    # Test with custom workspace + instruction
    python scripts/local_test_runner.py \
        --workspace artifacts/ws_snapshots/t001/run_0/workspace \
        --instruction "What is the start date of the house AI thing? YYYY-MM-DD"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_pcm import LocalPcmClient


def run_preflight_pipeline(
    workspace_path: str | Path,
    instruction: str,
    context_date: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Run the full preflight pipeline (schema + router + routed_preflight)
    against a local workspace snapshot.

    Returns a dict with all pipeline outputs for verification.
    """
    from bitgn_contest_agent.preflight.schema import discover_schema_from_fs
    from bitgn_contest_agent.router import _get_default_router
    from bitgn_contest_agent.routed_preflight import dispatch_routed_preflight

    client = LocalPcmClient(workspace_path, context_date=context_date)
    router = _get_default_router()

    result: dict[str, Any] = {
        "instruction": instruction,
        "workspace": str(workspace_path),
    }

    # Step 1: Schema discovery
    if verbose:
        print(f"  [1] Schema discovery...")
    schema = discover_schema_from_fs(Path(workspace_path))
    result["schema"] = {
        "entities_root": schema.entities_root,
        "projects_root": schema.projects_root,
        "inbox_root": schema.inbox_root,
        "finance_roots": list(schema.finance_roots) if schema.finance_roots else [],
        "outbox_root": schema.outbox_root,
    }
    if verbose:
        for k, v in result["schema"].items():
            if v:
                print(f"       {k}: {v}")

    # Step 2: Router classification
    if verbose:
        print(f"  [2] Router classification...")
    skills_by_name = router.skills_by_name()
    decision = router.route(instruction)
    result["routing"] = {
        "skill_name": decision.skill_name,
        "source": decision.source,
        "extracted": decision.extracted,
        "task_text": decision.task_text[:100] if decision.task_text else None,
    }
    if verbose:
        print(f"       skill={decision.skill_name} source={decision.source}")

    # Step 3: Routed preflight
    if verbose:
        print(f"  [3] Routed preflight...")

    # Build a minimal adapter that routes to local PCM
    adapter = _LocalPreflightAdapter(client)

    # For preflight_unknown we need a backend — skip it in local mode
    try:
        outcome = dispatch_routed_preflight(
            decision=decision,
            schema=schema,
            adapter=adapter,
            skills_by_name=skills_by_name,
            backend=None,  # No LLM backend for local testing
        )
        result["preflight"] = {
            "tool": outcome.tool,
            "skipped_reason": outcome.skipped_reason,
            "error": outcome.error,
            "has_result": outcome.result is not None,
        }
        if outcome.result:
            result["preflight"]["ok"] = outcome.result.ok
            result["preflight"]["refs"] = list(outcome.result.refs) if outcome.result.refs else []
            # Parse the content JSON
            try:
                content = json.loads(outcome.result.content) if outcome.result.content else {}
                result["preflight"]["summary"] = content.get("summary", "")
                result["preflight"]["data"] = content.get("data", {})
            except (json.JSONDecodeError, TypeError):
                result["preflight"]["content_raw"] = (
                    outcome.result.content[:500] if outcome.result.content else ""
                )
        if verbose:
            print(f"       tool={outcome.tool} skipped={outcome.skipped_reason}")
            if outcome.result and outcome.result.ok:
                try:
                    c = json.loads(outcome.result.content)
                    print(f"       summary: {c.get('summary', '')[:120]}")
                except Exception:
                    pass
    except Exception as e:
        result["preflight"] = {"error": str(e)}
        if verbose:
            print(f"       ERROR: {e}")

    # Step 4: PCM ops log
    result["pcm_ops"] = len(client.ops_log)
    result["reads"] = sorted(client.reads)

    return result


class _LocalPreflightAdapter:
    """Minimal adapter that dispatches preflight requests to the local PCM."""

    def __init__(self, client: LocalPcmClient):
        self._client = client

    def dispatch(self, req: Any) -> Any:
        """Route a preflight request to the appropriate handler."""
        from bitgn_contest_agent.schemas import (
            Req_PreflightFinance,
            Req_PreflightEntity,
            Req_PreflightProject,
            Req_PreflightInbox,
        )

        if isinstance(req, Req_PreflightProject):
            from bitgn_contest_agent.preflight.project import run_preflight_project
            return run_preflight_project(self._client, req)
        elif isinstance(req, Req_PreflightFinance):
            from bitgn_contest_agent.preflight.finance import run_preflight_finance
            return run_preflight_finance(self._client, req)
        elif isinstance(req, Req_PreflightEntity):
            from bitgn_contest_agent.preflight.entity import run_preflight_entity
            return run_preflight_entity(self._client, req)
        elif isinstance(req, Req_PreflightInbox):
            from bitgn_contest_agent.preflight.inbox import run_preflight_inbox
            return run_preflight_inbox(self._client, req)
        else:
            raise ValueError(f"Unknown preflight request type: {type(req)}")


def _verify_against_expected(
    result: dict[str, Any],
    expected: dict[str, Any],
    test_case: dict[str, Any],
) -> list[str]:
    """Check pipeline result against expected test case outcomes."""
    issues: list[str] = []

    # Check schema discovery
    schema = result.get("schema", {})
    if not schema.get("entities_root"):
        issues.append("schema: entities_root not discovered")
    if not schema.get("projects_root"):
        issues.append("schema: projects_root not discovered")
    if not schema.get("finance_roots"):
        issues.append("schema: finance_roots not discovered")

    # Check routing matches expected skill
    expected_skill = test_case.get("skill")
    actual_skill = result.get("routing", {}).get("skill_name")
    if expected_skill and actual_skill != expected_skill:
        issues.append(f"routing: expected skill={expected_skill}, got {actual_skill}")

    # Check preflight found expected files
    preflight = result.get("preflight", {})
    exp = test_case.get("expected", {})
    if exp.get("missing_refs"):
        refs = preflight.get("refs", [])
        for missing in exp["missing_refs"]:
            if not any(missing in r for r in refs):
                issues.append(f"preflight: expected ref to {missing}, not in refs")

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Local preflight test runner")
    parser.add_argument("--catalogue", help="Test case catalogue JSON")
    parser.add_argument("--task-id", help="Specific task ID to test")
    parser.add_argument("--all-with-snapshots", action="store_true",
                        help="Test all tasks with workspace snapshots")
    parser.add_argument("--workspace", help="Direct workspace path")
    parser.add_argument("--instruction", help="Task instruction text")
    parser.add_argument("--context-date", help="Override context date (ISO format)")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Only test preflight pipeline, no agent loop")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.workspace and args.instruction:
        # Direct mode
        result = run_preflight_pipeline(
            args.workspace,
            args.instruction,
            context_date=args.context_date,
            verbose=not args.quiet,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    if not args.catalogue:
        parser.error("--catalogue is required unless using --workspace + --instruction")

    catalogue = json.load(open(args.catalogue))
    cases = catalogue["test_cases"]

    if args.task_id:
        cases = [c for c in cases if c["task_id"] == args.task_id]
        if not cases:
            print(f"ERROR: task {args.task_id} not found in catalogue", file=sys.stderr)
            sys.exit(1)
    elif args.all_with_snapshots:
        cases = [c for c in cases if c["has_snapshot"]]
    else:
        parser.error("Specify --task-id, --all-with-snapshots, or --workspace + --instruction")

    print(f"Testing {len(cases)} tasks\n")

    passed = 0
    failed = 0
    errors = 0

    for tc in cases:
        tid = tc["task_id"]
        intent = tc["intent"]
        snap = tc.get("snapshot_path")

        if not snap or not Path(snap).exists():
            print(f"  {tid}: SKIP (no snapshot)")
            continue

        print(f"  {tid}: {intent[:70]}...")
        try:
            result = run_preflight_pipeline(
                snap,
                intent,
                verbose=not args.quiet,
            )
            issues = _verify_against_expected(result, tc.get("expected", {}), tc)
            if issues:
                failed += 1
                for issue in issues:
                    print(f"    ISSUE: {issue}")
            else:
                passed += 1
                if not args.quiet:
                    print(f"    OK")
        except Exception as e:
            errors += 1
            print(f"    ERROR: {e}")
        print()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {errors} errors")


if __name__ == "__main__":
    main()
