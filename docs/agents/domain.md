# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root, if it exists.
- **`docs/designs/level-1/decisions-log.md`**: this repo's decisions are its `| D<n> |` rows, not files under
  `docs/adr/`. Read the rows that touch the area you're about to work in, and cite them as `D<n>`.
- **`docs/designs/environment-standard.md`**: the design those decisions shape.

If `GLOSSARY.md` doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The
`/domain-modeling` skill creates it lazily when terms actually get resolved.

## File structure

Single-context repo:

```text
/
├── GLOSSARY.md                        (created when terms get resolved)
└── docs/designs/
    ├── environment-standard.md        the design
    └── level-1/decisions-log.md       the decisions (D-rows)
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the
term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project
doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag decision conflicts

If your output contradicts a decision, surface it explicitly rather than silently overriding:

> _Contradicts D155 (zero-touch container logins), but worth reopening because…_
