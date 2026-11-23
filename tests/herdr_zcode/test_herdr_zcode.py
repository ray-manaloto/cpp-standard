"""Tests for herdr-zcode launch.py and receipt.py."""

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "unix" / "home" / ".agents" / "skills" / "herdr-zcode" / "scripts"
LAUNCH = SCRIPTS / "launch.py"
RECEIPT = SCRIPTS / "receipt.py"


def make_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class LaunchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.log = self.root / "calls.jsonl"
        self.spaces_file = self.root / "spaces.json"
        self.spaces_file.write_text(
            json.dumps(
                {
                    "spaces": [
                        {
                            "id": "sp1",
                            "name": "local",
                            "machine": None,
                            "tabs": [
                                {
                                    "id": "tb0",
                                    "name": "lead",
                                    "terminals": [{"terminal": "t3wv"}],
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.fake_node = make_executable(
            self.bin_dir / "node",
            '#!/bin/sh\nexec "$@"\n',
        )
        self.fake_zcode = make_executable(
            self.bin_dir / "zcode.js",
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "if sys.argv[1:] == ['doctor', '--json']:\n"
            "    if os.environ.get('FAKE_DOCTOR_BAD') == '1':\n"
            "        print(json.dumps({'configuration': {'ok': False}}))\n"
            "    elif os.environ.get('FAKE_DOCTOR_FAIL') == '1':\n"
            "        print('broken', file=sys.stderr)\n"
            "        sys.exit(2)\n"
            "    else:\n"
            "        print(json.dumps({'configuration': {'ok': True}}))\n",
        )
        make_executable(
            self.bin_dir / "mise",
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "if sys.argv[1:3] == ['which', 'zcode']:\n"
            "    print(os.environ['FAKE_ZCODE'])\n"
            "elif sys.argv[1:3] == ['which', 'node']:\n"
            "    print(os.environ['FAKE_NODE'])\n"
            "else:\n"
            "    sys.exit(1)\n",
        )
        make_executable(
            self.bin_dir / "herdr-app",
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "a = sys.argv[1:]\n"
            "if a == ['ls']:\n"
            "    if os.environ.get('FAKE_LS_ERROR') == '1':\n"
            "        print(json.dumps({'error': 'the window did not answer'}))\n"
            "        sys.exit(1)\n"
            "    print(open(os.environ['FAKE_SPACES']).read())\n"
            "elif a[:2] == ['do', 'tab.new']:\n"
            "    with open(os.environ['FAKE_LOG'], 'a') as fh:\n"
            "        fh.write(json.dumps(a) + '\\n')\n"
            "    idx = len(open(os.environ['FAKE_LOG']).read().splitlines())\n"
            "    if os.environ.get('FAKE_FAIL_SECOND') == '1' and idx == 2:\n"
            "        print('boom', file=sys.stderr)\n"
            "        sys.exit(1)\n"
            "    print(json.dumps({'tab': f'tb{idx}', 'terminal': f't{idx}'}))\n"
            "else:\n"
            "    sys.exit(1)\n",
        )
        self.env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "HC_TERMINAL_ID": "t3wv",
            "FAKE_ZCODE": str(self.fake_zcode),
            "FAKE_NODE": str(self.fake_node),
            "FAKE_SPACES": str(self.spaces_file),
            "FAKE_LOG": str(self.log),
        }

    def run_launch(
        self, *args: str, env_overrides: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if env_overrides:
            for key, value in env_overrides.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
        return subprocess.run(
            [sys.executable, str(LAUNCH), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def test_multi_tab_launch_unrestricted_with_passthrough(self) -> None:
        proc = self.run_launch(
            "--folder",
            str(self.work),
            "ZCode map 1",
            "ZCode map 2",
            "--",
            "--resume",
            "sess_abc",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        records = [json.loads(line) for line in proc.stdout.strip().splitlines()]
        self.assertEqual(
            records,
            [
                {"name": "ZCode map 1", "tab": "tb1", "terminal": "t1"},
                {"name": "ZCode map 2", "tab": "tb2", "terminal": "t2"},
            ],
        )
        calls = [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(calls), 2)
        argv = json.loads(calls[0][calls[0].index("--argv") + 1])
        self.assertEqual(
            argv,
            [
                "/usr/bin/env",
                f"ZCODE_NODE={self.fake_node}",
                "ZCODE_DISABLE_UPDATE_CHECK=1",
                "NO_UPDATE_NOTIFIER=1",
                str(self.fake_node),
                str(self.fake_zcode),
                "--resume",
                "sess_abc",
            ],
        )
        joined = " ".join(argv)
        for forbidden in (
            "sandbox-exec",
            "--disallowed-tools",
            "ZCODE_CLI_SETTINGS_FILE",
        ):
            self.assertNotIn(forbidden, joined)

    def test_refuses_bad_environment_and_collisions(self) -> None:
        no_hc = self.run_launch(
            "--folder", str(self.work), "w1", env_overrides={"HC_TERMINAL_ID": ""}
        )
        self.assertNotEqual(no_hc.returncode, 0)
        self.assertIn("HC_TERMINAL_ID", no_hc.stderr)

        ls_err = self.run_launch(
            "--folder", str(self.work), "w1", env_overrides={"FAKE_LS_ERROR": "1"}
        )
        self.assertNotEqual(ls_err.returncode, 0)
        self.assertIn("the window did not answer", ls_err.stderr)

        dup = self.run_launch("--folder", str(self.work), "w1", "w1")
        self.assertNotEqual(dup.returncode, 0)

        collision = self.run_launch("--folder", str(self.work), "lead")
        self.assertNotEqual(collision.returncode, 0)
        self.assertIn("already exists", collision.stderr)

        missing_dir = self.run_launch("--folder", str(self.root / "missing"), "w1")
        self.assertNotEqual(missing_dir.returncode, 0)

        self.spaces_file.write_text(
            json.dumps(
                {
                    "spaces": [
                        {
                            "id": "sp1",
                            "machine": "pc",
                            "tabs": [
                                {
                                    "id": "tb0",
                                    "name": "lead",
                                    "terminals": [{"terminal": "t3wv"}],
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        remote = self.run_launch("--folder", str(self.work), "w1")
        self.assertNotEqual(remote.returncode, 0)
        self.assertIn("local Herdr space", remote.stderr)

    def test_doctor_refusal_skip_and_partial_failure(self) -> None:
        bad = self.run_launch(
            "--folder", str(self.work), "w1", env_overrides={"FAKE_DOCTOR_BAD": "1"}
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("doctor", bad.stderr)

        skipped = self.run_launch(
            "--skip-doctor",
            "--folder",
            str(self.work),
            "w1",
            env_overrides={"FAKE_DOCTOR_FAIL": "1"},
        )
        self.assertEqual(skipped.returncode, 0, skipped.stderr)

        self.log.unlink(missing_ok=True)
        partial = self.run_launch(
            "--folder",
            str(self.work),
            "w1",
            "w2",
            env_overrides={"FAKE_FAIL_SECOND": "1"},
        )
        self.assertNotEqual(partial.returncode, 0)
        self.assertEqual(
            json.loads(partial.stdout.strip()),
            {"name": "w1", "tab": "tb1", "terminal": "t1"},
        )


class ReceiptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / "db.sqlite"
        self.rollout_dir = self.root / "rollout"
        self.rollout_dir.mkdir()
        self.work_dir = (self.root / "repo").resolve()
        self.work_dir.mkdir()

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE session (
                    id text primary key,
                    directory text not null,
                    title text not null,
                    version text not null,
                    time_created integer not null,
                    time_updated integer not null,
                    last_outcome text
                );
                CREATE TABLE model_usage (
                    id text primary key,
                    session_id text not null,
                    provider_id text not null,
                    model_id text not null,
                    variant text,
                    mode text,
                    status text not null,
                    started_at integer not null,
                    input_tokens integer not null default 0,
                    output_tokens integer not null default 0,
                    reasoning_tokens integer not null default 0,
                    cache_creation_input_tokens integer not null default 0,
                    cache_read_input_tokens integer not null default 0,
                    provider_total_tokens integer,
                    computed_total_tokens integer not null default 0,
                    error_code text,
                    error_message text
                );
                CREATE TABLE message (
                    id text primary key,
                    session_id text not null,
                    time_created integer not null,
                    data text not null,
                    sequence integer
                );
                CREATE TABLE part (
                    id text primary key,
                    message_id text not null,
                    session_id text not null,
                    time_created integer not null,
                    data text not null,
                    sequence integer
                );
                """
            )
            conn.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "sess_1",
                    str(self.work_dir),
                    "Map repo",
                    "0.17.1",
                    1000,
                    2500,
                    "completed",
                ),
            )
            conn.execute(
                "INSERT INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "u1",
                    "sess_1",
                    "account:zai",
                    "GLM-5.3-Flash",
                    "high",
                    "build",
                    "error",
                    1100,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    "3008",
                    None,
                ),
            )
            conn.execute(
                "INSERT INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "u2",
                    "sess_1",
                    "account:zai",
                    "GLM-5.3-Flash",
                    "high",
                    "build",
                    "completed",
                    1200,
                    1000,
                    50,
                    10,
                    0,
                    900,
                    1050,
                    1050,
                    None,
                    None,
                ),
            )
            conn.execute(
                "INSERT INTO model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "u3",
                    "sess_1",
                    "account:zai",
                    "GLM-5.3",
                    "max",
                    "build",
                    "error",
                    1250,
                    0,
                    0,
                    0,
                    0,
                    0,
                    None,
                    0,
                    None,
                    "[1113][Insufficient balance]",
                ),
            )
            conn.execute(
                "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
                ("m1", "sess_1", 1300, json.dumps({"role": "assistant"}), 1),
            )
            conn.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "p1",
                    "m1",
                    "sess_1",
                    1301,
                    json.dumps({"type": "text", "text": "Mapped successfully."}),
                    1,
                ),
            )
            conn.execute(
                "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "sess_rollout",
                    str(self.root / "other"),
                    "Empty db usage",
                    "0.17.1",
                    3000,
                    4000,
                    "completed",
                ),
            )
        (self.rollout_dir / "model-io-sess_rollout.jsonl").write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "model": "GLM-5.3-Flash",
                            "response": {
                                "modelId": "GLM-5.3-Flash",
                                "text": "Recovered from rollout",
                                "usage": {
                                    "inputTokens": 200,
                                    "outputTokens": 25,
                                    "cacheReadTokens": 150,
                                    "totalTokens": 225,
                                },
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "model": "GLM-5.3-Flash",
                            "error": {"message": "exceed quota limit"},
                            "response": {"usage": {}},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def run_receipt(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RECEIPT),
                "--db",
                str(self.db_path),
                "--rollout-dir",
                str(self.rollout_dir),
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def test_lookup_by_dir_since_and_include_reply(self) -> None:
        proc = self.run_receipt(
            "--dir", str(self.work_dir), "--since", "2000", "--include-reply"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["source"], "sqlite")
        self.assertEqual(data["session"]["id"], "sess_1")
        self.assertEqual(data["usage"]["request_count"], 3)
        self.assertEqual(data["usage"]["error_codes"], ["3008"])
        self.assertEqual(
            data["usage"]["error_messages"], ["[1113][Insufficient balance]"]
        )
        self.assertEqual(data["usage"]["statuses"], {"completed": 1, "error": 2})
        self.assertEqual(data["usage"]["cache_read_input_tokens"], 900)
        self.assertEqual(data["usage"]["provider_total_tokens"], 1050)
        self.assertEqual(data["last_assistant_text"], "Mapped successfully.")

    def test_rollout_fallback_and_refusals(self) -> None:
        proc = self.run_receipt("--session", "sess_rollout", "--include-reply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["source"], "rollout")
        self.assertEqual(data["usage"]["error_messages"], ["exceed quota limit"])
        self.assertEqual(data["usage"]["input_tokens"], 200)
        self.assertEqual(data["usage"]["cache_read_input_tokens"], 150)
        self.assertEqual(data["last_assistant_text"], "Recovered from rollout")

        missing = self.run_receipt("--session", "sess_unknown")
        self.assertNotEqual(missing.returncode, 0)

        no_db = subprocess.run(
            [
                sys.executable,
                str(RECEIPT),
                "--db",
                str(self.root / "nope.sqlite"),
                "--dir",
                str(self.work_dir),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(no_db.returncode, 0)
