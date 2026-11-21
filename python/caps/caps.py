"""The capability lock (D42): what each compiler can do in each environment, as committed
JSON, and the checks around it (ticket #134).

- `check` compares one configure's probe results (build/<preset>/capabilities.json, written by
  cmake/probes.cmake) with cmake/capabilities.lock.json and fails naming the capability that
  disagrees: a planted disagreement between a probe and the lock fails the gate by name.
- `gate-presets` filters the candidate gate presets by the lock — never by a live probe (D42):
  a preset whose capability the lock disallows for its compiler is skipped, and the log says
  where TSan was skipped and why.
- `applicable` prints the compilers whose lock entry allows a capability; the must-fail runner
  runs a capability fixture once per such compiler, with the compiler as its argument.
- `update` merges capabilities.json files (the environments' CI jobs' uploads) into the lock;
  `mise run caps:update` is the explicit lock update task (D53), and its diff is the PR's
  record of the change (D42).

Run: python3 -I python/caps/caps.py <subcommand> ...
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = ROOT / "cmake/capabilities.lock.json"
# The capabilities a probe reports and the lock records, in probe order.
CAPABILITIES = ("asan", "ubsan", "tsan", "valgrind")
# The gate preset kinds beyond -coverage and the capabilities each one needs.
PRESET_KINDS: dict[str, tuple[str, ...]] = {
    "asan-ubsan": ("asan", "ubsan"),
    "tsan": ("tsan",),
    "valgrind": ("valgrind",),
}


class CapsError(Exception):
    """A lock, probe file or capability name this module refuses."""


def environment() -> str:
    """This environment, as the lock names it: <system>-<arch> with the repository's names
    (linux, macos; arm64, amd64). CPPSTD_CAPS_ENVIRONMENT overrides it, for the tests."""
    override = os.environ.get("CPPSTD_CAPS_ENVIRONMENT")
    if override:
        return override
    systems = {"linux": "linux", "darwin": "macos"}
    archs = {"aarch64": "arm64", "arm64": "arm64", "amd64": "amd64", "x86_64": "amd64"}
    system = systems.get(platform.system().lower())
    arch = archs.get(platform.machine().lower())
    if system is None or arch is None:
        raise CapsError(
            f"cannot name this environment ({platform.system()} {platform.machine()})"
        )
    return f"{system}-{arch}"


def load_lock(path: Path) -> dict:
    """The capability lock as JSON, refusing a missing or malformed one."""
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CapsError(f"cannot read the capability lock {path}: {error}") from error
    if (
        not isinstance(lock, dict)
        or not isinstance(lock.get("environments"), dict)
        or not lock["environments"]
    ):
        raise CapsError(f"{path} lists no environments entry")
    return lock


def load_probe(path: Path) -> tuple[str, str, dict]:
    """One configure's probe results as (environment, preset, capabilities), refusing a
    missing, malformed or unnamed one."""
    try:
        probe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CapsError(f"cannot read the probe results {path}: {error}") from error
    if not isinstance(probe, dict):
        raise CapsError(f"{path} must contain a JSON object")
    env = probe.get("environment")
    preset = probe.get("preset")
    capabilities = probe.get("capabilities")
    if not isinstance(env, str) or not env or not isinstance(preset, str) or not preset:
        raise CapsError(f"{path} names no environment and preset")
    if probe.get("compiler") != preset.partition("-")[0] or preset == "unknown":
        raise CapsError(f"{path} names a compiler inconsistent with {preset}")
    if not isinstance(capabilities, dict) or not capabilities:
        raise CapsError(f"{path} reports no capabilities")
    invalid = sorted(
        name for name, value in capabilities.items() if not isinstance(value, bool)
    )
    if invalid:
        raise CapsError(
            f"{path} reports non-boolean capabilities: {', '.join(invalid)}"
        )
    unknown = sorted(set(capabilities) - set(CAPABILITIES))
    if unknown:
        raise CapsError(f"{path} reports unknown capabilities: {', '.join(unknown)}")
    return env, preset, capabilities


def preset_entry(lock: dict, env: str, preset: str) -> dict:
    """The lock's entry for one preset in one environment, refusing a missing one."""
    environments = lock["environments"]
    if env not in environments:
        raise CapsError(f"the capability lock has no entry for {env}")
    row = environments[env]
    presets = row.get("presets") if isinstance(row, dict) else None
    if not isinstance(presets, dict) or preset not in presets:
        raise CapsError(f"the capability lock has no {preset} entry in {env}")
    entry = presets[preset]
    if not isinstance(entry, dict) or not isinstance(entry.get("capabilities"), dict):
        raise CapsError(f"the lock's {preset} entry in {env} records no capabilities")
    invalid = sorted(
        name
        for name, value in entry["capabilities"].items()
        if not isinstance(value, bool)
    )
    if invalid:
        raise CapsError(
            f"the lock's {preset} entry in {env} records non-boolean capabilities: {', '.join(invalid)}"
        )
    reasons = entry.get("skip_reasons", {})
    if not isinstance(reasons, dict) or any(
        not isinstance(value, str) for value in reasons.values()
    ):
        raise CapsError(f"the lock's {preset} entry in {env} has invalid skip reasons")
    return entry


