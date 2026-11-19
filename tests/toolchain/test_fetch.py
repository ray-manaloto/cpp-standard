"""Tests of python/toolchain/fetch.py (ticket #130): each row of the source table, the staged copy
refused on main and outside Actions, release-only mode, the waiting job that never builds, the
duplicate-title refusal, and the install that never lets a refused archive in. The release store,
the verifier and the rebuild are fakes over small stand-in archives, so nothing here needs the
network, gh or a real toolchain. Run: python3 -I tests/toolchain/test_fetch.py
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python/toolchain"))
sys.path.insert(0, str(ROOT / "python/artifact"))

import artifact
import fetch

TAG = "p2996-linux-arm64-00112233445566aa"
HASH = "00112233445566aa"
HOSTED = {"RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_ACTIONS": "true"}


def make_archive(path: Path, content: str, inputs_hash: str | None = HASH) -> Path:
    """A stand-in toolchain archive: bin/marker holds `content`."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "bin").mkdir()
        (Path(d) / "bin/marker").write_text(content)
        if inputs_hash is not None:
            (Path(d) / fetch.HASH_FILE).write_text(inputs_hash + "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "--zstd", "-cf", str(path), "-C", d, "."], check=True)
    return path


def release_json(tag: str = TAG, title: str = TAG, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": title,
        "draft": draft,
        "assets": [{"name": f"{tag}.tar.zst"}],
    }


class FakeReleases:
    def __init__(self, archive: Path | None, listing: list[dict] | None = None) -> None:
        self.archive = archive
        self.listing = (
            listing if listing is not None else ([release_json()] if archive else [])
        )

    def find(self, tag: str) -> fetch.Release | None:
        return fetch.pick_release(tag, self.listing)

    def download(self, release: fetch.Release, asset: str, dest: Path) -> Path:
        assert self.archive is not None
        target = dest / asset
        target.write_bytes(self.archive.read_bytes())
        return target


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "installed"
        self.staged = self.tmp / "staged"
        self.rebuilt = 0
        self.log: list[str] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def rebuild_ok(self, tag: str) -> Path:
        self.rebuilt += 1
        return make_archive(self.tmp / "dist" / f"{tag}.tar.zst", "rebuilt")

    def rebuild_fails(self, tag: str) -> Path:
        self.rebuilt += 1
        raise subprocess.CalledProcessError(1, ["artifact:build", tag])

    def stage(self, content: str = "staged") -> None:
        make_archive(self.staged / TAG / f"{TAG}.tar.zst", content)

    def run_fetch(
        self, ctx: str, releases, verifier=lambda _: True, builder=None, **kw
    ):
        order = fetch.sources(fetch.Context(ctx), **kw)
        return fetch.fetch(
            TAG,
            self.root,
            order,
            releases,
            verifier,
            builder or self.rebuild_ok,
            self.staged,
            self.log.append,
        )

    def installed(self) -> str | None:
        marker = self.root / TAG / "bin/marker"
        return marker.read_text() if marker.exists() else None


class ContextTest(unittest.TestCase):
    def test_contexts(self) -> None:
        C = fetch.Context.from_env
        self.assertEqual(C({}).kind, "outside")
        pr = HOSTED | {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/7/merge",
        }
        self.assertEqual(C(pr).kind, "hosted_pr")
        mq = HOSTED | {
            "GITHUB_EVENT_NAME": "merge_group",
            "GITHUB_REF": "refs/heads/gh-readonly-queue/main/pr-7-" + "a" * 40,
        }
        self.assertEqual(C(mq).kind, "hosted_pr")
        for event in ("push", "workflow_dispatch", "schedule"):
            env = HOSTED | {"GITHUB_EVENT_NAME": event, "GITHUB_REF": "refs/heads/main"}
            self.assertEqual(C(env).kind, "actions", event)
        self.assertEqual(C(pr | {"RUNNER_ENVIRONMENT": "self-hosted"}).kind, "actions")
        # The name ci.yml sets; the runner's own RUNNER_ENVIRONMENT may be absent in a container.
        pr_ours = {k: v for k, v in pr.items() if k != "RUNNER_ENVIRONMENT"}
        self.assertEqual(C(pr_ours).kind, "actions")
        ours = pr_ours | {"CPPSTD_RUNNER_ENVIRONMENT": "github-hosted"}
        self.assertEqual(C(ours).kind, "hosted_pr")

    def test_source_table(self) -> None:
        S = fetch.sources
        self.assertEqual(
            S(fetch.Context("hosted_pr")), ["release", "staged", "rebuild"]
        )
        self.assertEqual(S(fetch.Context("actions")), ["release", "rebuild"])
        self.assertEqual(S(fetch.Context("outside")), ["release", "rebuild"])
        for kind in ("hosted_pr", "actions", "outside"):
            self.assertEqual(S(fetch.Context(kind), release_only=True), ["release"])
        self.assertEqual(
            S(fetch.Context("hosted_pr"), rebuild=False), ["release", "staged"]
        )


class RowTest(Case):
    """One test per row of the source table, and the staged copy refused on main and outside."""

    def test_pr_row_release_first(self) -> None:
        self.stage()
        rel = FakeReleases(make_archive(self.tmp / "r.tar.zst", "release"))
        r = self.run_fetch("hosted_pr", rel)
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("release", "release", 0)
        )

    def test_pr_row_staged_before_rebuild(self) -> None:
        self.stage()
        r = self.run_fetch("hosted_pr", FakeReleases(None))
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("staged", "staged", 0)
        )

    def test_pr_row_rebuild_last(self) -> None:
        r = self.run_fetch("hosted_pr", FakeReleases(None))
        self.assertEqual(
            (r.source, self.installed(), self.rebuilt), ("rebuild", "rebuilt", 1)
        )

    def test_main_and_outside_never_take_a_staged_copy(self) -> None:
        for ctx in ("actions", "outside"):
            with self.subTest(ctx):
                self.stage()
                r = self.run_fetch(ctx, FakeReleases(None))
                self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))

    def test_main_and_outside_take_the_release(self) -> None:
        rel = FakeReleases(make_archive(self.tmp / "r.tar.zst", "release"))
        for ctx in ("actions", "outside"):
            with self.subTest(ctx):
                self.root = self.tmp / f"installed-{ctx}"  # a fresh install root each
                r = self.run_fetch(ctx, rel)
                self.assertEqual((r.source, self.installed()), ("release", "release"))
        self.assertEqual(self.rebuilt, 0)

    def test_staged_copy_with_wrong_hash_is_refused(self) -> None:
        make_archive(
            self.staged / TAG / f"{TAG}.tar.zst", "staged", inputs_hash="f" * 16
        )
        r = self.run_fetch("hosted_pr", FakeReleases(None))
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("inputs-hash.txt", r.refusals[0])


