# cpp-standard

> **Sunset (2026-11-27).** This repository is being sunset. Its successor is
> [ray-manaloto/dotfiles-v2](https://github.com/ray-manaloto/dotfiles-v2). Open new issues and pull requests there.

cpp-standard held the C++ environment and project standard: the design (`docs/designs/environment-standard.md`, its
decisions in `docs/designs/level-1/decisions-log.md`), the macOS and Ubuntu setups (`docs/standard/`), the tools
image and the clang-p2996 toolchain builds, and the gate that checked them.

## State

- No new issues or pull requests here, except the work that finishes the sunset. The existing issues stay as a
  record.
- The daily schedules of the `apt-bump`, `post-merge` and `builder` workflows are removed from the workflow files.
  The owner may also disable those workflows, which stops their manual and push runs too.
- The repository is not archived yet; archiving comes last.

Agents: read `AGENTS.md` first.