def check(probe: Path, lock_path: Path, expected_preset: str | None = None) -> int:
    """The gate's capability comparison (D42): the probes' results against the committed
    lock, failing by capability name on any disagreement."""
    try:
        env, preset, got = load_probe(probe)
        if expected_preset and (preset != expected_preset or env != environment()):
            raise CapsError(
                f"expected {expected_preset} ({environment()}), got {preset} ({env})"
            )
        expected = preset_entry(load_lock(lock_path), env, preset)["capabilities"]
    except CapsError as error:
        print(f"ci:caps: FAIL {error}", file=sys.stderr)
        return 1
    problems = []
    for name in sorted(set(CAPABILITIES) | set(got) | set(expected)):
        if name not in got and name not in expected:
            problems.append(f"capability {name}: missing from both probe and lock")
            continue
        if name not in got:
            problems.append(f"capability {name}: the lock lists it, the probe did not")
        elif name not in expected:
            problems.append(
                f"capability {name}: the probe reports it, the lock does not"
            )
        elif got[name] != expected[name]:
            problems.append(
                f"capability {name}: probe {got[name]}, lock {expected[name]}"
            )
    if problems:
        for problem in problems:
            print(
                f"ci:caps: FAIL on {preset} ({env}): {problem}",
                file=sys.stderr,
            )
        return 1
    print(f"PASS: probes match the capability lock ({preset}, {env})")
    return 0


def gate_presets(requested: list[str], lock_path: Path) -> int:
    """The candidate gate presets filtered by the lock (D42): the allowed ones on stdout,
    with the lock reason for each skipped TSan preset on stderr."""
    env = environment()
    lock = load_lock(lock_path)
    allowed: list[str] = []
    for preset in requested:
        compiler, _, kind = preset.partition("-")
        entry = preset_entry(lock, env, preset)
        if kind == "coverage":
            allowed.append(preset)
            continue
        needs = PRESET_KINDS.get(kind)
        if needs is None:
            raise CapsError(f"{preset} is no gate preset kind")
        if kind == "valgrind" and (not env.startswith("linux-") or compiler != "gcc16"):
            raise CapsError(f"{preset}: Valgrind applies to Linux gcc16")
        caps = entry["capabilities"]
        missing = [name for name in needs if caps.get(name) is not True]
        if not missing:
            allowed.append(preset)
            continue
        reasons = entry.get("skip_reasons", {})
        if (
            kind == "tsan"
            and caps.get("tsan") is False
            and reasons.get("tsan", "").strip()
        ):
            print(f"skipped: {preset}: {reasons['tsan']}", file=sys.stderr)
            continue
        raise CapsError(
            f"{preset}: required capabilities missing or disabled: {', '.join(missing)}"
        )
    print(" ".join(allowed))
    return 0


def applicable(capability: str, lock_path: Path, requested: list[str]) -> int:
    """The compilers whose lock entry allows the capability on stdout, one skip line per
    disallowed compiler on stderr (D42)."""
    kind = next(
        (kind for kind, names in PRESET_KINDS.items() if capability in names), None
    )
    if kind is None:
        raise CapsError(f"unknown capability {capability}")
    env = environment()
    lock = load_lock(lock_path)
    row = lock["environments"].get(env)
    presets = row.get("presets") if isinstance(row, dict) else None
    if not isinstance(presets, dict) or not presets:
        raise CapsError(f"the capability lock has no {env} presets entry")
    candidates = requested or sorted(
        preset for preset in presets if preset.endswith(f"-{kind}")
    )
    if any(not preset.endswith(f"-{kind}") for preset in candidates):
        raise CapsError(f"{capability}: fixtures must name {kind} presets")
    if not candidates:
        raise CapsError(f"the capability lock has no {kind} presets in {env}")
    allowed: list[str] = []
    for preset in candidates:
        compiler, _, _ = preset.partition("-")
        entry = preset_entry(lock, env, preset)
        if entry["capabilities"].get(capability) is True:
            allowed.append(compiler)
            continue
        reason = entry.get("skip_reasons", {}).get(capability)
        if (
            capability != "tsan"
            or entry["capabilities"].get(capability) is not False
            or not (reason or "").strip()
        ):
            raise CapsError(
                f"{preset}: missing required capability decision for {capability}"
            )
        print(f"skipped: {capability} on {compiler}: {reason}", file=sys.stderr)
    print(" ".join(allowed))
    return 0