class ReleaseOnlyTest(Case):
    def test_release_only_installs_the_release(self) -> None:
        self.stage()
        rel = FakeReleases(make_archive(self.tmp / "r.tar.zst", "release"))
        r = self.run_fetch("actions", rel, release_only=True)
        self.assertEqual((r.source, self.installed()), ("release", "release"))

    def test_release_only_never_falls_back(self) -> None:
        self.stage()
        r = self.run_fetch("hosted_pr", FakeReleases(None), release_only=True)
        self.assertIsNone(r.prefix)
        self.assertEqual((self.installed(), self.rebuilt), (None, 0))


class WaitTest(Case):
    """A job that waits for the staged copy fails when the wait ends without one and never
    builds: artifact-check's wait for the toolchain tag ends missing, and the job's fetch, which
    runs with the rebuild off, installs nothing."""

    def test_short_wait_then_no_build(self) -> None:
        now = [0.0]
        clock = artifact.Clock(
            now=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)
        )

        class Nothing:
            def digest(self, _ref: str) -> None:
                return None

            def where(self, _tag: str) -> None:
                return None

        missing = artifact.check(
            [TAG],
            Nothing(),
            7,
            True,
            timeout=3,
            interval=1,
            clock=clock,
            log=self.log.append,
            toolchains=Nothing(),
        )
        self.assertEqual(missing, [TAG])
        r = self.run_fetch("hosted_pr", FakeReleases(None), rebuild=False)
        self.assertIsNone(r.prefix)
        self.assertEqual(self.rebuilt, 0)


