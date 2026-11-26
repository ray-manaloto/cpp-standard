"""Check the runner launch flags without starting containers."""

import re
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "docs/standard/gha-runner"
CONTAINER_ENV = re.compile(r"(?<!\S)-e\s+container=docker(?=\s|$)")


class ContainerEnvironment(unittest.TestCase):
    def test_direct_docker_runs_set_container_environment(self):
        for name in ("gha-slot", "pc-compiler-once.sh", "pc-compiler-store.sh"):
            source = (SCRIPTS / name).read_text().replace("\\\n", " ")
            launches = re.findall(r"\bdocker[ \t]+run[ \t]+([^\n]+)", source)
            self.assertTrue(launches, f"{name}: no direct docker run found")
            for args in launches:
                with self.subTest(script=name, args=args):
                    self.assertRegex(args, CONTAINER_ENV)

    def test_shared_job_arguments_set_container_environment(self):
        source = (SCRIPTS / "gha-slot").read_text().replace("\\\n", " ")
        job_args = re.search(r"(?m)^job_args\(\) \{\n(.*?)^\}", source, re.DOTALL)
        self.assertIsNotNone(job_args)
        assert job_args is not None
        run_args = re.search(r"(?m)^\s*printf '%s\\n' run ([^\n]+)", job_args[1])
        self.assertIsNotNone(run_args)
        assert run_args is not None
        self.assertRegex(run_args[1], CONTAINER_ENV)