def update(probes: list[Path], lock_path: Path) -> int:
    """Merge the probes' results into the lock (D42, D53): one entry per environment and
    preset, no volatile version strings; a capability the probe found again loses its skip
    reason, one it lost keeps it or takes the probe's."""
    try:
        lock = (
            load_lock(lock_path)
            if lock_path.exists()
            else {"schema": 1, "environments": {}}
        )
        seen = {}
        for probe in probes:
            env, preset, capabilities = load_probe(probe)
            missing = sorted(set(CAPABILITIES) - set(capabilities))
            if missing:
                raise CapsError(f"{probe} omits capabilities: {', '.join(missing)}")
            key = (env, preset)
            prior = seen.setdefault(key, capabilities)
            if prior != capabilities:
                differing = [
                    name for name in CAPABILITIES if prior[name] != capabilities[name]
                ]
                raise CapsError(
                    f"conflicting probes for {preset} ({env}): {', '.join(differing)}"
                )
            environments = lock["environments"].setdefault(env, {})
            presets = environments.setdefault("presets", {})
            if preset not in presets:
                presets[preset] = {"capabilities": {}, "skip_reasons": {}}
            entry = preset_entry(lock, env, preset)
            for name, value in sorted(capabilities.items()):
                if entry["capabilities"].get(name) != value:
                    print(
                        f"changed: {name} on {preset} ({env}): "
                        f"{entry['capabilities'].get(name)} -> {value}"
                    )
                entry["capabilities"][name] = value
                if value:
                    entry.get("skip_reasons", {}).pop(name, None)
                elif name not in entry.get("skip_reasons", {}):
                    entry.setdefault("skip_reasons", {})[name] = (
                        f"the {preset} probe found no {name} support in {env}"
                    )
    except CapsError as error:
        print(f"caps:update: FAIL {error}", file=sys.stderr)
        return 1
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"PASS: the capability lock now matches the probes ({lock_path})")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="caps",
        description="The capability lock's checks: compare probes with the lock, filter the "
        "gate presets by it, and update it (D42).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check_cmd = sub.add_parser(
        "check", help="compare one configure's probes with the lock"
    )
    check_cmd.add_argument(
        "probe", type=Path, help="the build tree's capabilities.json"
    )
    check_cmd.add_argument(
        "--lock", type=Path, default=DEFAULT_LOCK, help="the capability lock"
    )
    check_cmd.add_argument("--preset")
    presets_cmd = sub.add_parser(
        "gate-presets", help="filter the candidate gate presets"
    )
    presets_cmd.add_argument(
        "--requested", required=True, help="the candidate presets, space-separated"
    )
    presets_cmd.add_argument(
        "--lock", type=Path, default=DEFAULT_LOCK, help="the capability lock"
    )
    applicable_cmd = sub.add_parser(
        "applicable", help="the compilers the lock allows it for"
    )
    applicable_cmd.add_argument("capability", help="one capability, e.g. tsan")
    applicable_cmd.add_argument(
        "--lock", type=Path, default=DEFAULT_LOCK, help="the capability lock"
    )
    applicable_cmd.add_argument("--presets", default="")
    update_cmd = sub.add_parser("update", help="merge probe files into the lock")
    update_cmd.add_argument(
        "probes", type=Path, nargs="+", help="capabilities.json files"
    )
    update_cmd.add_argument(
        "--lock", type=Path, default=DEFAULT_LOCK, help="the capability lock"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check(args.probe, args.lock, args.preset)
        if args.command == "gate-presets":
            return gate_presets(args.requested.split(), args.lock)
        if args.command == "applicable":
            return applicable(
                args.capability,
                args.lock,
                args.presets.split(",") if args.presets else [],
            )
        return update(args.probes, args.lock)
    except CapsError as error:
        print(f"caps: FAIL {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
