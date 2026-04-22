# Fix B — INBOX_GIVEUP nudge extension for collection tasks

Apply to `src/bitgn_contest_agent/verify.py`, replace `_section_inbox_giveup`.

## Imports
`re` is already imported in verify.py; no new imports.

## Replace _section_inbox_giveup (lines 220-239)

```python
_COLLECTION_QUANTIFIER_RE = re.compile(
    r"\b(all|every|each)\b", re.IGNORECASE,
)


def _section_inbox_giveup(task_text: str) -> str:
    base = (
        "## INBOX_GIVEUP\n"
        "You routed as an inbox task, marked outcome "
        "NONE_CLARIFICATION, and did not write any outbox reply. This "
        "usually indicates premature giveup — reconsider before "
        "finalizing:\n"
        "  - Re-read the inbox `from:` header and resolve the sender "
        "via the entity cast directly (aliases, relationship, "
        "primary_contact_email).\n"
        "  - If the task mentions a descriptor (e.g. 'design partner', "
        "'my spouse'), re-check every entity's relationship field — "
        "the descriptor may map semantically to startup_partner, wife, "
        "etc.\n"
        "  - If after that check no entity matches, re-emit "
        "report_completion with outcome OUTCOME_NONE_UNSUPPORTED "
        "(task really has no answer) or OUTCOME_NONE_CLARIFICATION "
        "with a specific clarifying question you couldn't answer from "
        "the workspace."
    )
    if _COLLECTION_QUANTIFIER_RE.search(task_text):
        base += (
            "\n  - This inbox item names a collection (`all`/`every`/"
            "`each`). Do not conclude no evidence exists based on "
            "`search` alone — PCM search is case-sensitive, so "
            "lowercase patterns miss Title-cased entity names, and "
            "descriptor-based references are invisible to substring "
            "match. Instead `list` the lane most likely to hold these "
            "records (e.g. `50_finance/purchases/` for bills, "
            "`30_knowledge/notes/` for notes), then `read` each "
            "candidate and filter by entity name in file content."
        )
    return base
```
