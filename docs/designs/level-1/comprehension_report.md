# Stage 6: Comprehension Test

* **Target:** `docs/designs/environment-standard.md` (990 lines; FeatureRange 1-819, DetailedRange 820-989)
* **Date:** 2026-11-13
* **Reviewer:** `egm-comprehension`, in a fresh context, given the design only and no other files
* **Result:** both parts could be paraphrased, so there is no Blocker. 13 Major, 11 Nit.

## What this proposes

The design sets up a new public repository, cpp-standard. It holds:
- a written C++ environment standard;
- a small reference project using C++20 modules and `import std`;
- a FIX-style field encoder of about 100 lines, written with C++26 reflection;
- a daily canary that builds upstream reflection libraries;
- one mise configuration that builds three environments: a Tart macOS VM,
  and Ubuntu 26.10 images for arm64 and amd64.

Three compilers each have a fixed role: clang 23, GCC 16.2 and clang-p2996.
Images, and the two toolchains that no package manager can pin, are tagged by
a hash of their input files. One builder builds each of them once and
publishes it to GHCR.

Every environment runs one gate, `mise run ci`:
- **Tier 1** covers build, tests, 100% coverage per compiler, sanitizers,
  Valgrind, format, tidy, hardening and SARIF.
- It also compares configure-time probes with a committed capability lock.
- Must-fail fixtures prove that each check is live.

Unreviewed code runs only on GitHub-hosted runners, and the owner's PC and
Mac run only reviewed `main` code. Five things keep agents from colliding and
the environment from drifting:
- owner-reviewed "owned roots";
- a merge queue;
- daily Renovate updates;
- rule-based automerge;
- a daily digest that uses no model.

Level 1 ends on 2026-11-27, with a Linux-first critical path and a fixed cut
order.

## How the existing system works, per this document

Today nothing is the single source of truth:
- Build presets were written four times, in the private prototype, glaze build-setup, cpp-core
  and the cpp-utilities catalogue.
- The compiler source keeps switching between Homebrew, conda and apt.
- Several agent sessions edit the same repositories and dotfiles at once.
- dotfiles has 66,000 lines, and only about a quarter of them are bootstrap.
- Rulings are not enforced.

As a result, glaze FIX is stuck at the step that turns FIX Orchestra XML into
C++ structs.

Some prior pieces are reused by copying them with a link back:
- the inputs-hash pattern;
- `ProfileCheck.cmake`;
- the vcpkg triplets;
- the p2996 macOS build.

Everything else is parked.

## Findings

