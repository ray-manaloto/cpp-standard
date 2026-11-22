"""Exercise both checklist rows offline with two independent installed-tool stand-ins."""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBES = ROOT / ".mise/tasks/certify/ubuntu-probes"
STOCK = "/opt/iwyu-llvm23/bin/include-what-you-use"
SNAPSHOT = "Ubuntu clang version 23.1.6 (++20261116013916+5b10d2d74929-1~exp1~20261116133927.96)"
DEB_VERSION = "1:23.1.6~++20261116013916+5b10d2d74929-1~exp1~20261116133927.96"

# Each stand-in checks the actual translation unit and driver arguments before
# emitting -H records and IWYU output in the installed tools' formats.
ANALYZE = """
grep -Fxq '#include <vector>' iw.cpp
grep -Fxq 'int main() { return 0; }' iw.cpp
echo "$row" >>"$calls"
echo ". $header" >&2
echo "${unit:-iw.cpp} should remove these lines:" >&2
echo "${removal:-- #include <vector>  // lines 1-1}" >&2
echo "The full include-list for iw.cpp:" >&2
echo "#include <vector>" >&2
echo "${diagnostic:-}" >&2
exit "${analysis_rc:-0}"
"""


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(0o755)


def pin(path, assignment):
    return re.search(
        rf"^{assignment}=([0-9a-f]{{40}})$", path.read_text(), re.MULTILINE
    )[1]


