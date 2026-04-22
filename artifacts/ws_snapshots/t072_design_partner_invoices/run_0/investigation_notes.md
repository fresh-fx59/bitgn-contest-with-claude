# t072 — design-partner invoice reply (c352c7a bench)

- **Harness URL**: vm-03osztksn13mc53l2s.eu.bitgn.com
- **Commit**: c352c7a (descriptor-SI fix)
- **Outcome**: OUTCOME_ERR_INTERNAL (terminated_by=cancel, error=cancelled:timeout)
- **Wall time**: 605s (hit client `TASK_TIMEOUT_SEC=600` deadline)
- **Total steps**: 25 (forced-cancel mid-step)

## Intent
"Take care of the next message in inbox" — email requests oldest 3 invoices linked to sender's design partner.

## Timeline
- steps 0-17: identity bootstrap + rulebook loading + cast/project digest scan
- step 20: **Descriptor resolved correctly — "design partner" → Nina (startup_partner)** via semantic index
- step 21: validator R4 flagged name-based finance search → agent pivoted to project-alias lookup
- steps 22-23: found 5 Northstar invoice candidates via project-alias search
- step 24: read 1st invoice, needed 2 more → TIMEOUT hit

## Cost breakdown (prepass)
- preflight_semantic_index: 6.6KB digest, 6421ms wall, ~36 reads
- Total prepass pcm_ops: 215 (tree=2, context=1, list=53, read=159)

## Root cause
Client-side `task_timeout_sec=600` too tight for "read bill → pivot search → attach 3 invoices" flow on top of semantic-index prepass.

## Not a descriptor-resolution regression
Descriptor resolution worked (step 20 shows Nina picked correctly). The task just needed more wall-clock.