| # | Severity | Range | What is unclear | Suggested fix |
|---|---|---|---|---|
| C1 | 🟡 Major | 113, 288, 301-304, 368-370, 687-694, 856, 900 | M0 sub-check letters ("M0 (b)", "M0 c", "M0 a") are never defined. "M0 a" doesn't match the first bullet, and M0 itself is explained only at 687. | Define M0 at first use. Letter the list (a)-(g) and use those letters everywhere. |
| C2 | 🟡 Major | 316-320, 419-422, 570, 583-585 | It's unclear who may use the `publish` Environment ("main and builder runs", but the builder runs on PRs too). The diagram says "main-only". Weak point 9 says a PR can grant itself `packages: write` anyway. | Say whether PR builder runs may publish. Separate Environment secrets from the GITHUB_TOKEN `packages: write` permission. Say which one is fenced and which one D54 accepts as a risk. |
| C3 | 🟡 Major | 103, 518-519, 586-599 | "Owned code" (the coverage target) clashes with "owned roots" (the paths the owner reviews). It's unclear whether `src/cppstd/core.cppm` counts. | Define the coverage scope, for example "all first-party code under `src/`", and use a different word. |
| C4 | 🟡 Major | 307-309, 374-377, 894 | How does a PR update the macOS lock entries when the macOS gate runs only after merge? What happens when `main` fails to match on macOS? | Describe the macOS lock path, for example a follow-up `caps:update` PR. Say whether a macOS mismatch on `main` is red. |
| C5 | 🟡 Major | 385-391, 465-467, 955-956 | The golden VM is named "by its inputs hash", but §2 has no row for it. | Add a §2 row: `vm/inputs.toml`, `tools.toml` and `mise.lock`. |
| C6 | 🟡 Major | 112, 443, 929, 939-941 | fnox, jouet and hk are never defined. jouet carries workflow meaning. | Define each in one line at first use. |
| C7 | 🟡 Major | 600-604, 768-771, 852 | The PC runner App, the owner's personal account and the existing org-admin App are not explained: what type each is, and where its credential lives. | Define each identity. |
| C8 | 🟡 Major | 257, 650-652, 975 | The agent cap has no value, and "agent session" isn't defined. | State the cap and where it is set, and how sessions are counted. |
| C9 | 🟡 Major | 98-99, 443, 529-530, 929, 977 | No tier-2 tool is ever named. | List the first tier-2 tools. |
| C10 | 🟡 Major | 34, 95, 163-172, 230, 863, 955 | Some D-references carry meaning that isn't stated in the text. The "settled questions" list is D-numbers only. | Give each settled question a one-clause answer, and forward-reference §5 for the consteval rule. |
| C11 | 🟡 Major | 852-854, 906, 944-949 | The PC runner is registered before M1a and used by `post-merge.yml` in M1a, but M2 is titled "the PC runner". | Say what `post-merge.yml` runs on until M2, or move the PC to M2. |
| C12 | 🟡 Major | 877, 955, 966 | `vm/inputs.toml` (sizes) and `canary/pins.toml` are pins files that `pins:validate` doesn't describe. | Extend `pins:validate` to cover them, with their allowed fields. |
| C13 | 🟢 Nit | 166, 313, 771 | "Fence" is not defined at first use. | Define it in §6. |
| C14 | 🟢 Nit | 248, 314, 586 | The same idea is called "owned file", "owner-root files" and "owned roots". | Use "owned roots" everywhere. |
| C15 | 🟢 Nit | 210, 406, 889 | It's unclear how `image:tag` relates to `artifact:tag`. | Say that `image:tag` wraps `artifact:tag`. |
| C16 | 🟢 Nit | 794, 798 | "Leaf" is not defined. | Define it. |
| C17 | 🟢 Nit | 52-53, 138, 383, 707 | Legacy project names are not explained, and "cpp-core keeps running on free models" is opaque. | Add a short glossary. |
| C18 | 🟢 Nit | 4, 35-36, 274, 663, 989 | EGM, the stage names, the drift report and "goldfish" are not defined. | Add one sentence on EGM, with a link. |
| C19 | 🟢 Nit | 211-212 vs 669, 944-948 | CUJ 2 builds amd64, but amd64 arrives in M2. | Note that amd64 comes in M2. |
| C20 | 🟢 Nit | 94 | The "ut" framework isn't identified until line 895. | Name Boost.ext ut at first use. |
| C21 | 🟢 Nit | 835 | "The commit review step" is unexplained. | Describe the step. |
| C22 | 🟢 Nit | 878 vs §2 | The full tag format (name prefix plus hash) appears only in the implementation part. | State it in §2. |
| C23 | 🟢 Nit | 940 | Context7 and codebase-memory are not described. | Add one clause each. |
| C24 | 🟢 Nit | 584-585, 844-845 | It's unclear which Actions job needs the agent App key. | Name the workflow, for example `digest.yml`. |

## Author (Elephant) notes for the owner

* The reviewer understood the design, but a newcomer is left with questions
  in three areas:
  - **Vocabulary from your setup:** fnox, jouet, hk, the identities, the
    commit review, EGM.
  - **Undefined labels:** the M0 letters, "owned", "leaf", "fence".
  - **Thin macOS mechanics:** how the macOS lock entries get updated, and
    the golden VM's hash.
* **C2 and C4 are real design gaps, not only wording.**
  - **C2:** given D54, the `publish` Environment fences secrets but not GHCR
    write. The text should say so plainly.
  - **C4:** a capability change on macOS can't be accepted before merge,
    because the macOS gate runs after merge.
* Most fixes are one line each, plus a short glossary.
