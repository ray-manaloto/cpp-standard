"""Offline coverage of the first-run bootstrap, result handoff and host cleanup."""

import json
import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "docs/standard/gha-runner"


class FirstRun(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        (self.root / "source").mkdir()
        (self.root / "result").mkdir()
        self.result = self.root / "result"

    def shell(self, body, **settings):
        # Any Docker or APT invocation outside the case's stand-ins is a test error.
        preamble = """
set -eu -o pipefail
source "$scripts/pc-compiler-bootstrap.sh"
source "$scripts/pc-compiler-once.sh"
docker() { echo "unexpected docker: $*" >&2; return 88; }
apt-get() { echo "unexpected apt: $*" >&2; return 88; }
result=$PWD/result source=$PWD/source state=$PWD
"""
        return subprocess.run(
            ["bash", "-c", preamble + body],
            cwd=self.root,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(self.root),
                "scripts": str(SCRIPTS),
                **settings,
            },
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def test_bootstrap_lock_and_postinstall_in_private_project(self):
        source = self.root / "source"
        (source / ".mise").mkdir()
        lock = source / ".mise/mise.lock"
        lock.write_text("sealed input")
        hook = tomllib.loads((ROOT / "mise.toml").read_text())["hooks"]["postinstall"]
        for status in [0, 37]:
            with self.subTest(status=status):
                proc = self.shell(
                    """
hk() { echo "$*" >> "$state/hk.log"; }
unset CI
eval "$postinstall"
mise() {
  [[ "$#" == 4 && "$1" == -E && "$2" == ubuntu && "$3" == bootstrap && "$4" == --yes ]]
  [[ "$PWD" != "$source" && "$MISE_TRUSTED_CONFIG_PATHS" == "$PWD" ]]
  printf '%s' "$PWD" > "$state/bootstrap-dir"
  [[ "$(cat .mise/mise.lock)" == "sealed input" ]]
  tmp_lock="$(mktemp .mise/.mise.lock.XXXXXXXX)"
  echo refreshed > "$tmp_lock"
  mv "$tmp_lock" .mise/mise.lock
  eval "$postinstall"
  return "$fixture_rc"
}
bootstrap_compiler_project "$source"
""",
                    TMPDIR=str(self.root / "result"),
                    postinstall=hook,
                    fixture_rc=str(status),
                )
                self.assertEqual(proc.returncode, status, proc.stderr)
                self.assertEqual(lock.read_text(), "sealed input")
                project = Path((self.root / "bootstrap-dir").read_text())
                self.assertEqual(project.parent.resolve(), self.result.resolve())
                self.assertFalse(project.exists())
                hk = self.root / "hk.log"
                self.assertEqual(hk.read_text().splitlines(), ["install --mise"])
                hk.unlink()

    def prerequisites(self, *, bundle=True, update_rc=0):
        if bundle:
            (self.root / "bundle").write_text("fixture CA")
        (self.root / "mise.ubuntu.toml").write_text(
            'APT::Snapshot "20261116T000000Z";\n'
        )
        return self.shell(
            """
apt-get() {
  echo "$*" >>apt.log
  if [[ "${!#}" == update ]]; then return "$update_rc"; fi
}
install_snapshot_prerequisites bundle
""",
            update_rc=str(update_rc),
        )

    def test_trust_and_signed_snapshot_precede_package_install(self):
        proc = self.prerequisites()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        options = "-o APT::Snapshot=20261116T000000Z -o Acquire::https::CaInfo=bundle"
        self.assertEqual(
            (self.root / "apt.log").read_text().splitlines(),
            [
                options + " -o APT::Update::Error-Mode=any update",
                options + " install -y --no-install-recommends ca-certificates curl",
            ],
        )

    def test_missing_bootstrap_trust_stops_before_apt(self):
        self.assertNotEqual(self.prerequisites(bundle=False).returncode, 0)
        self.assertFalse((self.root / "apt.log").exists())

    def test_refused_update_keeps_apt_status_and_skips_install(self):
        self.assertEqual(self.prerequisites(update_rc=100).returncode, 100)
        self.assertEqual(len((self.root / "apt.log").read_text().splitlines()), 1)

    def test_ca_copy_from_pinned_donor_to_fresh_container(self):
        for data in ["certificate fixture", ""]:
            with self.subTest(nonempty=bool(data)):
                proc = self.shell(
                    """
donor_name=owned-donor build=owned-build
docker() {
  case "$*" in
    "cp owned-donor:/etc/ssl/certs/ca-certificates.crt $state/bootstrap-ca.crt")
      printf '%s' "$bundle" >"$3" ;;
    "cp $state/bootstrap-ca.crt owned-build:/tmp/cpp-bootstrap-ca.crt")
      cp "$2" delivered ;;
    *) return 88 ;;
  esac
}
seed_compiler_ca
""",
                    bundle=data,
                )
                if data:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual((self.root / "delivered").read_text(), data)
                    (self.root / "delivered").unlink()
                else:
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertFalse((self.root / "delivered").exists())

    def test_wait_distinguishes_container_status_and_deadline(self):
        for output, wait_rc, expected in [
            ("0", 0, 0),
            ("100", 0, 100),
            ("", 124, 124),
            ("bad", 0, 1),
            ("256", 0, 1),
        ]:
            with self.subTest(output=output, wait_rc=wait_rc):
                proc = self.shell(
                    """
timeout() {
  [[ "$*" == "--kill-after=30s 270m docker wait owned-build" ]] || return 125
  echo "$output"
  return "$fixture_wait_rc"
}
wait_compiler_build owned-build
""",
                    output=output,
                    fixture_wait_rc=str(wait_rc),
                )
                self.assertEqual(proc.returncode, expected, proc.stderr)
                code = output if wait_rc == 0 and output in {"0", "100"} else "unknown"
                self.assertEqual(
                    (self.result / "build-exit.txt").read_text(),
                    f"wait_exit={wait_rc} container_exit={code}\n",
                )

    def finish(self, cleanup_rc):
        (self.root / "build.cid").write_text("a" * 64 + "\n")
        (self.root / "volume-attached").touch()
        return self.shell(
            """
run=1 job_id=2 sha=abc rid='' worker='' phase=compile owner_name=owned
runner=listener build=build check=check donor_name=donor
work_volume=work cert_volume=cert passes=0 fails=0 na=0 total=0
status=FAIL timing=unverified execution_rc=100
docker() {
  case "$1" in
    inspect) echo owned ;;
    logs) test -f volume-attached || return 81; echo "original apt failure" ;;
    *) return 88 ;;
  esac
}
remove_compiler_container() {
  echo "container $1" >>order
  if [[ "$1" == build ]]; then rm -f volume-attached; fi
}
remove_compiler_volume() {
  echo "volume $1" >>order
  [[ ! -e volume-attached ]] || return 82
  return "$fixture_cleanup_rc"
}
finish_compiler_workload
# The listener and original output stay available while Actions uploads.
test -e "$result/final.json"
! grep -q listener order
compiler_cleanup 1
""",
            fixture_cleanup_rc=str(cleanup_rc),
        )

    def check_failed_handoff(self, cleanup_rc):
        proc = self.finish(cleanup_rc)
        self.assertEqual(proc.returncode, 100, proc.stderr)
        receipt = json.loads((self.result / "final.json").read_text())
        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(receipt["execution_exit"], 100)
        self.assertEqual(receipt["cleanup_exit"], cleanup_rc)
        self.assertEqual(receipt["total"], 0)
        self.assertEqual(receipt["checklist"], "not_run")
        self.assertEqual(
            (self.result / "build.log").read_text(), "original apt failure\n"
        )
        order = (self.root / "order").read_text().splitlines()
        self.assertEqual(
            order[:5],
            [
                "container check",
                "container build",
                "container donor",
                "volume work",
                "volume cert",
            ],
        )
        self.assertEqual(order[-1], "container listener")
        self.assertIn(
            f"exit=100 cleanup={cleanup_rc}", (self.root / "closeout").read_text()
        )

    def test_attached_build_volume_and_actions_failure_handoff(self):
        self.check_failed_handoff(0)

    def test_secondary_cleanup_failure_retains_original_exit_and_evidence(self):
        self.check_failed_handoff(1)

    def test_unexpected_exit_can_still_resolve_local_worker(self):
        proc = self.shell(
            """
prepare_compiler() {
  runner=listener check=check build=build
  work_volume=work cert_volume=cert donor_name=donor
  local git_dir=unused sha=abc
  set -m
  sleep 6 &
  worker=$!
  echo "$worker" >worker.pid
  set +m
  git() { return 37; }
  tar() { cat >/dev/null; }
  remove_compiler_container() { echo "$1" >>removed; }
  remove_compiler_volume() { return 0; }
  supervise_compiler
}
compiler_once 1
"""
        )
        self.assertEqual(proc.returncode, 37, proc.stderr)
        self.assertNotIn("unbound", proc.stderr)
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.root / "worker.pid").read_text()), 0)
        self.assertIn("exit=37 cleanup=0", (self.root / "closeout").read_text())
        self.assertIn("listener", (self.root / "removed").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
