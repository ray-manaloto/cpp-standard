# Stage 8: Intermediate Zoom Out

**Target:** `docs/designs/environment-standard.md` (2309 lines). It was 1813
lines at the Stage 5 re-audit.

**Reviewer:** `egm-zoom-out`.

**Inputs:**

- `zoom_out_report.md` and `zoom_out_reaudit_report.md`;
- the GoldfishContext.

**Verdict:** 0 Blockers, 8 Majors and 5 Nits.

D119-D133 fixed real bugs. Taken together, though, they moved the design
away from simple, and the M2 trust model is out of proportion for one
owner with a 2026-11-27 deadline:

- **Trust roots:** the list grew from about 5 paths to about 25, plus about
  15 named M2 gate items.
- **Owner bottleneck:** that brings back the bottleneck D101 rejected.
- **M1a:** it picked up machinery that existing checks already make
  redundant.

The main move is to defer the M2 trust work, not to refine it further.

## Findings

- **Z8-1 (Major):** the trust roots now cover most of the owned roots. From
  M2, most agent PRs would wait for the owner. Fix: keep D108's short list
  plus `publish.yml` and `gate-removals.toml`. Move D123, D125, D129, D132,
  D133 and the M2 entry-gate list into an M2 backlog, to be written when M2
  starts (after 2026-11-27).
- **Z8-2 (Major):** the D129 "named items" are new, undesigned mechanisms.
  Fix: move them to the M2 backlog.
- **Z8-3 (Major):** `publish.yml` now runs the shared hash script, so it
  runs repository code. This reopens R1. Fix: drop the tip-hash recompute
  (D132) and the shared script (D133). Provenance comes from a `main`
  builder run.
- **Z8-4 (Major):** since D130, the agent App no longer needs
  `actions: write`. Fix: remove it, and collapse the anti-replay checks to
  one event and ref check.
- **Z8-5 (Major):** the release lookup grew: pagination, decoys, the
  lowest-version pick, draft clean-up and concurrency. Fix: in M1a, make the
  release tag the artifact tag and fetch it with
  `GET /releases/tags/<tag>`. Defer D89's versioning to M2.
- **Z8-6 (Major):** D126's `docker load` path is unproven and sits on the
  M1a path. Fix: go back to `pr-` GHCR tags, guarded by `image:verify`.
  Defer the workflows allowlist. Make rows 2142 and 2245 match.
- **Z8-7 (Major):** the meta-gate machinery: the checker runs from `main`'s
  copy, the `owned-roots.txt` diff, single-use entries. Fix: run
  `must-fail` on every PR and keep only the `gate-removals.toml` ratchet.
- **Z8-8 (Major):** the document grew by about 500 lines. Fix: after Z8-1,
  move command lines and evidence out, and keep risk rows to one sentence.
  Target: under 1800 lines.
- **Z8-9 to Z8-13 (Nits):**
  - the D133 and Stage 8 status lines;
  - close Q8 and remove the "D107, proposed" markers;
  - setup steps 6 and 9;
  - the trigger list and the `post-merge.yml` double build;
  - the probe copies (Z8).

## Stage 5 status

| Status | Findings |
|---|---|
| Still resolved (11) | Z2, Z7, Z9, Z10, Z11, R2, R3, R4, R5, R10, R11 |
| Regressed (3) | Z3, Z5, R1 |
| Newly affected (4) | Z1, Z4, R6, R7 |
| Partly resolved (2) | Z6, R9 |
| Unresolved (2) | Z8, R8 |

## Status

Resolved by D134. The owner chose "Cut to M2 backlog + simplify M1a".

- **Trust roots:** back to D108's short list. The deferred items are in
  `m2-trust-backlog.md`.
- **M1a simplified:**
  - the release tag is the artifact tag;
  - PR images use `pr-` tags;
  - `publish.yml` runs no repository code;
  - the agent App has no `actions: write`;
  - `must-fail` runs on every PR.
- **Document trimmed** from 2,229 to 1,837 lines.

Not taken:

- Z8-10: Q8 and D107 stay for the owner's exit review on 2026-11-16.
- Z8-13: the probe-copy detail. Stage 9 reviews it with the file plan.

`mise run check` passes.