class RefusalTest(Case):
    """The refusal cases of spec #122's table, on the code path used outside Actions."""

    def test_unattested_release_then_rebuild_installs_the_rebuilt_one(self) -> None:
        make_archive(self.root / "seed.tar.zst", "before")
        fetch.install(self.root / "seed.tar.zst", TAG, self.root)
        rel = FakeReleases(make_archive(self.tmp / "r.tar.zst", "refused"))
        r = self.run_fetch("outside", rel, verifier=lambda _: False)
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("attestation", r.refusals[0])

    def test_unattested_release_and_no_rebuild_leaves_the_old_one(self) -> None:
        make_archive(self.root / "seed.tar.zst", "before")
        fetch.install(self.root / "seed.tar.zst", TAG, self.root)
        rel = FakeReleases(make_archive(self.tmp / "r.tar.zst", "refused"))
        r = self.run_fetch(
            "outside", rel, verifier=lambda _: False, builder=self.rebuild_fails
        )
        self.assertIsNone(r.prefix)
        self.assertEqual((self.installed(), self.rebuilt), ("before", 1))

    def test_attested_release_with_wrong_inputs_hash_is_refused(self) -> None:
        rel = FakeReleases(
            make_archive(self.tmp / "r.tar.zst", "wrong", inputs_hash="e" * 16)
        )
        r = self.run_fetch("outside", rel)
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("inputs-hash.txt", r.refusals[0])

    def test_archive_without_inputs_hash_is_refused(self) -> None:
        rel = FakeReleases(
            make_archive(self.tmp / "r.tar.zst", "none", inputs_hash=None)
        )
        r = self.run_fetch("outside", rel, release_only=True)
        self.assertIsNone(r.prefix)
        self.assertIsNone(self.installed())

    def test_corrupt_archive_is_refused(self) -> None:
        bad = self.tmp / "r.tar.zst"
        bad.write_bytes(b"not an archive")
        r = self.run_fetch("outside", FakeReleases(bad), release_only=True)
        self.assertIsNone(r.prefix)
        self.assertIn("does not extract", r.refusals[0])


class DuplicateTitleTest(Case):
    def test_two_releases_with_the_title_are_refused(self) -> None:
        listing = [release_json(), release_json(tag="decoy", title=TAG)]
        rel = FakeReleases(make_archive(self.tmp / "r.tar.zst", "release"), listing)
        r = self.run_fetch("outside", rel)
        self.assertEqual((r.source, self.installed()), ("rebuild", "rebuilt"))
        self.assertIn("2 releases match", r.refusals[0])

    def test_pick_release(self) -> None:
        P = fetch.pick_release
        self.assertIsNone(P(TAG, []))
        self.assertIsNone(P(TAG, [release_json(draft=True)]))
        self.assertEqual(P(TAG, [release_json(), release_json(draft=True)]).tag, TAG)
        with self.assertRaises(fetch.Refused):
            P(TAG, [release_json(title="something else")])
        with self.assertRaises(fetch.Refused):
            P(TAG, [release_json(), release_json(tag="other", title=TAG)])

    def test_release_without_the_archive_is_refused(self) -> None:
        listing = [release_json() | {"assets": []}]
        r = self.run_fetch(
            "outside", FakeReleases(self.tmp / "x", listing), release_only=True
        )
        self.assertIsNone(r.prefix)
        self.assertIn("has no", r.refusals[0])


