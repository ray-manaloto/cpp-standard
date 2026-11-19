---
name: pins-apt-bump
description: Move every apt pin of cpp-standard to the newest version in the apt indexes by running `mise run pins:apt-bump` (D165), and nothing else. Use it whenever someone asks to bump, update, refresh or move the apt pins, the LLVM 23 or Ubuntu package pins, `apt.toml`, `apt-toolchain-host.toml` or `mise.ubuntu.toml`'s pins or snapshot date, or to check whether a pinned apt version is still published.
---

# pins-apt-bump

Runs the task `mise run pins:apt-bump` (`.mise/tasks/pins/apt-bump`, `python/pins/apt_bump.py`) from the checkout
root, and nothing else: no other command, no edits by hand, no commit.

1. Run `mise run pins:apt-bump`. Pass `--group llvm` or `--group ubuntu` only when asked for one group, and
   `--check` only when asked whether the pins are still published.
2. Report its output as it is: one line per changed package (`name old -> new`, plus `APT::Snapshot old -> new`
   when the machine setup file's date moved), or nothing when no pin changed. A `FAIL:` line names the refused
   package or index; report it and stop. Nonzero exit means the group it names changed no file.
