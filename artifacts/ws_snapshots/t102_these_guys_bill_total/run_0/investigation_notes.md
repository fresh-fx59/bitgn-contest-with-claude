# t102 — "these guys" bill total (c352c7a bench)

- **Harness URL**: vm-03osztkstaga7yzu12.eu.bitgn.com
- **Commit**: c352c7a (descriptor-SI fix)
- **Outcome**: OUTCOME_OK but **wrong answer** (expected 241, agent reported 133)
- **Wall time**: ~12 min (agent completed naturally, not a timeout)
- **Total steps**: 12

## Intent
"Doing my accounting cleanup. `2026_02_02__eur_000080__bill__studio_parts_petg_batch.md` looks overpriced. How much did I pay **these guys** in total? Number only"

## What happened
- step 9: read cited bill → saw `counterparty: Filamenthütte Wien`, total_eur=80
- step 10-11: **ignored counterparty**, searched by filename token `studio_parts` (product category) instead
- Found 3 `studio_parts` bills: €80 + €33 + €20 = €133
- Submitted 133. Expected 241. Shortfall €108 = likely 1-2 additional Filamenthütte Wien bills whose filenames don't contain "studio_parts"

## Root cause
Descriptor "these guys" points to **counterparty** of the cited bill, not to its product-tag/category. Agent read the bill, saw the counterparty field, but kept anchoring the search on the filename token.

## Not a timeout / not a descriptor-SI issue
The semantic index only covers cast + projects. Finance counterparty resolution is out of scope. Unrelated to the c352c7a fix.

## Proposed follow-up (separate from t072 timeout fix)
Finance-lane hint: when a task cites a specific bill file, treat its `counterparty:` field as the canonical entity to aggregate by — don't anchor on filename tokens.