class InstallTest(Case):
    def test_reinstall_replaces(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        fetch.install(make_archive(self.tmp / "b.tar.zst", "two"), TAG, self.root)
        self.assertEqual(self.installed(), "two")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [TAG])

    def test_failed_swap_puts_the_old_install_back(self) -> None:
        fetch.install(make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root)
        real = Path.rename
        dest = self.root / TAG

        def rename(src: Path, target):  # the new tree's move into place fails
            if Path(target) == dest and src.name.startswith(f".{TAG}.new-"):
                raise OSError("simulated")
            return real(src, target)

        with mock.patch.object(Path, "rename", rename), self.assertRaises(OSError):
            fetch.install(make_archive(self.tmp / "b.tar.zst", "two"), TAG, self.root)
        self.assertEqual(self.installed(), "one")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [TAG])

    def test_installed_prefix_is_readable(self) -> None:
        prefix = fetch.install(
            make_archive(self.tmp / "a.tar.zst", "one"), TAG, self.root
        )
        self.assertEqual(prefix.stat().st_mode & 0o777, 0o755)

    def test_unknown_machine(self) -> None:
        with (
            mock.patch.object(fetch.platform, "machine", return_value="armv7l"),
            self.assertRaises(fetch.FetchError),
        ):
            fetch.host_arch()
        with mock.patch.object(fetch.platform, "machine", return_value="aarch64"):
            self.assertEqual(fetch.host_arch(), "arm64")

    def test_not_a_toolchain_tag(self) -> None:
        with self.assertRaises(fetch.FetchError):
            fetch.tag_hash("tools-arm64-0011223344556677")


class SourceErrorTest(Case):
    """A release source that cannot be asked is never read as "no release" (#130 review)."""

    class Broken:
        def find(self, tag: str):
            raise fetch.SourceError("gh api could not list the releases: HTTP 401")

    def test_outside_actions_stops_without_rebuilding(self) -> None:
        order = fetch.sources(fetch.Context("outside"))
        r = fetch.fetch(
            TAG,
            self.root,
            order,
            self.Broken(),
            lambda _: True,
            self.rebuild_ok,
            self.staged,
            self.log.append,
            stop_on_source_error=True,
        )
        self.assertIsNone(r.prefix)
        self.assertEqual(self.rebuilt, 0)
        self.assertIn("HTTP 401", r.errors[0])
        self.assertTrue(any("stopping, no rebuild" in x for x in self.log))

    def test_in_actions_the_next_source_follows_a_warning(self) -> None:
        self.stage()
        order = fetch.sources(fetch.Context("hosted_pr"), rebuild=False)
        r = fetch.fetch(
            TAG,
            self.root,
            order,
            self.Broken(),
            lambda _: True,
            self.rebuild_ok,
            self.staged,
            self.log.append,
        )
        self.assertEqual((r.source, self.installed()), ("staged", "staged"))
        self.assertTrue(any(x.startswith("::warning::") for x in self.log))

    def test_gh_api_failure_is_a_source_error(self) -> None:
        def run(cmd, **kw):
            raise subprocess.CalledProcessError(1, cmd, "", "HTTP 401: Bad credentials")

        with (
            mock.patch.object(fetch.subprocess, "run", run),
            self.assertRaises(fetch.SourceError) as e,
        ):
            fetch.GhReleases().find(TAG)
        self.assertIn("gh auth login", str(e.exception))

    def test_no_gh_and_bad_output_are_source_errors(self) -> None:
        def missing(cmd, **kw):
            raise FileNotFoundError("gh")

        def garbage(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "not json", "")

        for run in (missing, garbage):
            with (
                mock.patch.object(fetch.subprocess, "run", run),
                self.assertRaises(fetch.SourceError),
            ):
                fetch.GhReleases().find(TAG)