class IwyuProbes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.fork = self.root / "fork"
        self.stock = self.root / "stock/bin/include-what-you-use"
        self.path = self.root / "bin"
        self.resource = self.fork / "lib/clang/21"
        self.builtin = self.resource / "include/__stddef_size_t.h"
        self.vector = self.root / "usr/lib/llvm-23/include/c++/v1/vector"
        self.fallback = self.root / "gcc/include/c++/16/vector"
        for header in (self.builtin, self.vector, self.fallback):
            header.parent.mkdir(parents=True)
            header.touch()
        public = self.root / "usr/include/c++/v1"
        public.parent.mkdir(parents=True)
        public.symlink_to(self.vector.parent)
        (self.root / "sources").mkdir()
        # Relocate only the absolute image install into the disposable tree.
        # Run the entire checklist, including --only selection and row formatting.
        script = PROBES.read_text()
        self.script = self.root / "ubuntu-probes"
        self.script.write_text(script.replace(STOCK, shlex.quote(str(self.stock))))
        recipe = ROOT / "docs/standard/ubuntu-p2996/build-linux.sh"
        fork_pin = pin(recipe, "commit")
        self.env = {
            "PATH": f"{self.path}:/usr/bin:/bin",
            "PRETTY_NAME": "fixture",  # macOS lacks /etc/os-release.
            "HOME": str(self.root),
            "PROBES": str(self.root / "sources"),
            "P2996": str(self.fork),
            "PIN": fork_pin,
            "fork_clang": f"clang version 21.0.0git (bloomberg/clang-p2996 {fork_pin})",
            "fork_source": pin(recipe, "iwyu_commit")[:7],
            "stock_source": pin(
                ROOT / "docs/standard/ubuntu-cert.Dockerfile", "ARG IWYU_COMMIT"
            )[:7],
            "stock_clang": SNAPSHOT,
            "resource": str(self.resource),
            "builtin": str(self.builtin),
            "vector": str(public / "vector"),
            "package_vector": str(self.vector),
            "native_arch": "amd64",
            "deb_version": DEB_VERSION,
            "calls": str(self.root / "calls"),
        }
        executable(
            self.fork / "bin/clang++",
            """
case "$*" in
  --version) echo "$fork_clang"; exit "${fork_version_rc:-0}" ;;
  -print-resource-dir) echo "${compiler_root:-$resource}" ;;
  *) exit 90 ;;
esac
""",
        )
        executable(
            self.path / "clang++-23", '[[ "$*" == --version ]] && echo "$stock_clang"'
        )
        executable(
            self.path / "dpkg",
            '[[ "$*" == --print-architecture ]] && echo "$native_arch"',
        )
        executable(
            self.path / "dpkg-query",
            """
if [[ "$1" == -L && "$2" == "libc++-23-dev:$native_arch" ]]; then
  printf '%s\\n' "/." "$package_vector"
  exit 0
fi
[[ "$1" == -W && "$2" == '--showformat=${db:Status-Status} ${Version}' ]]
case "$3" in
  "clang-23:$native_arch") echo "installed $deb_version" ;;
  "libc++-23-dev:$native_arch") echo "${libcxx_status:-installed} ${libcxx_version:-$deb_version}" ;;
  *) exit 90 ;;
esac
""",
        )
        self.fork_iw = self.fork / "bin/include-what-you-use"
        executable(
            self.fork_iw,
            """
case "$*" in
  --version) echo "include-what-you-use 0.25 (git:$fork_source) based on ${fork_base:-$fork_clang}"; exit 0 ;;
  -print-resource-dir) echo "${iwyu_root:-$resource}"; exit "${query_rc:-1}" ;;
esac
[[ "$*" == '-std=c++26 -H iw.cpp' ]]
grep -Fxq '#include <__stddef_size_t.h>' iw.cpp
row=P8 header=${fork_trace:-$builtin}
"""
            + ANALYZE,
        )
        executable(
            self.stock,
            """
if [[ "$*" == --version ]]; then
  echo "include-what-you-use 0.27 (git:$stock_source) based on ${stock_base:-$stock_clang}"
  exit 0
fi
[[ "$*" == '-std=c++26 -stdlib=libc++ -H iw.cpp' ]]
grep -Fq '!defined(_LIBCPP_VERSION) || defined(__GLIBCXX__)' iw.cpp
row=T3 header=${stock_trace:-$vector}
"""
            + ANALYZE,
        )
        self.stock_link = self.path / self.stock.name
        self.stock_link.symlink_to(self.stock)

    def rows(self, *, p8=None, t3=None, **settings):
        expected = [(row, status) for row, status in (("P8", p8), ("T3", t3)) if status]
        self.assertTrue(expected)
        only = ",".join(row for row, _ in expected)
        Path(self.env["calls"]).write_text("")
        run = subprocess.run(
            ["bash", str(self.script)],
            cwd=self.root,
            env={**self.env, "usage_only": only, **settings},
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        rows = [
            line.split(maxsplit=2)
            for line in run.stdout.splitlines()
            if not line.startswith("HDR ")
        ]
        self.assertEqual([(row[0], row[1]) for row in rows], expected, run.stdout)
        return [row[2] for row in rows]

    def test_single_row_selection_reports_only_its_own_analysis(self):
        for row, settings, proof in [
            ("P8", {"p8": "PASS", "query_rc": "0"}, str(self.builtin)),
            (
                "T3",
                {"t3": "PASS", "native_arch": "arm64"},
                f"libc++-23-dev:arm64={DEB_VERSION}",
            ),
        ]:
            with self.subTest(row=row):
                (evidence,) = self.rows(**settings)
                self.assertIn(proof, evidence)
                self.assertEqual(
                    Path(self.env["calls"]).read_text().splitlines(), [row]
                )

    def test_both_installations_analyze_and_retain_evidence(self):
        mounted = self.root / "mounted fork"
        mounted.symlink_to(self.fork)
        p8, t3 = self.rows(p8="PASS", t3="PASS", P2996=str(mounted))
        for part in (
            self.fork_iw,
            self.env["PIN"],
            self.env["fork_source"],
            self.resource,
            self.builtin,
        ):
            self.assertIn(str(part), p8)
        for part in (
            self.stock,
            self.env["stock_source"],
            SNAPSHOT,
            self.vector,
            f"libc++-23-dev:amd64={DEB_VERSION}",
        ):
            self.assertIn(str(part), t3)
        for evidence in (p8, t3):
            self.assertIn("removed <vector> rc=0", evidence)
        self.assertEqual(Path(self.env["calls"]).read_text().splitlines(), ["P8", "T3"])

    def test_fork_provenance(self):
        other = self.fork.with_name("fork-other")
        other.mkdir()
        wrong_header = other / self.builtin.name
        wrong_header.touch()
        for settings, reason in [
            ({"fork_source": "791e69e0"}, "identify fork"),
            ({"fork_version_rc": "1"}, "--version exited 1"),
            (
                {
                    "fork_base": self.env["fork_clang"].replace(
                        self.env["PIN"], "0" * 40
                    )
                },
                "identify fork",
            ),
            ({"iwyu_root": str(self.fork)}, "resource mismatch"),
            (
                {"iwyu_root": str(other), "compiler_root": str(other)},
                "resource mismatch",
            ),
            ({"query_rc": "2"}, "resource query"),
            ({"fork_trace": str(wrong_header)}, "builtin include"),
        ]:
            with self.subTest(settings=settings):
                self.assertIn(reason, self.rows(p8="FAIL", **settings)[0])
        self.builtin.unlink()
        self.builtin.symlink_to(wrong_header)
        self.assertIn("builtin include", self.rows(p8="FAIL")[0])

    def test_fork_executable_must_resolve_inside_selected_prefix(self):
        other = self.root / "other-iwyu"
        self.fork_iw.rename(other)
        self.fork_iw.symlink_to(other)
        self.assertIn("misplaced fork IWYU", self.rows(p8="FAIL")[0])

    def test_stock_provenance_and_libcxx(self):
        for settings, reason in [
            ({"stock_source": "c9cbc830"}, "expected Ubuntu clang"),
            (
                {"stock_base": SNAPSHOT.replace("5b10d2d74929", "551bf48cf74f")},
                "expected Ubuntu clang",
            ),
            ({"stock_clang": "Ubuntu clang version 23.1.6"}, "expected Ubuntu clang"),
            ({"stock_trace": str(self.fallback)}, "expected libc++ <vector>"),
        ]:
            with self.subTest(settings=settings):
                self.assertIn(reason, self.rows(t3="FAIL", **settings)[0])
        self.stock_link.unlink()
        shutil.copy2(self.stock, self.stock_link)
        self.assertIn("expected distinct stock install", self.rows(t3="FAIL")[0])

    def test_same_executable_cannot_satisfy_both_rows(self):
        self.stock.unlink()
        os.link(self.fork_iw, self.stock)
        _, t3 = self.rows(p8="PASS", t3="FAIL")
        self.assertIn("expected distinct stock install", t3)

    def test_stock_header_ownership_and_package_snapshot(self):
        other = self.root / "other/include/c++/v1/vector"
        other.parent.mkdir(parents=True)
        shutil.copyfile(self.vector, other)
        older = DEB_VERSION.replace("5b10d2d74929", "551bf48cf74f")
        for settings, reason in [
            ({"stock_trace": str(other)}, "does not own traced"),
            ({"libcxx_version": older}, "clang-23:amd64 reports"),
            ({"libcxx_status": "config-files"}, "clang-23:amd64 reports"),
            ({"deb_version": older}, "differs from active"),
        ]:
            with self.subTest(settings=settings):
                (evidence,) = self.rows(t3="FAIL", **settings)
                self.assertIn(reason, evidence)
        self.vector.unlink()
        self.vector.symlink_to(other)
        (evidence,) = self.rows(t3="FAIL")
        self.assertIn("does not own traced", evidence)

    def test_each_analysis_must_succeed_and_remove_vector_from_its_own_file(self):
        for row, settings, reason in [
            ("p8", {"analysis_rc": "1"}, "analysis exit 1"),
            ("t3", {"diagnostic": "fatal error: header missing"}, "fatal error:"),
            ("p8", {"removal": "- #include <map>"}, "no unused <vector>"),
            ("t3", {"unit": "another.cpp"}, "no unused <vector>"),
        ]:
            with self.subTest(row=row, settings=settings):
                (evidence,) = self.rows(**{row: "FAIL"}, **settings)
                self.assertIn(reason, evidence)
                self.assertEqual(
                    Path(self.env["calls"]).read_text().splitlines(), [row.upper()]
                )


if __name__ == "__main__":
    unittest.main()
