"""Read the runtime owner's saved observations and terminal collection offline."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("timestamp needs a UTC offset")
    return parsed


def checkpoint(attempt, polled, owner_receipts=()):
    samples = []
    for path in attempt.glob("sample-*.txt"):
        lines = path.read_text().splitlines()
        if lines:
            samples.append((timestamp(lines[0]), path, lines[1:]))
    for path in attempt.glob(".planning/*/progress.md"):
        day = None
        in_samples = False
        for line in path.read_text().splitlines():
            date = re.fullmatch(r"## (\d{4}-\d\d-\d\d) UTC", line)
            if date:
                day = date[1]
            if line.startswith("## "):
                in_samples = line == "## Latest host sample"
            match = re.match(r"- (\d\d:\d\d:\d\d) UTC\. (.+)", line)
            if day and in_samples and match:
                samples.append((timestamp(f"{day}T{match[1]}Z"), path, [match[2]]))
    if owner_receipts:
        admitted = read_json(attempt / "run-admitted.json")
        for path in owner_receipts:
            receipt = read_json(path)
            if (receipt["run"], receipt["attempt"]) != (
                admitted["id"],
                admitted["run_attempt"],
            ):
                raise ValueError("owner observation belongs to another attempt")
            samples.append(
                (timestamp(receipt["acquired"]), path, [receipt["observation"]])
            )
    eligible = [sample for sample in samples if sample[0] <= polled]
    latest = None
    if eligible:
        acquired, source, lines = max(eligible, key=lambda sample: sample[0])
        latest = {
            "acquired": acquired.isoformat(),
            "source": str(source),
            "observations": lines,
        }
    return {"polled": polled.isoformat(), "host_sample": latest}


def read_json(path):
    return json.loads(path.read_text())


def fields(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines())


def counters(path):
    if not path.exists():
        return None
    stats = read_json(path)["stats"]
    return {
        "requests": stats["compile_requests"],
        "hits": sum(stats["cache_hits"]["counts"].values()),
        "misses": sum(stats["cache_misses"]["counts"].values()),
        "non_cacheable": stats["requests_not_cacheable"],
    }


def closeout(collection):
    result = collection / "host-result/result"
    assignment = read_json(result / "assignment.json")
    deadline = read_json(collection / "deadline.json")
    for field, assigned in (("run", "run"), ("job", "job"), ("runner", "runner_id")):
        if str(deadline[field]) != assignment[assigned]:
            raise ValueError(f"deadline {field} differs from assignment")
    target = timestamp(deadline["target_utc"])
    offsets = {}
    for name in ("job_completed", "host_closeout_completed", "drain_verified_utc"):
        observed = deadline.get(name)
        offsets[name] = (
            (timestamp(observed) - target).total_seconds() if observed else None
        )
    image = (result / "built-image").read_text().strip()
    reuse = None
    if (result / "compiler-cache.txt").exists():
        decision = fields(result / "compiler-cache.txt")
        key = hashlib.sha256((result / "compiler-inputs.json").read_bytes()).hexdigest()
        package = read_json(result / "compiler-package.json")
        if key != decision["inputs_sha256"] or key != package["inputs_sha256"]:
            raise ValueError("compiler input key mismatch")
        mode = decision["source"]
        if mode not in {"local", "registry", "retained", "cold"}:
            raise ValueError("unknown compiler source")
        digest_path = result / "compiler-registry-digest"
        digest = digest_path.read_text().strip() if digest_path.exists() else None
        if (mode == "registry" or digest is not None) and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", digest or ""
        ):
            raise ValueError("missing or invalid registry digest")
        reuse = {
            "source": mode,
            "inputs_sha256": key,
            "archive_sha256": package["archive_sha256"],
            "registry_digest": digest,
            "compiler_counters": counters(result / "compiler-sccache.json"),
        }
    return {
        "assignment": assignment,
        "image": image,
        "compiler_package": reuse,
        "project_counters": {
            p.name: counters(p / "sccache.json")
            for p in sorted((result / "project").glob("*-coverage-amd64"))
        },
        "target_utc": deadline["target_utc"],
        "seconds_from_target": offsets,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("checkpoint")
    status.add_argument("attempt", type=Path)
    status.add_argument("polled", type=timestamp)
    status.add_argument("--owner-receipt", action="append", type=Path, default=[])
    commands.add_parser("closeout").add_argument("collection", type=Path)
    args = parser.parse_args()
    report = (
        checkpoint(args.attempt, args.polled, args.owner_receipt)
        if args.command == "checkpoint"
        else closeout(args.collection)
    )
    print(json.dumps(report, indent=2))
