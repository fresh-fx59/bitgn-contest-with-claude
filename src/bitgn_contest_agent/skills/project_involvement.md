---
name: project-involvement
description: Strategy for finding project attributes or membership
type: rigid
category: project_involvement
matcher_patterns:
  - '(?i)start\s+date\b.*\b(project|for\s+(?:the\s+)?(?:project\s+)?\w)'
  - '(?i)\bproject\b.*\bstart\s+date\b'
classifier_hint: "Tasks asking about project attributes (start date, members, status), which projects a person is involved in, or any project-related queries — even if the project name sounds financial or like another domain"
---

## Step 0: Classify the query

**Before using preflight data**, determine what the task is actually
asking:

- **"Which projects is X involved in?"** → This is an ENTITY→PROJECTS
  query. X is a person, device, or system — NOT a project name.
  **IGNORE preflight project matches entirely.** Preflight tries to
  match X as a project name and will give you wrong project candidates.
  Go directly to Step 1 (entity resolution).

- **"What is the start date of project X?"** → This is a PROJECT
  ATTRIBUTE query. Preflight project matches ARE useful here. Read the
  matched file and extract the date.

- **Other project queries** → Use preflight data if it returned a
  useful match; fall through to search strategy if not.

**CRITICAL grounding rule:** You MUST `read` every file you reference
in your answer. The grader checks that referenced files appear in your
tool-call history.

## Step 1: Entity Resolution (for "which projects" queries)

The subject of "which projects is X involved in" is ALWAYS an entity
(person, device, system), never a project. If preflight returned an
entity match, use it. Otherwise resolve manually:

1. Search cast files by name, alias, and relationship field.
2. **Colloquial household/personal descriptors** — when the task uses
   a bare, possessive English descriptor with NO qualifier word in
   front of it ("my partner", "my spouse", "my kid", "my mom"),
   resolve it as the colloquial-English *role*, not as a substring
   search on the `relationship` field. In the cast, the matching
   canonical relationships are:
   - `my partner` / `my spouse` / `my significant other` / `my other half`
     → `wife` **or** `husband` (the spouse). Do **NOT** match
     `startup_partner`, `business_partner`, `design_partner`,
     `cofounder`, or any `*_partner` compound — those describe
     business roles, not a romantic partner.
   - `my kid` / `my child` → `daughter` **or** `son` (disambiguate by
     context if both exist; otherwise sum both).
   - `my mom` / `my mother` → `mother`; `my dad` / `my father` → `father`;
     `my wife` → `wife`; `my husband` → `husband`.
   - `my boss` / `my CEO` → `day_job_ceo` or equivalent employment role.
   - `my client` → `consulting_client` or equivalent.
   - `my advisor` → `startup_advisor` or equivalent.

   Rule of thumb: if the descriptor is bare ("my partner") the user
   means the intuitive personal-life referent (spouse). If the
   descriptor is qualified ("my **startup** partner", "my **business**
   partner", "my **design** partner"), THEN follow the compound rule
   in step 3 below.

3. **Qualified compound descriptors** (e.g. "startup partner", "design
   partner", "business partner"): the qualifier tells you which
   `*_partner` compound relationship to match. Split into qualifier
   (e.g. "startup") + relationship type ("partner"). Find entities
   whose relationship is exactly `<qualifier>_<type>` (e.g.
   `startup_partner`). If multiple match, use invoice/project
   filenames for the qualifier — e.g. `*_design_partner_*` in finance
   records disambiguates which entity is the "design" partner.

From the resolved entity, extract the `alias` field — this is the
canonical identifier you will search projects with.

## Step 2: Search Projects by Entity Identifier

Once you have the canonical entity alias (e.g. `juniper`, `nina`):

1. Use `search` with pattern `entity.{alias}` across the projects
   directory. This finds ALL projects that link this entity.
2. Do NOT search by name keywords in prose — structured `entity.X`
   references are the reliable lookup key.
3. Read EVERY matching project README to extract the exact project
   title. Do not stop at the first match.

## Step 3: Compile and Verify

1. Collect ALL project titles from Step 2.
2. **Verification check**: Does the count seem reasonable? If you found
   only 1 project for an entity, consider whether you searched broadly
   enough. Re-search if needed.
3. Sort alphabetically and return the complete list.
4. If zero projects found after exhaustive entity-identifier search,
   report OUTCOME_NONE_CLARIFICATION.
