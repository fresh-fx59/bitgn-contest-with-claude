`50_finance/` is the money lane.

- Treat invoices, purchases, and payment-adjacent records as sensitive and auditable.
- Prefer exactness over prose here.
- Some records in this lane are being migrated toward YAML frontmatter. The transition can be uneven for a while, but the long-term goal is cleaner and more uniform record handling. When asked to OCR, normalize, or structure a finance note, preserve the original note body and discover the required frontmatter shape via `99_system/schemas/`.
- Do not infer authorization for financial actions from casual chat alone.
