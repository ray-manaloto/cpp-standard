# Python code and its coverage gates

Every Python package or script folder here either gates its default test run on a recorded coverage floor or carries
a one-line reason for having none (#185). A floor is the coverage measured when it was set. Raise it when coverage
rises. A change that lowers it says why in its commit message and pull request.

| Folder | Default test run | Gate |
| --- | --- | --- |
| `repo` | `mise run //repo:test` | 100% line and branch (`pyproject.toml`) |
| `workflow` | `mise run //workflow:test` | 100% line and branch (`pyproject.toml`) |
| `pctools` | `mise run pctools:test` | 100% line and branch (`pyproject.toml`) |
| `pins` | `mise run pins:cov` (the `pins-cov` hk step) | floor in `pins/pyproject.toml` |
| `agents` | `mise run agents:cov` (the `agents-cov` hk step) | floor in `agents/pyproject.toml` |
| `suites` | `mise run suites:cov` (the `suites-cov` hk step) | floor in `suites/pyproject.toml` |
| `artifact` | `mise run artifact:cov` (the `artifact-cov` hk step) | floor in `artifact/pyproject.toml` |
| `toolchain` | `mise run toolchain:cov` (the `toolchain-cov` hk step) | floor in `toolchain/pyproject.toml` |
| `gate` | `mise run gate:cov` (the `gate-cov` hk step) | floor in `gate/pyproject.toml` |
| `guards` | none here | No floor: a byte-for-byte copy of dotfiles' `python/guards`, gated at 100% there. |
