"""Exercise PC compiler identity, retained archives and fallback without Docker or GitHub."""

import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "docs/standard/gha-runner"
CACHE = runpy.run_path(str(SCRIPTS / "pc-compiler-cache.py"))


class CompilerCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "store"
        self.transfer = self.root / "transfer"
        for path in (self.store / "packages", self.transfer, self.root / "result"):
            path.mkdir(parents=True)
        self.identity = self.transfer / "inputs.json"
        self.identity.write_text('{"recipe":"abc"}\n')
        self.key = CACHE["sha"](self.identity)
        self.entry = self.store / "packages" / self.key

    def test_key_ignores_checkout_and_tracks_actual_build_inputs(self):
        recipe = self.root / CACHE["RECIPE"]
        shutil.copytree(ROOT / CACHE["RECIPE"], recipe)
        tool = self.root / "compiler"
        tool.write_bytes(b"locked tool")
        packages = "ii \tclang-23\t1\tlibc6 | provider, flavor\t\nii \tlibc6\t1\t\t\nii \tprovider\t2\t\tflavor\nii \teditor\t1\t\t\n"

        def output(args, **kwargs):
            return str(tool) if args[0] == "clang-23" else packages

        def key():
            result = CACHE["inputs"](
                self.root, "sha256:" + "1" * 64, "sha256:" + "2" * 64
            )
            return hashlib.sha256(
                json.dumps(result, sort_keys=True).encode()
            ).hexdigest()

        with (
            patch("subprocess.check_output", side_effect=output),
            patch("shutil.which", return_value=str(tool)),
        ):
            first = key()
            (self.root / "project.cpp").write_text("project-only change")
            packages = packages.replace("editor\t1", "editor\t2")
            self.assertEqual(key(), first)
            packages = packages.replace("provider\t2", "provider\t3")
            second = key()
            self.assertNotEqual(second, first)
            with (recipe / "lldb-base-specifier-derived.patch").open("a") as f:
                f.write("changed patch")
            third = key()
            self.assertNotEqual(third, second)
            tool.write_bytes(b"changed tool")
            self.assertNotEqual(key(), third)

    def resolve(self, lookup="absent", reason="", fail=False):
        return subprocess.run(
            [
                "bash",
                "-euo",
                "pipefail",
                "-c",
                """
source "$scripts/pc-compiler-store.sh"
compiler_cache() { echo remote >>"$state/calls"; echo "$lookup"; return "$rc"; }
resolve_compiler_package
""",
            ],
            env={
                **os.environ,
                "scripts": str(SCRIPTS),
                "compiler_store": str(self.store),
                "transfer": str(self.transfer),
                "result": str(self.root / "result"),
                "state": str(self.root),
                "cold_reason": reason,
                "seed_run": "",
                "TOKEN": "fixture",
                "lookup": lookup,
                "rc": "1" if fail else "0",
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_local_hits_before_registry_and_never_rebuilds_on_errors(self):
        self.entry.mkdir()
        decision = self.transfer / "decision"
        proc = self.resolve(fail=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(decision.read_text().strip(), "local")
        self.assertFalse((self.root / "calls").exists())
        self.entry.rmdir()
        for lookup, reason, fail, mode in (
            ("absent", "", False, "unavailable"),
            ("absent", "changed recipe", False, "cold"),
            ("sha256:" + "a" * 64, "", False, "registry"),
            ("401", "changed recipe", True, None),
            ("unknown", "changed recipe", False, None),
        ):
            with self.subTest(mode=mode, lookup=lookup):
                decision.unlink(missing_ok=True)
                proc = self.resolve(lookup, reason, fail)
                if mode:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(decision.read_text().strip(), mode)
                else:
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertFalse(decision.exists())

    def test_archive_round_trip_and_refusal(self):
        prefix = self.root / "old/p2996"
        binary = prefix / "bin/clang"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"compiled prefix fixture")
        binary.chmod(0o755)
        (binary.parent / "clang++").symlink_to("clang")
        receipt = CACHE["pack"](self.identity, prefix, self.entry)
        archive = CACHE["verify"](self.identity, self.entry)
        self.assertEqual(receipt["archive_sha256"], CACHE["sha"](archive))
        installed = self.root / "new"
        installed.mkdir()
        process = subprocess.run(
            [
                os.sys.executable,
                "-I",
                str(SCRIPTS / "pc-compiler-cache.py"),
                "restore",
                self.identity,
                self.entry,
                installed,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(
            (installed / "p2996/bin/clang++").read_bytes(), binary.read_bytes()
        )
        self.assertTrue((installed / "p2996/bin/clang++").is_symlink())
        self.assertTrue(os.access(installed / "p2996/bin/clang", os.X_OK))
        changed = self.root / "other.json"
        changed.write_bytes(b"other inputs")
        other = self.root / "other"
        CACHE["pack"](changed, prefix, other)
        wrong = next(other.glob("*.tar.zst"))
        shutil.copyfile(wrong, archive)
        (self.entry / "package.json").write_text(
            json.dumps(
                {"inputs_sha256": self.key, "archive_sha256": CACHE["sha"](archive)}
            )
        )
        with self.assertRaisesRegex(ValueError, "compiler identity|compiler inputs"):
            CACHE["verify"](self.identity, self.entry)
        with archive.open("ab") as f:
            f.write(b"corruption")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            CACHE["verify"](self.identity, self.entry)

    def test_cache_mounts_are_private_to_build_and_project(self):
        launcher = (SCRIPTS / "pc-compiler-once.sh").read_text()
        listener = launcher.split('docker run -d --name "$runner"', 1)[1].split(
            "unset jit", 1
        )[0]
        build = launcher.split(
            'docker create --platform linux/amd64 --name "$build"', 1
        )[1].split("seed_compiler_ca", 1)[0]
        project = launcher.split('docker create --name "$name"', 1)[1].split(
            "project.cid", 1
        )[0]
        timed = launcher.split("35m env -i", 1)[1].split("certify_compiler_project", 1)[
            0
        ]
        mount = "src=$compiler_store/sccache,dst=/cache/sccache"
        self.assertIn(mount, build)
        self.assertIn(mount, project)
        self.assertIn("dst=/root/.cache/mise/downloads-cas", build)
        for isolated in (listener, timed):
            self.assertNotIn("src=$compiler_store", isolated)
        self.assertNotIn(
            "compiler_store",
            launcher.split("release_compiler_workload() {", 1)[1].split(
                "remove_compiler_container() {", 1
            )[0],
        )

    def test_published_oci_round_trip_requires_provenance(self):
        prefix = self.root / "old/p2996"
        prefix.mkdir(parents=True)
        (prefix / "compiler").write_bytes(b"installed compiler")
        receipt = CACHE["pack"](self.identity, prefix, self.entry)
        stage = self.root / "stage"
        CACHE["publish_files"](self.identity, self.entry, stage)
        digest = (stage / "image.txt").read_text().split("digest=")[1].strip()
        sys.path.insert(0, str(ROOT / "python/toolchain"))
        self.addCleanup(sys.path.remove, str(ROOT / "python/toolchain"))
        import fetch

        name = CACHE["tag"](self.key)
        ref = fetch.artifact.names(name)["ref"]
        subject = ref.rpartition(":")[0] + "@" + digest
        target = self.root / "other-store"
        target.mkdir()
        with (
            tarfile.open(stage / "image.tar") as archive,
            patch.object(fetch.artifact, "Registry") as registry,
            patch.object(fetch, "gh_verify", return_value=False) as attest,
        ):
            client = registry.return_value
            client.digest.return_value = digest
            with self.assertRaisesRegex(ValueError, "refused publisher"):
                CACHE["remote"](self.identity, target)
            client.manifest_bytes.assert_not_called()
            attest.assert_called_once_with("oci://" + subject)
            attest.return_value = True
            manifest = archive.extractfile("blobs/sha256/" + digest[7:]).read()
            client.manifest_bytes.return_value = manifest

            def blob(at_digest, layer, dest):
                self.assertEqual(at_digest, subject)
                self.assertEqual(layer, json.loads(manifest)["layers"][0]["digest"])
                dest.write_bytes(
                    archive.extractfile("blobs/sha256/" + layer[7:]).read()
                )
                return dest

            client.blob.side_effect = blob
            self.assertEqual(CACHE["remote"](self.identity, target), digest)
            client.digest.assert_called_with(ref)
            client.manifest_bytes.assert_called_once_with(subject)
        cached = target / self.key
        self.assertEqual((cached / "registry-digest").read_text().strip(), digest)
        self.assertEqual(
            CACHE["sha"](CACHE["verify"](self.identity, cached)),
            receipt["archive_sha256"],
        )

    def test_protected_publisher_admits_only_dedicated_package(self):
        workflow = (ROOT / ".github/workflows/publish.yml").read_text()
        body = workflow.split("          refuse() {", 1)[1].split("\n  image:", 1)[0]
        script = (
            """set -eu -o pipefail
gh() {
  case "$2" in
    */attempts/1/jobs) cat jobs ;;
    */artifacts) cat artifacts ;;
    */compare/*) echo ahead ;;
    */actions/runs/1) cat producer ;;
    *) exit 1 ;;
  esac
}
refuse() {"""
            + body
        )
        sha = "a" * 40
        package = "toolchain-p2996-pc-linux-amd64-" + "f" * 16
        repo = "ray-manaloto/cpp-standard"
        env = {
            **os.environ,
            "GITHUB_REPOSITORY": repo,
            "RUN_ID": "1",
            "REF": "refs/heads/main",
            "GITHUB_OUTPUT": str(self.root / "out"),
        }
        for group, attempt, upload, path, artifacts, accept in (
            (6, 1, "success", "pc-compiler", [package, "ubuntu-amd64-1-1"], True),
            (5, 1, "success", "pc-compiler", [package], False),
            (6, 2, "success", "pc-compiler", [package], False),
            (6, 1, "skipped", "pc-compiler", [package], False),
            (
                6,
                1,
                "success",
                "pc-compiler",
                [package, "image-tools-amd64-" + "1" * 16],
                False,
            ),
            (6, 1, "success", "builder", [package], False),
        ):
            with self.subTest(
                group=group,
                attempt=attempt,
                upload=upload,
                path=path,
                artifacts=artifacts,
            ):
                producer = {
                    "path": f".github/workflows/{path}.yml",
                    "event": "workflow_dispatch",
                    "run_attempt": attempt,
                    "head_sha": sha,
                    "head_branch": "main",
                    "head_repository": {"full_name": repo},
                }
                job = {
                    "name": "Build and certify Ubuntu amd64",
                    "head_sha": sha,
                    "runner_group_id": group,
                    "runner_id": 740,
                    "conclusion": "failure",
                    "steps": [
                        {
                            "name": "Verify admitted runner and isolated mounts",
                            "conclusion": "success",
                        },
                        {
                            "name": "Stage verified compiler package",
                            "conclusion": "success",
                        },
                        {
                            "name": "Upload verified compiler package",
                            "conclusion": upload,
                        },
                    ],
                }
                for file, data in (
                    ("producer", producer),
                    ("jobs", {"total_count": 1, "jobs": [job]}),
                    ("artifacts", [{"artifacts": [{"name": n} for n in artifacts]}]),
                ):
                    (self.root / file).write_text(json.dumps(data))
                proc = subprocess.run(
                    ["bash", "-c", script],
                    check=False,
                    cwd=self.root,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    proc.returncode == 0, accept, proc.stdout + proc.stderr
                )


if __name__ == "__main__":
    unittest.main()