class GhBoundaryTest(unittest.TestCase):
    """The gh calls themselves, with subprocess.run replaced: the verify policy, paging of the
    release listing, and main()'s flags (#130 review)."""

    def test_verify_policy_and_verdict(self) -> None:
        calls: list[list[str]] = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404")

        path = Path("/tmp/downloaded/x.tar.zst")
        with mock.patch.object(fetch.subprocess, "run", run):
            ok, out = fetch.gh_verify_report(path)
            self.assertFalse(fetch.gh_verify(path))
        self.assertFalse(ok)
        self.assertIn("HTTP 404", out)
        cmd = calls[0]
        self.assertEqual(cmd[:4], ["gh", "attestation", "verify", str(path)])
        flags = dict(zip(cmd[4::2], cmd[5::2], strict=False))
        self.assertEqual(
            flags["--signer-workflow"],
            "ray-manaloto/cpp-standard/.github/workflows/publish.yml",
        )
        self.assertEqual(flags["--source-ref"], "refs/heads/main")
        self.assertEqual(flags["--repo"], "ray-manaloto/cpp-standard")
        self.assertIn("--deny-self-hosted-runners", cmd)

    def test_verify_passes_on_exit_zero(self) -> None:
        def run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with mock.patch.object(fetch.subprocess, "run", run):
            self.assertTrue(fetch.gh_verify(Path("x")))

    def find(self, pages: list) -> fetch.Release | None:
        def run(cmd, **kw):
            self.assertIn("--paginate", cmd)
            self.assertIn("--slurp", cmd)
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pages), "")

        with mock.patch.object(fetch.subprocess, "run", run):
            return fetch.GhReleases().find(TAG)

    def test_find_on_the_second_page(self) -> None:
        page1 = [release_json(tag=f"other-{i}", title=f"other-{i}") for i in range(100)]
        self.assertEqual(self.find([page1, [release_json()]]).tag, TAG)

    def test_find_duplicate_across_pages(self) -> None:
        with self.assertRaises(fetch.Refused):
            self.find([[release_json()], [release_json(tag="decoy", title=TAG)]])

    def test_find_no_releases(self) -> None:
        self.assertIsNone(self.find([[]]))

    def test_download_names_the_release_and_asset(self) -> None:
        calls: list[list[str]] = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        rel = fetch.Release(TAG, TAG, (f"{TAG}.tar.zst",))
        with mock.patch.object(fetch.subprocess, "run", run):
            got = fetch.GhReleases().download(rel, f"{TAG}.tar.zst", Path("/d"))
        self.assertEqual(got, Path("/d") / f"{TAG}.tar.zst")
        self.assertEqual(calls[0][:4], ["gh", "release", "download", TAG])
        self.assertIn(f"{TAG}.tar.zst", calls[0])


class MainTest(unittest.TestCase):
    """main(): the flags map to the source table; nothing installed exits 1."""

    def run_main(self, argv: list[str], result: fetch.Result, env: dict[str, str]):
        seen = {}

        def fake_fetch(tag, root, order, *rest, **kw):
            seen["order"] = order
            return result

        with (
            mock.patch.object(fetch, "compute_tag", return_value=TAG),
            mock.patch.object(fetch, "fetch", fake_fetch),
            mock.patch.dict(fetch.os.environ, env, clear=True),
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            rc = fetch.main([*argv, "--arch", "arm64", "--root", "/tmp/r"])
        return rc, seen["order"], out.getvalue()

    def test_release_only(self) -> None:
        pr = HOSTED | {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/7/merge",
        }
        rc, order, _ = self.run_main(["--release-only"], fetch.Result(), pr)
        self.assertEqual((rc, order), (1, ["release"]))

    def test_no_rebuild(self) -> None:
        pr = HOSTED | {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/7/merge",
        }
        rc, order, _ = self.run_main(["--no-rebuild"], fetch.Result(), pr)
        self.assertEqual((rc, order), (1, ["release", "staged"]))

    def test_outside_default_and_success_output(self) -> None:
        done = fetch.Result(prefix=Path("/tmp/r") / TAG, source="release")
        rc, order, out = self.run_main([], done, {})
        self.assertEqual((rc, order), (0, ["release", "rebuild"]))
        self.assertIn(f"prefix=/tmp/r/{TAG}", out)
        self.assertIn("source=release", out)


if __name__ == "__main__":
    unittest.main()
