"""Tests of toolchains/p2996/build.sh's patch step (`build.sh patch <src> [patch dir]`): a patch
applies to a source tree that sits inside another git repository (the builder's scratch is inside
the checkout, where a plain `git apply` exits 0 and changes nothing), and a patch that changes no
file fails the build. Synthetic patches, no network. Run: python3 -I tests/toolchain/test_build_patch.py
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "toolchains/p2996/build.sh"

PATCH = """Header text, as the real patch has.

diff --git a/lib/a.txt b/lib/a.txt
index 0000000..1111111 100644
--- a/lib/a.txt
+++ b/lib/a.txt
@@ -1,2 +1,2 @@
 keep
-old
+new
"""


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BUILD), "patch", *args],
        capture_output=True,
        text=True,
        check=False,
    )


class PatchStep(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.outer = Path(self._tmp.name) / "checkout"
        self.outer.mkdir()
        # The enclosing repository: the checkout the scratch directory sits in.
        subprocess.run(["git", "init", "-q", str(self.outer)], check=True)
        self.src = self.outer / ".work/build/src"
        (self.src / "lib").mkdir(parents=True)
        (self.src / "lib/a.txt").write_text("keep\nold\n")
        self.patches = Path(self._tmp.name) / "patches"
        self.patches.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_applies_inside_an_enclosing_repository(self) -> None:
        (self.patches / "fix.patch").write_text(PATCH)
        r = run(str(self.src), str(self.patches))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.src / "lib/a.txt").read_text(), "keep\nnew\n")
        self.assertIn("applied fix.patch: lib/a.txt", r.stdout)

    def test_a_patch_that_does_not_apply_fails(self) -> None:
        (self.src / "lib/a.txt").write_text("keep\nnew\n")
        (self.patches / "fix.patch").write_text(PATCH)
        self.assertNotEqual(run(str(self.src), str(self.patches)).returncode, 0)

    def test_a_patch_that_names_no_file_fails(self) -> None:
        (self.patches / "empty.patch").write_text("only a header\n")
        r = run(str(self.src), str(self.patches))
        self.assertNotEqual(r.returncode, 0)

    def test_the_real_patch_dir_is_the_default(self) -> None:
        # The real scc.h patch does not apply to this stand-in tree: the step must fail, not
        # silently pass.
        self.assertNotEqual(run(str(self.src)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
