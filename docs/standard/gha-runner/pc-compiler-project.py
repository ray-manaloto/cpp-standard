"""Build the archived checkout with the three native presets inside the qualified image."""

import json
import os
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = (
    ("gcc16", "x64-linux-gcc16", "/usr/bin/g++-16"),
    ("clang23", "x64-linux-clang23-libcxx", "/usr/bin/clang++-23"),
    ("p2996", "x64-linux-p2996-libcxx", "/opt/p2996/bin/clang++"),
)
SOURCES = ("src/cppstd/core.cppm", "src/standin/standin.cppm")
TESTS = ("core_test", "standin_test")


def check_tests(report):
    rows = sorted(
        (
            row.attrib["name"],
            row.get("status"),
            any(row.find(tag) is not None for tag in ("failure", "error", "skipped")),
        )
        for row in ET.parse(report).iter("testcase")
    )
    if rows != [(name, "run", False) for name in TESTS]:
        raise ValueError(f"expected two named passing CTest cases, observed {rows}")


def check_project(source, build, evidence, triplet, compiler, launcher):
    cache = (build / "CMakeCache.txt").read_text().splitlines()
    # The project enables CXX. Only enabled languages initialize a launcher cache entry.
    if [
        line.partition("=")[2]
        for line in cache
        if line.startswith("CMAKE_CXX_COMPILER_LAUNCHER:")
    ] != [launcher]:
        raise ValueError(f"unexpected C++ compiler launcher for {triplet}")
    for key in ("VCPKG_TARGET_TRIPLET", "VCPKG_HOST_TRIPLET"):
        if [line.partition("=")[2] for line in cache if line.startswith(key + ":")] != [
            triplet
        ]:
            raise ValueError(f"unexpected {key} for {triplet}")
    # Manifest-mode vcpkg installs only the selected compiler's dependency tree.
    status = (build / "vcpkg_installed/vcpkg/status").read_text()
    if not any(
        {"Package: bext-ut", f"Architecture: {triplet}", "Status: install ok installed"}
        <= set(p.splitlines())
        for p in status.split("\n\n")
    ):
        raise ValueError(f"missing installed bext-ut for {triplet}")
    (evidence / "vcpkg-status.txt").write_text(status)
    commands = json.loads((build / "compile_commands.json").read_bytes())
    for module in SOURCES:
        matching = [
            entry
            for entry in commands
            if (Path(entry["directory"]) / entry["file"]).resolve() == source / module
        ]
        if not matching:
            raise ValueError(f"no compilation command for {module}")
        for entry in matching:
            args = (
                entry["arguments"]
                if "arguments" in entry
                else shlex.split(entry["command"])
            )
            if args[0] == launcher:
                args = args[1:]
            if Path(args[0]).resolve() != Path(compiler).resolve():
                raise ValueError(f"unexpected compiler for {module}: {args[0]}")
            if triplet.endswith("-libcxx") and module == SOURCES[0]:
                # Replay the actual preset's ordered preprocessor settings. A
                # later -U or conflicting -D must invalidate the result.
                flags = [
                    value
                    for value in args[1:]
                    if value.startswith(("-std=", "-stdlib=", "-D", "-U"))
                ]
                macros = subprocess.check_output(
                    [compiler, *flags, "-dM", "-E", "-x", "c++", "-"],
                    input="#include <version>\n#if !defined(_LIBCPP_VERSION) || !defined(_LIBCPP_HARDENING_MODE_EXTENSIVE) || _LIBCPP_HARDENING_MODE != _LIBCPP_HARDENING_MODE_EXTENSIVE\n#error expected extensive libc++ hardening\n#endif\n",
                    text=True,
                )
                (evidence / "hardening.txt").write_text(
                    shlex.join([compiler, *flags])
                    + "\n"
                    + "\n".join(
                        m
                        for m in macros.splitlines()
                        if m.startswith(
                            (
                                "#define _LIBCPP_HARDENING_MODE",
                                "#define _LIBCPP_VERSION ",
                            )
                        )
                    )
                    + "\n"
                )

    output = subprocess.check_output(["ldd", str(build / "tests/core_test")], text=True)
    (evidence / "core_test.ldd").write_text(output)
    lib = "libstdc++.so.6" if triplet == "x64-linux-gcc16" else "libc++.so.1"
    other = "libc++.so.1" if lib == "libstdc++.so.6" else "libstdc++.so.6"
    paths = [
        line.split()[2]
        for line in output.splitlines()
        if line.strip().startswith(lib + " => /")
    ]
    if len(paths) != 1 or other + " =>" in output or "not found" in output:
        raise ValueError(f"unexpected C++ runtime for {triplet}: {output}")
    resolved = Path(paths[0]).resolve(strict=True)
    expected_root = Path(
        "/opt/p2996" if compiler.startswith("/opt/p2996/") else "/usr/lib"
    )
    if not resolved.is_relative_to(expected_root):
        raise ValueError(f"{triplet} loaded {resolved}")


def main():
    source = Path("/tmp/cpp-standard-project")
    evidence = Path("/tmp/project-evidence")
    evidence.mkdir()
    shutil.copytree("/project", source, symlinks=True)
    os.chdir(source)
    os.environ.update(MISE_PROJECT_ROOT=str(source), CPPSTD_P2996_PREFIX="/opt/p2996")
    # The existing bootstrap reads the baseline from this exact checkout.
    subprocess.run(["bash", ".mise/tasks/vcpkg/bootstrap"], check=True)
    launcher = shutil.which("sccache")
    if not launcher:
        raise RuntimeError("locked sccache executable missing")
    os.environ.update(
        CMAKE_C_COMPILER_LAUNCHER=launcher, CMAKE_CXX_COMPILER_LAUNCHER=launcher
    )
    for name, triplet, compiler in TOOLS:
        preset = f"{name}-coverage-amd64"
        build = source / "build" / preset
        dest = evidence / preset
        dest.mkdir()
        junit = dest / "ctest.xml"
        subprocess.run([launcher, "--zero-stats"], check=True)
        for argv in (
            ["cmake", "--preset", preset],
            ["cmake", "--build", "--preset", preset, "--parallel", "6"],
            [
                "ctest",
                "--preset",
                preset,
                "--no-tests=error",
                "--output-on-failure",
                "--output-junit",
                str(junit),
            ],
        ):
            print(shlex.join(argv), flush=True)
            rc = subprocess.run(argv, check=False).returncode
            print(f"exit={rc} {shlex.join(argv)}", flush=True)
            if rc != 0 or argv[0] == "ctest":
                with (dest / "sccache.json").open("w") as report:
                    stats = subprocess.run(
                        [launcher, "--show-stats", "--stats-format=json"],
                        stdout=report,
                        check=False,
                    )
                if rc == 0:
                    stats.check_returncode()
            if rc != 0:
                raise SystemExit(rc if rc > 0 else 128 - rc)
        check_tests(junit)
        for filename in ("CMakeCache.txt", "compile_commands.json"):
            shutil.copyfile(build / filename, dest / filename)
        check_project(source, build, dest, triplet, compiler, launcher)
        print(f"PASS {preset} {triplet} {compiler} core_test standin_test", flush=True)


if __name__ == "__main__":
    main()
