"""Check the CTest result consumed by the native amd64 qualification."""

import runpy
import tempfile
import unittest
from pathlib import Path

CHECK = runpy.run_path(
    str(
        Path(__file__).resolve().parents[2]
        / "docs/standard/gha-runner/pc-compiler-project.py"
    )
)["check_tests"]


class ProjectResults(unittest.TestCase):
    def test_requires_two_distinct_executed_passing_tests(self):
        core = '<testcase name="core_test" status="run"/>'
        standin = '<testcase name="standin_test" status="run"/>'
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "ctest.xml"
            for rows in (
                core + standin,
                core,
                core * 2,
                core + standin + core,
                core + standin.replace("run", "notrun"),
                core + standin.replace("/>", "><failure/></testcase>"),
            ):
                with self.subTest(rows=rows):
                    report.write_text(f"<testsuite>{rows}</testsuite>")
                    if rows == core + standin:
                        CHECK(report)
                    else:
                        with self.assertRaises(ValueError):
                            CHECK(report)


if __name__ == "__main__":
    unittest.main()
