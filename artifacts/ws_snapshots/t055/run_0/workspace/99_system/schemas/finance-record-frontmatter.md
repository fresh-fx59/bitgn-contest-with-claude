# Finance record frontmatter

Finance notes are gradually migrating toward YAML frontmatter so they stay readable in Obsidian while exposing structured fields for automation.

When a task asks you to OCR, normalize, or structure a finance note:

- extract visible data from the existing note body into YAML frontmatter
- preserve the existing note body below the frontmatter as the source OCR or human-readable content
- do not invent fields that are not supported by the visible note
- if the visible invoice or bill data does not mention a currency, assume euros for `total_eur`, `unit_eur`, and `line_eur`

## Invoice schema

For invoices, add YAML frontmatter like this:

```yaml
---
record_type: invoice
invoice_number: INV-0017
alias: northstar-renewal
issued_on: 2026-03-10
total_eur: 4200
counterparty: Northstar Forecasting
project: Forecast Recovery Sprint
related_entity: Mila Novak
lines:
  - item: Discovery workshop
    quantity: 2
    unit_eur: 900
    line_eur: 1800
  - item: Model tuning
    quantity: 3
    unit_eur: 800
    line_eur: 2400
---
```

Required invoice fields:

- `record_type`
- `invoice_number`
- `alias`
- `issued_on`
- `total_eur`
- `counterparty`
- `project`
- `lines`

Optional invoice fields:

- `related_entity`

Invoice line rules:

- `lines` is an ordered list and should follow the visible line-item order from the note
- each line item must include:
  - `item`
  - `quantity`
  - `unit_eur`
  - `line_eur`
- `line_eur` should match `quantity * unit_eur`

## Bill schema

For bills, add YAML frontmatter like this:

```yaml
---
record_type: bill
bill_id: bill.hosting-renewal
alias: hosting-renewal
purchased_on: 2026-03-11
total_eur: 320
counterparty: Hetzner
project: Household Infra Cleanup
related_entity: Miles Novak
lines:
  - item: Cloud instance
    quantity: 1
    unit_eur: 200
    line_eur: 200
  - item: Backup storage
    quantity: 2
    unit_eur: 60
    line_eur: 120
---
```

Required bill fields:

- `record_type`
- `bill_id`
- `alias`
- `purchased_on`
- `total_eur`
- `counterparty`
- `project`
- `lines`

Optional bill fields:

- `related_entity`

Bill line rules:

- `lines` is an ordered list and should follow the visible line-item order from the note
- each line item must include:
  - `item`
  - `quantity`
  - `unit_eur`
  - `line_eur`
- `line_eur` should match `quantity * unit_eur`
