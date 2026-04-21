`10_entities/cast/` holds the canonical records for people, pets, and named systems in Miles's world.

- Each file is authoritative for relationship, birthday when present, and the basic identity of that entity.
- When present, `primary_contact_email` is the canonical email identity for that entity.
- Prefer these files over chat context, memory summaries, or project mentions when resolving identity.
