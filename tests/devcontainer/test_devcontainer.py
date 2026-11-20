"""Offline tests of the devcontainer's host-side chain (ticket #137; the file plan's .devcontainer
row, D93): image:verify runs on the host and writes the verified CPPSTD_TOOLS_IMAGE to the
generated, gitignored .devcontainer/.env; a refusal removes the file and names the image; compose
starts exactly that digest, as the image's non-root user, with no privileged run anywhere.
artifact.py's env-file unit tests are tests/artifact/test_artifact.py (fake registry, fake
verifier); here the generated files are checked statically and .mise/tasks/image/verify runs with
a stand-in python3, so nothing here needs mise, gh, Docker or the network. Run:
python3 -I tests/devcontainer/test_devcontainer.py
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/artifact"))

import artifact

DEVCONTAINER = ROOT / ".devcontainer/devcontainer.json"
COMPOSE = ROOT / ".devcontainer/compose.yaml"
GITIGNORE = ROOT / ".gitignore"
VERIFY_TASK = ROOT / ".mise/tasks/image/verify"
IMAGE = "ghcr.io/ray-manaloto/cpp-standard/tools"

# The task's --arch default derives the Docker arch this way (python/toolchain/fetch.py:477).
HOST_ARCH = {
    "aarch64": "arm64",
    "arm64": "arm64",
    "x86_64": "amd64",
    "amd64": "amd64",
}[platform.machine().lower()]


# The stand-in python3 (its shebang is /usr/bin/python3, on macOS and CI's Ubuntu alike): it
# answers the two calls the verify task makes. The real pins.py and artifact.py run under
# coverage in the pins-cov and artifact-cov steps; only the task's wiring is tested here.
STUB_PY = '''#!/usr/bin/python3
"""Stand-in python3 for tests/devcontainer/test_devcontainer.py: answers the pins.py tag probe
and the artifact.py verify call that .mise/tasks/image/verify makes, with no registry, gh or
network."""
import json
import os
import sys

argv = sys.argv[1:]
# argv is ["-I", "<script>", ...]; the call the task makes follows the script path.
script = argv[1] if len(argv) > 1 and argv[1].endswith(".py") else ""
args = argv[2:] if script else argv
log = os.environ.get("STUB_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps([script, *args]) + "\\n")
if script.endswith("pins.py"):
    kind = args[args.index("tag") + 1]
    arch = args[args.index("--arch") + 1]
    print(f"{kind}-{arch}-0123456789abcdef")
elif script.endswith("artifact.py"):
    ref = args[args.index("verify") + 1]
    if os.environ.get("DEVCONTAINER_TEST_REFUSED") == "1":
        print(f"FAIL: {ref}: attestation refused", file=sys.stderr)
        sys.exit(1)
    image = ref.rpartition(":")[0]
    digest = "sha256:" + "c" * 64
    if "--env-file" in args:
        path = args[args.index("--env-file") + 1]
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{os.environ['STUB_ENV_VAR']}={image}@{digest}\\n")
    print(digest)
else:
    sys.exit(2)
'''


class DevcontainerFiles(unittest.TestCase):
    """The generated files and how they agree: verify -> .env -> compose, the non-root user, no
    privileged run anywhere, sccache in a volume (the file plan's .devcontainer row, D93)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.json_text = DEVCONTAINER.read_text()
        cls.dev = json.loads(cls.json_text)
        cls.compose = COMPOSE.read_text()
        # Without comments, so the checks see what compose runs, not what the file explains.
        cls.compose_body = "\n".join(
            line
            for line in cls.compose.splitlines()
            if not line.lstrip().startswith("#")
        )

    def _keys(self, node: object) -> set[str]:
        if isinstance(node, dict):
            keys = set(node)
            for value in node.values():
                keys |= self._keys(value)
            return keys
        if isinstance(node, list):
            keys = set()
            for item in node:
                keys |= self._keys(item)
            return keys
        return set()

    def test_the_generated_env_file_is_ignored(self) -> None:
        lines = {line.strip() for line in GITIGNORE.read_text().splitlines()}
        self.assertIn(
            ".devcontainer/.env",
            lines,
            "the generated env file must never be committed",
        )

    def test_initialize_verifies_the_tools_image_into_the_env_file(self) -> None:
        init = self.dev["initializeCommand"]
        self.assertIn("image:verify tools", init)
        self.assertIn("--env-file .devcontainer/.env", init)

    def test_initialize_refuses_compose_environment_overrides(self) -> None:
        for name in (
            "CPPSTD_TOOLS_IMAGE",
            "COMPOSE_ENV_FILES",
            "COMPOSE_DISABLE_ENV_FILE",
        ):
            with self.subTest(name=name):
                result = subprocess.run(
                    ["/bin/sh", "-c", self.dev["initializeCommand"]],
                    env={"PATH": "/usr/bin:/bin", name: "override"},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{name}", result.stderr)

    def test_compose_reads_the_variable_verify_writes(self) -> None:
        # The :? form: with no env file compose refuses (naming the fix) instead of starting an
        # empty or unverified image; the variable is the one image:verify writes (D93).
        self.assertIn(f"image: ${{{artifact.DEVCONTAINER_ENV_VAR}:?", self.compose_body)

    def test_post_create_fetches_then_bootstraps_then_checks(self) -> None:
        post = self.dev["postCreateCommand"]
        fetch = post.index("toolchain:fetch --release-only")
        bootstrap = post.index("vcpkg:bootstrap")
        doctor = post.index("mise run doctor")
        self.assertLess(fetch, bootstrap)
        self.assertLess(bootstrap, doctor)
        self.assertIn("export CPPSTD_P2996_PREFIX", post)

    def test_no_token_is_passed_in_and_post_create_needs_gh_login_first(self) -> None:
        # Owner ruling (#137): no host token in the container; postCreate stops naming the login.
        self.assertNotIn("remoteEnv", self._keys(self.dev))
        self.assertNotIn("GH_TOKEN", self.json_text)
        post = self.dev["postCreateCommand"]
        self.assertLess(post.index("gh auth status"), post.index("toolchain:fetch"))
        self.assertIn("gh auth login", post)

    def test_post_create_stops_on_missing_login_or_failed_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            gh = bin_dir / "gh"
            gh.write_text('#!/bin/sh\nexit "$TEST_AUTH_RC"\n')
            gh.chmod(0o755)
            mise = bin_dir / "mise"
            mise.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALLS"\n'
                '[ "$*" != "run -q toolchain:fetch --release-only" ] || exit 17\n'
            )
            mise.chmod(0o755)
            calls = bin_dir / "calls"
            env = {
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "TEST_CALLS": str(calls),
            }
            for login_rc in (1, 0):
                with self.subTest(login_rc=login_rc):
                    calls.write_text("")
                    result = subprocess.run(
                        ["/bin/sh", "-c", self.dev["postCreateCommand"]],
                        env={**env, "TEST_AUTH_RC": str(login_rc)},
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    commands = ["trust /workspaces/cpp-standard"]
                    if login_rc:
                        self.assertEqual(result.returncode, 1)
                        self.assertIn("gh auth login", result.stderr)
                    else:
                        self.assertEqual(result.returncode, 17)
                        commands.append("run -q toolchain:fetch --release-only")
                    self.assertEqual(calls.read_text().splitlines(), commands)

    def test_the_devcontainer_uses_the_compose_service(self) -> None:
        self.assertEqual(self.dev["dockerComposeFile"], "compose.yaml")
        self.assertIn(f"  {self.dev['service']}:", self.compose_body)

    def test_the_workspace_is_mounted_where_workspaceFolder_points(self) -> None:
        # Compose devcontainers mount the workspace in the compose file, not through
        # devcontainer.json; `..` is the repository root this .devcontainer folder sits in.
        self.assertIn(f"..:{self.dev['workspaceFolder']}", self.compose_body)

    def test_the_service_runs_as_the_non_root_user(self) -> None:
        # The tools image's user (uid 1001, image/tools.Dockerfile), pinned in compose.
        self.assertIn("user: 1001:1001", self.compose_body)

    def test_no_privileged_run_anywhere(self) -> None:
        keys = self._keys(self.dev)
        for key in ("privileged", "runArgs", "capAdd", "securityOpt"):
            self.assertNotIn(key, keys)
        self.assertNotRegex(
            self.compose_body, r"(?m)^\s*(privileged|cap_add|security_opt):"
        )

    def test_sccache_lives_in_a_volume(self) -> None:
        self.assertIn("- sccache:/home/cppstd/.cache/sccache", self.compose_body)

    def test_the_service_stays_up(self) -> None:
        self.assertIn("command: sleep infinity", self.compose_body)

    def test_the_verify_task_takes_the_shorthand_and_the_flag(self) -> None:
        script = VERIFY_TASK.read_text()
        self.assertIn("base | tools)", script)
        self.assertIn('--env-file "${usage_env_file}"', script)
        self.assertIn('"$root/python/artifact/artifact.py" verify', script)


class VerifyTaskScript(unittest.TestCase):
    """.mise/tasks/image/verify run with the stand-in python3: `tools` expands to this commit's
    registry ref, --env-file reaches artifact.py, and a refusal fails naming the image (D93). The
    script runs with the usage_* variables mise exports for its #USAGE flags; hk's mise-tasks
    step validates that syntax."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bin = Path(tempfile.mkdtemp(prefix="devcontainer-test-"))
        stub = cls.bin / "python3"
        stub.write_text(STUB_PY)
        stub.chmod(0o755)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.bin, ignore_errors=True)

    def _run(
        self, tmp: Path, env_file: Path | None, refused: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
        log = tmp / "stub.log"
        env = os.environ.copy()
        env["PATH"] = f"{self.bin}:{env['PATH']}"
        env["MISE_PROJECT_ROOT"] = str(ROOT)
        env["STUB_ENV_VAR"] = artifact.DEVCONTAINER_ENV_VAR
        env["STUB_LOG"] = str(log)
        for name in ("usage_image", "usage_arch", "usage_env_file"):
            env.pop(name, None)
        env["usage_image"] = "tools"
        if refused:
            env["DEVCONTAINER_TEST_REFUSED"] = "1"
        if env_file is not None:
            env["usage_env_file"] = str(env_file)
        r = subprocess.run(
            ["bash", str(VERIFY_TASK)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        calls: list[list[str]] = []
        if log.exists():
            calls = [json.loads(line) for line in log.read_text().splitlines()]
        return r, calls

    def test_tools_expands_to_the_registry_ref_and_writes_the_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            env_file = tmp / "devcontainer" / ".env"
            r, calls = self._run(tmp, env_file)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(calls), 2, calls)
            pins, verify = calls
            self.assertTrue(pins[0].endswith("pins.py"))
            self.assertEqual(pins[pins.index("tag") + 1], "tools")
            arch = pins[pins.index("--arch") + 1]
            self.assertEqual(arch, HOST_ARCH)
            tag = f"tools-{arch}-0123456789abcdef"
            self.assertTrue(verify[0].endswith("artifact.py"))
            self.assertEqual(verify[verify.index("verify") + 1], f"{IMAGE}:{tag}")
            self.assertEqual(verify[verify.index("--env-file") + 1], str(env_file))
            self.assertEqual(
                env_file.read_text(),
                f"{artifact.DEVCONTAINER_ENV_VAR}={IMAGE}@sha256:{'c' * 64}\n",
            )

    def test_a_refusal_fails_naming_the_image(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            env_file = tmp / "devcontainer" / ".env"
            r, _ = self._run(tmp, env_file, refused=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("attestation refused", r.stderr)
            self.assertIn(IMAGE, r.stderr)
            self.assertFalse(env_file.exists())

    def test_the_env_file_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            r, calls = self._run(tmp, None)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(calls), 2, calls)
            self.assertNotIn("--env-file", calls[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
