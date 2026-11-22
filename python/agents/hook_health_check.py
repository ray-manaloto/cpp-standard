"""Deterministic publisher checks. Set CODEX_HOOK_FIXTURE_BINARY for native coverage."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

# The repository's coverage runner uses python -I.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_health import (
    Expected,
    HookCheckError,
    NativeSocket,
    PublishPlan,
    RetainedFile,
    _discover,
    _entry_identity,
    check,
    guarded_publish,
    publish_bundle,
    reviewed_root_bundle_digest,
)

PLUGIN = "fixture@local"
KEY = PLUGIN + ":hooks.json:stop:0:0"
HASH = "sha256:declaration/sha256:bundle"
SOURCE = "https://example.invalid/fixture.git"


class SkillSetupTest(unittest.TestCase):
    def test_macos_setup_exposes_hook_health(self):
        root = Path(__file__).resolve().parents[2]
        with (root / "mise.mac.toml").open("rb") as stream:
            links = tomllib.load(stream)["dotfiles"]
        source = "unix/home/.config/agents/skills/codex-hook-health"
        for target in ("~/.agents/skills", "~/.config/agents/skills"):
            with self.subTest(target=target):
                link = links[f"{target}/codex-hook-health"]
                self.assertEqual(link["mode"], "symlink")
                self.assertEqual(
                    (root / link["source"]).resolve(), (root / source).resolve()
                )
        skill = (root / source / "SKILL.md").read_text().split("---", 2)
        self.assertEqual(skill[0], "")
        self.assertIn("name: codex-hook-health", skill[1].splitlines())

    def test_native_task_finds_worktree_with_inherited_git_dir(self):
        root = Path(__file__).resolve().parents[2]
        git_dir = subprocess.check_output(
            ["git", "rev-parse", "--absolute-git-dir"], cwd=root, text=True
        ).strip()
        with tempfile.TemporaryDirectory() as temporary:
            scratch = Path(temporary)
            python = scratch / "python3"
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            result = subprocess.run(
                [root / ".mise/tasks/agents/hook-native"],
                cwd=scratch,
                env={
                    "PATH": os.pathsep.join((temporary, os.defpath)),
                    "GIT_DIR": git_dir,
                    "CODEX_HOOK_FIXTURE_BINARY": str(python),
                },
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        self.assertEqual(
            result.stdout.splitlines(),
            ["-I", str(Path(__file__).resolve()), "NativeTest", "-v"],
        )


def make_bundle(path):
    path.mkdir(parents=True)
    (path / ".codex-plugin").mkdir()
    (path / ".codex-plugin/plugin.json").write_text(
        json.dumps({"name": "fixture", "version": path.name, "hooks": "./hooks.json"})
    )
    (path / "hooks.json").write_text(
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "false"}]}]}}
        )
    )
    (path / "stop.py").write_text("# fixture\n")


def fixture_git(checkout, *args):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Fixture",
        GIT_AUTHOR_EMAIL="fixture@example.invalid",
        GIT_COMMITTER_NAME="Fixture",
        GIT_COMMITTER_EMAIL="fixture@example.invalid",
    )

    return subprocess.check_output(
        ["git", "-C", checkout, *args], env=env, text=True, timeout=10
    ).strip()


def fixture_revision(checkout, *, init=False):
    if init:
        fixture_git(checkout, "init", "-q", "--template=")
    fixture_git(
        checkout, "add", "-A", "--", ".", ":(exclude).codex-marketplace-install.json"
    )
    tree = fixture_git(checkout, "write-tree")
    revision = fixture_git(checkout, "commit-tree", tree, "-m", "Reviewed fixture")
    receipt = checkout / ".codex-marketplace-install.json"
    receipt.write_text(
        json.dumps(
            {
                "source_type": "git",
                "source": SOURCE,
                "ref_name": revision,
                "revision": revision,
                "sparse_paths": [],
            }
        )
    )
    return receipt, revision


def make_receipt(home, staged_bundle):
    checkout = home / ".tmp/marketplaces/local"
    manifest = checkout / ".agents/plugins/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "name": "local",
                "plugins": [
                    {
                        "name": "fixture",
                        "source": {"source": "local", "path": "./plugins/fixture"},
                    }
                ],
            }
        )
    )
    shutil.copytree(staged_bundle, checkout / "plugins/fixture")
    return fixture_revision(checkout, init=True)


def row(bundle, **updates):
    return {
        "key": KEY,
        "pluginId": PLUGIN,
        "enabled": True,
        "trustStatus": "trusted",
        "source": "plugin",
        "sourcePath": str(bundle / "hooks.json"),
        "currentHash": HASH,
        **updates,
    }


def result(cwd, *rows, warnings=()):
    return {
        "data": [
            {
                "cwd": str(cwd),
                "hooks": list(rows),
                "errors": [],
                "warnings": list(warnings),
            }
        ]
    }


class StagingTestCase(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)


class PublicationTest(StagingTestCase):
    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.live = self.root / "live" / "plugins/cache/local/fixture"
        self.stage = self.root / "stage" / "plugins/cache/local/fixture/2.0.0"
        self.new = self.live / "2.0.0"
        self.old = self.live / "1.0.0"
        make_bundle(self.stage)
        self.receipt, revision = make_receipt(self.root / "stage", self.stage)
        make_bundle(self.old)
        self.old_file = self.old / "stop.py"
        self.retained = RetainedFile(
            self.old_file,
            hashlib.sha256(self.old_file.read_bytes()).hexdigest(),
            self.old_file.stat().st_mode & 0o7777,
        )
        self.plan = PublishPlan(
            self.root,
            self.live,
            Expected(PLUGIN, self.stage, {KEY: HASH}),
            Expected(PLUGIN, self.new, {KEY: HASH}),
            SOURCE,
            revision,
            (self.new,),
            {"resume-old": (self.retained,)},
        )
        self.stage_probe = Mock(
            home=self.root / "stage", return_value=result(self.root, row(self.stage))
        )
        self.other = row(self.old, key="unrelated", pluginId=None, source="user")
        self.live_probe = Mock(
            home=self.root / "live",
            side_effect=[
                result(self.root, self.other),
                result(self.root, self.other, row(self.new)),
            ],
        )
        self.publisher = Mock(side_effect=lambda: self.stage.rename(self.new))

    def assert_holds(self, reason, **overrides):
        with self.assertRaisesRegex(HookCheckError, "^" + reason + "$"):
            guarded_publish(
                replace(self.plan, **overrides),
                self.stage_probe,
                self.live_probe,
                self.publisher,
            )
        self.publisher.assert_not_called()
        self.assertFalse(self.new.exists())

    def test_additive_publication_preserves_retained_bytes(self):
        publish_bundle(self.plan, self.stage_probe, self.live_probe)
        self.assertTrue(self.new.is_dir())
        self.assertEqual(self.old_file.read_text(), "# fixture\n")
        self.assertEqual(self.live_probe.call_count, 2)

    def test_additive_publication_holds_before_an_inactive_or_unqualified_move(self):
        for version, reason in (
            ("local", "destination_would_be_inactive"),
            ("10.0.0", "destination_would_be_inactive"),
            ("required-fallback", "additive_version_unqualified"),
        ):
            with self.subTest(version=version):
                directory = self.live / version
                directory.mkdir()
                with self.assertRaisesRegex(HookCheckError, "^" + reason + "$"):
                    publish_bundle(self.plan, self.stage_probe, self.live_probe)
                directory.rmdir()
                self.assertTrue(self.stage.is_dir())
                self.assertFalse(self.new.exists())
        self.stage_probe.assert_not_called()
        self.live_probe.assert_not_called()

    def test_external_symlink_is_held_before_publication(self):
        alias = self.stage / "alias.py"
        for target in (self.old_file, Path("../2.0.0/stop.py")):
            with self.subTest(target=target):
                alias.symlink_to(target)
                with self.assertRaisesRegex(
                    HookCheckError, "^nonportable_bundle_symlink$"
                ):
                    publish_bundle(self.plan, self.stage_probe, self.live_probe)
                alias.unlink()
        self.stage_probe.assert_not_called()
        self.assertFalse(self.new.exists())

    def test_custom_publisher_cannot_move_a_staging_only_link(self):
        venv = self.stage / ".venv"
        venv.mkdir()
        (self.stage.parent / "alias").symlink_to(self.stage)
        (venv / "link").symlink_to("../../alias/stop.py")
        self.assert_holds("nonportable_bundle_symlink")

    def test_stage_bundle_cannot_be_a_resume_dependency(self):
        target = self.stage / "stop.py"
        receipt = RetainedFile(
            target,
            hashlib.sha256(target.read_bytes()).hexdigest(),
            target.stat().st_mode & 0o777,
        )
        self.assert_holds(
            "publication_overlaps_retained_path", retained={"resumed": (receipt,)}
        )

    def test_approved_existing_hash_is_preserved_on_noop(self):
        shutil.copytree(self.stage, self.new)
        self.live_probe.side_effect = None
        self.live_probe.return_value = result(self.root, self.other, row(self.new))
        guarded_publish(self.plan, self.stage_probe, self.live_probe, lambda: None)
        self.assertEqual(self.live_probe.call_count, 2)
        self.assertEqual((self.new / "stop.py").read_text(), "# fixture\n")

    def test_existing_version_has_no_overwrite(self):
        shutil.copytree(self.stage, self.new)
        with self.assertRaisesRegex(HookCheckError, "^destination_already_exists$"):
            publish_bundle(self.plan, self.stage_probe, self.live_probe)
        self.assertTrue(self.stage.is_dir())
        self.assertTrue(self.new.is_dir())

    def test_same_declaration_changed_bundle_holds(self):
        for trust, reason in (
            ("modified", "hook_not_enabled_and_trusted"),
            ("trusted", "hook_hash_changed"),
        ):
            with self.subTest(trust=trust):
                self.live_probe.side_effect = None
                self.live_probe.return_value = result(self.root, self.other)
                self.stage_probe.return_value = result(
                    self.root,
                    row(
                        self.stage,
                        trustStatus=trust,
                        currentHash="sha256:declaration/sha256:changed",
                    ),
                )
                self.assert_holds(reason)

    def test_new_approval_for_same_key_cannot_replace_live_approval(self):
        self.live_probe.side_effect = [
            result(self.root, row(self.old, currentHash="prior-approval"))
        ]
        self.assert_holds("live_approval_would_change")

    def test_empty_discovery_and_warning_hold(self):
        self.stage_probe.return_value = result(self.root)
        self.assert_holds("hook_inventory_mismatch")
        self.live_probe.side_effect = [result(self.root, self.other)]
        self.stage_probe.return_value = result(
            self.root, row(self.stage), warnings=["redacted"]
        )
        self.assert_holds("incomplete_discovery")

    def test_duplicate_and_disabled_rows_hold(self):
        self.live_probe.side_effect = None
        self.live_probe.return_value = result(self.root, self.other)
        self.stage_probe.return_value = result(
            self.root, row(self.stage), row(self.stage)
        )
        self.assert_holds("invalid_hook_row")
        self.stage_probe.return_value = result(
            self.root, row(self.stage, enabled=False)
        )
        self.assert_holds("hook_not_enabled_and_trusted")

    def test_missing_resume_path_and_prune_both_hold(self):
        self.assert_holds(
            "publication_overlaps_retained_path", write_roots=(self.live,)
        )
        self.old_file.unlink()
        self.assert_holds("retained_path_missing")

    def test_unknown_retention_and_floating_pin_hold(self):
        self.assert_holds("retention_inventory_unknown", retained=None)
        self.assert_holds("full_git_pin_required", revision="main")

    def test_intermediate_symlink_in_pruned_tree_holds(self):
        payload = self.root / "payload"
        self.old_file.rename(payload)
        self.old_file.symlink_to(payload)
        alias = self.root / "alias"
        alias.symlink_to(self.old_file)
        receipt = replace(self.retained, path=alias)
        self.assert_holds(
            "publication_overlaps_retained_path",
            retained={"resume-old": (receipt,)},
            write_roots=(self.live,),
        )

    def test_intermediate_directory_followed_by_parent_holds(self):
        payload = self.live / "payload"
        self.old_file.rename(payload)
        alias = self.root / "alias"
        alias.symlink_to(self.old / ".." / payload.name)
        receipt = replace(self.retained, path=alias)
        self.assert_holds(
            "publication_overlaps_retained_path",
            retained={"resume-old": (receipt,)},
            write_roots=(self.old, self.new),
        )

    def test_retention_preserves_special_permission_bits(self):
        self.old_file.chmod(0o2755)
        receipt = replace(self.retained, mode=0o2755)
        receipt.verify()
        self.old_file.chmod(0o755)
        self.assert_holds("retained_path_changed", retained={"resume-old": (receipt,)})

    def test_bad_metadata_and_source_context_hold(self):
        raw = self.receipt.read_text()
        self.receipt.unlink()
        (self.stage / self.receipt.name).write_text(raw)
        self.assert_holds("install_provenance_unavailable")
        self.receipt.write_text(raw.replace(self.plan.revision, "b" * 40))
        self.assert_holds("install_provenance_mismatch")
        self.receipt.write_text(raw)
        self.live_probe.side_effect = [result(self.root, self.other)]
        self.stage_probe.return_value = result(self.root, row(self.old))
        self.assert_holds("hook_source_mismatch")

    def test_native_hash_cannot_substitute_for_pinned_source_bytes(self):
        for bundle in (self.stage, self.receipt.parent / "plugins/fixture"):
            (bundle / "stop.py").write_text("# unreviewed\n")
        self.assert_holds("staged_bundle_differs_from_pinned_source")

    def test_different_version_directory_holds(self):
        wrong = self.new.with_name("3.0.0")
        self.assert_holds(
            "invalid_publication_scope",
            live=replace(self.plan.live, bundle=wrong),
            write_roots=(wrong,),
        )

    def test_case_alias_of_pruned_directory_holds(self):
        alias = self.old.with_name(self.old.name + "V")
        self.old.rename(alias)
        receipt_path = alias.with_name(alias.name.lower()) / self.old_file.name
        if not receipt_path.exists():
            self.skipTest("case-sensitive fixture volume")
        receipt = replace(self.retained, path=receipt_path)
        self.assert_holds(
            "publication_overlaps_retained_path",
            retained={"resume-old": (receipt,)},
            write_roots=(alias, self.new),
        )

    def test_live_write_scope_cannot_cover_the_home(self):
        home = self.live.parents[3]
        self.assert_holds(
            "invalid_publication_scope", cache_scope=home, write_roots=(home,)
        )

    def test_hardlink_can_hide_retention_overlap(self):
        external = self.root / "external.py"
        external.hardlink_to(self.old_file)
        receipt = replace(self.retained, path=external)
        self.assert_holds(
            "retained_file_has_hardlinks", retained={"resume-old": (receipt,)}
        )

    def test_tree_id_is_not_a_reviewed_commit(self):
        checkout = self.receipt.parent
        tree = fixture_git(checkout, "rev-parse", f"{self.plan.revision}^{{tree}}")
        self.receipt.write_text(
            self.receipt.read_text().replace(self.plan.revision, tree)
        )
        self.assert_holds("git_pin_not_commit", revision=tree)

    def test_hex_named_ref_is_not_a_reviewed_commit(self):
        checkout = self.receipt.parent
        refname = "a" * 64
        fixture_git(checkout, "update-ref", f"refs/heads/{refname}", self.plan.revision)
        self.receipt.write_text(
            self.receipt.read_text().replace(self.plan.revision, refname)
        )
        self.assert_holds("git_pin_not_exact", revision=refname)

    def test_staged_file_must_have_independent_bytes(self):
        external = self.root / "external.py"
        external.hardlink_to(self.stage / "stop.py")
        self.assert_holds("bundle_file_has_hardlinks")

    def test_staged_home_cannot_alias_live_home(self):
        alias_home = self.root / "STAGE"
        if not alias_home.exists():
            self.skipTest("case-sensitive fixture volume")
        destination = alias_home / self.stage.relative_to(self.root / "stage")
        self.assert_holds(
            "stage_overlaps_live_cache",
            cache_scope=destination.parent,
            live=replace(self.plan.live, bundle=destination),
            write_roots=(destination,),
        )

    def test_stage_cache_cannot_share_a_live_directory_identity(self):
        stage_cache = self.stage.parents[2]
        live_cache = self.live.parent.parent

        def identity(path):
            return _entry_identity(stage_cache if path == live_cache else path)

        with patch("hook_health._entry_identity", side_effect=identity):
            self.assert_holds("stage_overlaps_live_cache")

    def test_staged_descendant_cannot_alias_a_live_write_root_descendant(self):
        staged_dir = self.stage / "shared"
        live_dir = self.old / "shared"
        staged_dir.mkdir()
        live_dir.mkdir()

        def identity(path):
            return _entry_identity(live_dir if path == staged_dir else path)

        with patch("hook_health._entry_identity", side_effect=identity):
            self.assert_holds(
                "stage_overlaps_live_cache",
                retained={},
                write_roots=(self.old, self.new),
            )
        self.live_probe.assert_not_called()

    def test_retained_file_cannot_alias_an_entry_inside_a_pruned_directory(self):
        external = self.root / "external.py"
        shutil.copy2(self.old_file, external)
        receipt = replace(self.retained, path=external)

        def identity(path):
            return _entry_identity(self.old_file if path == external else path)

        with patch("hook_health._entry_identity", side_effect=identity):
            self.assert_holds(
                "publication_overlaps_retained_path",
                retained={"resume-old": (receipt,)},
                write_roots=(self.old, self.new),
            )

    def test_post_publication_stage_and_live_bundle_alias_holds(self):
        published = False

        def mount_alias():
            nonlocal published
            shutil.copytree(self.stage, self.new)
            published = True

        def identity(path):
            return _entry_identity(
                self.stage if published and path == self.new else path
            )

        with (
            patch("hook_health._entry_identity", side_effect=identity),
            self.assertRaisesRegex(
                HookCheckError, "^post_publication:stage_overlaps_live_cache$"
            ),
        ):
            guarded_publish(self.plan, self.stage_probe, self.live_probe, mount_alias)
        self.assertEqual(self.live_probe.call_count, 1)

    def test_published_destination_cannot_alias_the_staged_marketplace(self):
        source = self.receipt.parent / "plugins/fixture"
        original = _entry_identity
        published = False

        def mount_alias():
            nonlocal published
            shutil.copytree(self.stage, self.new)
            published = True

        def identity(path):
            return original(source if published and path == self.new else path)

        self.assertTrue(source.is_dir())
        with (
            patch("hook_health._entry_identity", side_effect=identity),
            self.assertRaisesRegex(
                HookCheckError, "^post_publication:stage_overlaps_live_cache$"
            ),
        ):
            guarded_publish(self.plan, self.stage_probe, self.live_probe, mount_alias)
        self.assertEqual(self.live_probe.call_count, 1)

    def test_publication_probes_must_report_the_planned_homes(self):
        for probe in (self.live_probe, self.stage_probe):
            with self.subTest(probe=probe):
                home = probe.home
                probe.home = self.root / "unrelated"
                self.assert_holds("publication_probe_home_mismatch")
                probe.home = home
        self.live_probe.assert_not_called()
        self.stage_probe.assert_not_called()

    def test_catalog_precedence_comes_from_pinned_tree(self):
        checkout = self.receipt.parent
        original = checkout / ".agents/plugins/marketplace.json"
        alternate = original.with_name("api_marketplace.json")
        catalog = json.loads(original.read_text())
        catalog["plugins"][0]["source"] = "./alternate"
        alternate.write_text(json.dumps(catalog))
        shutil.copytree(self.stage, checkout / "alternate")
        (checkout / "alternate/stop.py").write_text("# alternate\n")
        _, revision = fixture_revision(checkout)
        original.unlink()
        (self.stage / "stop.py").write_text("# alternate\n")
        self.assert_holds("staged_bundle_differs_from_pinned_source", revision=revision)

    def test_source_symlinks_omitted_by_native_install(self):
        source = self.receipt.parent / "plugins/fixture"
        (source / "alias").symlink_to("stop.py")
        _, revision = fixture_revision(self.receipt.parent)
        self.plan = replace(self.plan, revision=revision)
        (self.stage / "alias").symlink_to("stop.py")
        self.assert_holds("unexpected_bundle_symlink")
        (self.stage / "alias").unlink()
        self.live_probe.side_effect = [
            result(self.root, self.other),
            result(self.root, self.other, row(self.new)),
        ]
        publish_bundle(self.plan, self.stage_probe, self.live_probe)
        self.assertFalse((self.new / "alias").is_symlink())

    def test_marketplace_root_can_be_the_plugin_source(self):
        checkout = self.receipt.parent
        manifest = checkout / ".agents/plugins/marketplace.json"
        catalog = json.loads(manifest.read_text())
        catalog["plugins"][0]["source"] = "./"
        manifest.write_text(json.dumps(catalog))
        for entry in (checkout / "plugins/fixture").iterdir():
            entry.rename(checkout / entry.name)
        shutil.rmtree(checkout / "plugins")
        _, revision = fixture_revision(checkout)
        shutil.copytree(checkout, self.stage, dirs_exist_ok=True)
        self.plan = replace(self.plan, revision=revision)
        self.assert_holds("reviewed_root_digest_required")
        digest = reviewed_root_bundle_digest(self.stage)
        checkout_metadata = self.stage / ".git/description"
        checkout_metadata.write_text("unreviewed\n")
        self.live_probe.side_effect = [result(self.root, self.other)]
        self.assert_holds(
            "root_bundle_differs_from_review", reviewed_root_digest=digest
        )
        checkout_metadata.unlink()
        digest = reviewed_root_bundle_digest(self.stage)
        self.live_probe.side_effect = [
            result(self.root, self.other),
            result(self.root, self.other, row(self.new)),
        ]
        publish_bundle(
            replace(self.plan, reviewed_root_digest=digest),
            self.stage_probe,
            self.live_probe,
        )
        self.assertTrue(self.new.is_dir())

    def test_published_bytes_must_still_match_pinned_source(self):
        def substitute():
            self.stage.rename(self.new)
            (self.new / "stop.py").write_text("# unreviewed\n")

        with self.assertRaisesRegex(
            HookCheckError,
            "^post_publication:published_bundle_differs_from_pinned_source$",
        ):
            guarded_publish(self.plan, self.stage_probe, self.live_probe, substitute)

    def test_published_bundle_and_parent_cannot_be_aliases_into_stage(self):
        with self.assertRaisesRegex(
            HookCheckError, "^post_publication:published_bundle_path_changed$"
        ):
            guarded_publish(
                self.plan,
                self.stage_probe,
                self.live_probe,
                lambda: self.new.symlink_to(self.stage),
            )
        self.new.unlink()
        self.live_probe.side_effect = [result(self.root, self.other)]

        def replace_parent():
            self.live.rename(self.live.with_name("old-cache"))
            self.live.symlink_to(self.stage.parent)

        with self.assertRaisesRegex(
            HookCheckError, "^post_publication:published_bundle_path_changed$"
        ):
            guarded_publish(
                replace(self.plan, write_roots=(self.live,), retained={}),
                self.stage_probe,
                self.live_probe,
                replace_parent,
            )

    def test_post_empty_discovery_or_unrelated_drift_holds_restart(self):
        for after, reason in (
            (result(self.root), "hook_inventory_mismatch"),
            (result(self.root, row(self.new)), "unrelated_discovery_changed"),
        ):
            with self.subTest(reason=reason):
                self.live_probe.side_effect = [result(self.root, self.other), after]
                with self.assertRaisesRegex(
                    HookCheckError, "^post_publication:" + reason + "$"
                ):
                    guarded_publish(
                        self.plan, self.stage_probe, self.live_probe, self.publisher
                    )
                self.new.rename(self.stage)
        self.assertEqual(self.publisher.call_count, 2)

    def test_only_unrelated_relative_order_and_metadata_must_stay_stable(self):
        first = self.other | {"displayOrder": 0}
        second = self.other | {"key": "second", "displayOrder": 1}
        shifted_first = first | {"displayOrder": 1}
        shifted_second = second | {"displayOrder": 2}
        candidate = row(self.new, displayOrder=0)
        for rows, error in (
            ((candidate, shifted_first, shifted_second), None),
            ((candidate, shifted_second, shifted_first), "unrelated_discovery_changed"),
            (
                (candidate, shifted_first | {"enabled": False}, shifted_second),
                "unrelated_discovery_changed",
            ),
        ):
            with self.subTest(rows=rows):
                self.live_probe.side_effect = [
                    result(self.root, first, second),
                    result(self.root, *rows),
                ]
                if error:
                    with self.assertRaisesRegex(
                        HookCheckError, "^post_publication:" + error + "$"
                    ):
                        publish_bundle(self.plan, self.stage_probe, self.live_probe)
                else:
                    publish_bundle(self.plan, self.stage_probe, self.live_probe)
                self.new.rename(self.stage)

    def test_post_retention_failure_is_reported_even_if_discovery_would_pass(self):
        def bad_publish():
            self.stage.rename(self.new)
            self.old_file.unlink()

        with self.assertRaisesRegex(
            HookCheckError, "^post_publication:retained_path_missing$"
        ):
            guarded_publish(self.plan, self.stage_probe, self.live_probe, bad_publish)
        self.assertEqual(self.live_probe.call_count, 1)


class TransportTest(unittest.TestCase):
    def peer(self, path, config):
        nonce = base64.b64encode(bytes(16))
        accept = base64.b64encode(
            hashlib.sha1(nonce + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
        )
        headers = (
            b"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: "
            + accept
            + b"\r\n\r\n"
        )

        def frame(value):
            payload = json.dumps(value).encode()
            length = (
                bytes([len(payload)])
                if len(payload) < 126
                else b"\x7e" + len(payload).to_bytes(2, "big")
            )
            return b"\x81" + length + payload

        initialize = frame(
            {
                "id": 1,
                "result": {
                    "codexHome": str(path),
                    "userAgent": "codex/0.171.0 (fixture)",
                    "padding": "x" * 140,
                },
            }
        )
        layers = [
            {
                "name": {"type": "user", "file": str(path / "config.toml")},
                "config": config,
            }
        ]
        layers_frame = frame({"id": 2, "result": {"layers": layers}})
        hooks = frame({"id": 3, "result": {"data": []}})
        peer = Mock()
        peer.recv.return_value = (
            headers + initialize + layers_frame + b"\x89\x01p" + hooks
        )
        return peer

    def test_connection_parses_upgrade_and_control_responses(self):
        path = Path("/fixture")
        peer = self.peer(path, {})
        with patch("hook_health.os.urandom", side_effect=lambda size: bytes(size)):
            self.assertEqual(_discover(peer, path, path, path), {"data": []})
        # HTTP upgrade, initialize, initialized, config/read, hooks/list, pong.
        self.assertEqual(peer.sendall.call_count, 6)

    def test_missing_trust_baseline_stops_before_hook_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for key in (KEY, f"  {KEY}  "):
                with self.subTest(key=key):
                    peer = self.peer(
                        home, {"hooks": {"state": {key: {"trusted_hash": HASH}}}}
                    )
                    with (
                        patch(
                            "hook_health.os.urandom",
                            side_effect=lambda size: bytes(size),
                        ),
                        self.assertRaisesRegex(
                            HookCheckError, "^control_trust_baseline_missing$"
                        ),
                    ):
                        _discover(peer, home, home, home)
                    self.assertEqual(peer.sendall.call_count, 4)
                    self.assertFalse((home / ".hook-trust").exists())

    def test_missing_control_socket_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with self.assertRaisesRegex(
                HookCheckError, "^control_socket_unavailable$"
            ) as caught:
                NativeSocket(home / "missing.sock", home)(home)
            self.assertTrue(caught.exception.incomplete)


@contextmanager
def fixture_server(binary, root, home, name):
    sock = root / name
    env = {
        "HOME": str(root),
        "CODEX_HOME": str(home),
        "PATH": os.defpath,
        "GIT_ALLOW_PROTOCOL": "",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
    }
    with subprocess.Popen(
        [
            binary,
            "--disable",
            "daemon_auto_start",
            "app-server",
            "--listen",
            f"unix://{sock}",
        ],
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as server:
        try:
            for _ in range(100):
                if sock.is_socket():
                    break
                if server.poll() is not None:
                    raise AssertionError("fixture app-server exited")
                time.sleep(0.05)
            else:
                raise AssertionError("fixture socket unavailable")
            yield NativeSocket(sock, home)
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def install_native_marketplace(binary, root, stage):
    """Have Codex activate and install a pinned, local-only fixture checkout."""
    origin = root / "2.0.0"
    make_bundle(origin)
    (origin / "alias.py").symlink_to("stop.py")
    manifest = origin / ".agents/plugins/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"name": "local", "plugins": [{"name": "fixture", "source": "./"}]})
    )
    # Codex 0.171.0 waits for Git to exit before draining its pipes.
    # Detached HEAD advice can fill the small stderr pipe on macOS.
    git_config = root / "fixture-gitconfig"
    git_config.write_text("[advice]\n    detachedHead = false\n")
    env = {
        "HOME": str(root),
        "CODEX_HOME": str(stage),
        "PATH": os.defpath,
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(git_config),
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2025-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2025-01-01T00:00:00Z",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
    }

    def run(*argv):
        result = subprocess.run(
            argv,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            raise AssertionError(
                f"{argv[0]} failed ({result.returncode}): {result.stderr}"
            )
        return result.stdout.strip()

    git = ("git", "-C", origin)
    run(*git, "init", "-q", "--template=", "-b", "fixture")
    run(
        *git,
        "add",
        "--",
        ".agents",
        ".codex-plugin",
        "alias.py",
        "hooks.json",
        "stop.py",
    )
    tree = run(*git, "write-tree")
    revision = run(*git, "commit-tree", tree, "-m", "Native hook fixture")
    run(*git, "update-ref", "refs/heads/fixture", revision)
    stage.mkdir()
    source = origin.as_uri()
    (stage / "config.toml").write_text(
        f'[features]\nhooks = true\n[marketplaces.local]\nsource_type = "git"\n'
        f'source = "{source}"\nref = "{revision}"\n'
    )
    cli = (binary, "--disable", "daemon_auto_start", "plugin")
    run(*cli, "marketplace", "upgrade", "local")
    run(*cli, "add", PLUGIN, "--json")
    return source, revision


@unittest.skipUnless(
    os.environ.get("CODEX_HOOK_FIXTURE_BINARY"), "explicit disposable native fixture"
)
class NativeTest(StagingTestCase):
    def test_native_trust_byte_drift_missing_and_publication(self):
        binary = Path(os.environ["CODEX_HOOK_FIXTURE_BINARY"]).resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix="hooks-", dir="/tmp") as temporary:
            root = Path(temporary).resolve()
            stage, live = root / "stage", root / "live"
            relative = Path("plugins/cache/local/fixture/2.0.0")
            source = stage / relative
            destination = live / relative
            git_source, revision = install_native_marketplace(binary, root, stage)
            self.assertTrue(source.is_dir())
            self.assertFalse((source / "alias.py").is_symlink())
            reviewed_bundle = reviewed_root_bundle_digest(source)
            destination.parent.mkdir(parents=True)
            config = (
                '[features]\nhooks = true\n[plugins."fixture@local"]\nenabled = true\n'
            )
            (stage / "config.toml").write_text(config)
            with fixture_server(binary, root, stage, "initial.sock") as discover:
                rows = discover(root)["data"][0]["hooks"]
                self.assertEqual(len(rows), 1)
                key, digest = rows[0]["key"], rows[0]["currentHash"]
                self.assertEqual(rows[0]["trustStatus"], "untrusted")
            declaration, content = digest.split("/")
            config += (
                f'[hooks.state."{key}"]\ntrusted_hash = "{declaration}"\n'
                f'trusted_content_hash = "{content}"\n'
            )
            for home in (stage, live):
                (home / "config.toml").write_text(config)
            with fixture_server(binary, root, stage, "unseeded.sock") as unseeded:
                with self.assertRaisesRegex(
                    HookCheckError, "^control_trust_baseline_missing$"
                ):
                    unseeded(root)
                self.assertFalse((stage / ".hook-trust").exists())
            receipts = {}
            for home in (stage, live):
                identity = hashlib.sha256()
                for part in (os.fsencode(home / "config.toml"), PLUGIN.encode()):
                    identity.update(len(part).to_bytes(8, "little"))
                    identity.update(part)
                directory = home / ".hook-trust"
                directory.mkdir()
                baseline = directory / identity.hexdigest()
                baseline.write_text(content)
                receipts[baseline] = baseline.read_bytes()
            stage_expected = Expected(PLUGIN, source, {key: digest})
            live_expected = Expected(PLUGIN, destination, {key: digest})
            with (
                fixture_server(binary, root, stage, "stage.sock") as stage_probe,
                fixture_server(binary, root, live, "live.sock") as live_probe,
            ):
                check(stage_probe, root, stage_expected)
                (source / "stop.py").write_text("# changed byte\n")
                modified = stage_probe(root)["data"][0]["hooks"][0]
                self.assertEqual(modified["trustStatus"], "modified")
                self.assertEqual(modified["currentHash"].split("/")[0], declaration)
                self.assertNotEqual(modified["currentHash"], digest)
                with self.assertRaisesRegex(
                    HookCheckError, "hook_not_enabled_and_trusted"
                ):
                    check(stage_probe, root, stage_expected)
                (source / "stop.py").write_text("# fixture\n")
                self.assertEqual(live_probe(root)["data"][0]["hooks"], [])
                with self.assertRaisesRegex(HookCheckError, "hook_inventory_mismatch"):
                    check(live_probe, root, live_expected)
                plan = PublishPlan(
                    root,
                    destination.parent,
                    stage_expected,
                    live_expected,
                    git_source,
                    revision,
                    (destination,),
                    {},
                    reviewed_root_digest=reviewed_bundle,
                )
                publish_bundle(plan, stage_probe, live_probe)
                self.assertEqual((live / "config.toml").read_text(), config)
                self.assertEqual((stage / "config.toml").read_text(), config)
                self.assertEqual(
                    {path: path.read_bytes() for path in receipts}, receipts
                )
                check(live_probe, root, live_expected)
                expectation = root / "expected.json"
                expectation.write_text(
                    json.dumps(
                        {
                            "plugin": PLUGIN,
                            "bundle": str(destination),
                            "hashes": {key: digest},
                        }
                    )
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        Path(__file__).with_name("hook_health.py"),
                        "--socket",
                        live_probe.socket,
                        "--home",
                        live,
                        "--cwd",
                        root,
                        "--expect",
                        expectation,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(
                    json.loads(completed.stdout),
                    {
                        "runtime": "NOT_RUN",
                        "discovery": "pass",
                        "hooks": 1,
                    },
                )
                with self.assertRaisesRegex(HookCheckError, "^control_home_mismatch$"):
                    NativeSocket(live_probe.socket, stage)(root)


if __name__ == "__main__":
    unittest.main()
