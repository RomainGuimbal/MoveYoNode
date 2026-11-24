"""Run the move_yo_node test suite inside Blender.

Usage:
    python run_tests.py                 # run everything
    python run_tests.py test_levels     # run one module
    python run_tests.py -v              # verbose

The suite runs in a throwaway Blender process started with --factory-startup,
so the user's Blender preferences are never read or written.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"
BLENDER = os.environ.get("MYN_BLENDER", "")

# Script executed inside Blender. The paths are derived from this file's
# location, so no absolute path is ever written down.
INNER = r"""
import sys, unittest
sys.path.insert(0, {repo_root!r})
sys.path.insert(0, {src_dir!r})
import tests

loader = unittest.TestLoader()
names = {names!r}
if names:
    suite = unittest.TestSuite(
        loader.loadTestsFromName(
            n if "." in n else "tests." + n
        ) for n in names
    )
else:
    suite = loader.discover(
        {tests_dir!r}, pattern="test_*.py", top_level_dir={repo_root!r}
    )

runner = unittest.TextTestRunner(verbosity={verbosity})
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def find_blender() -> str:
    if BLENDER:
        return BLENDER
    if sys.platform == "win32":
        candidates = sorted(
            Path("C:/Program Files/Blender Foundation").glob("Blender */blender.exe")
        )
        if candidates:
            return str(candidates[-1])
    return "blender"


def main(argv: list[str]) -> int:
    verbose = "-v" in argv
    names = [a for a in argv if not a.startswith("-")]

    script = INNER.format(
        repo_root=str(REPO_ROOT),
        src_dir=str(SRC_DIR),
        tests_dir=str(TESTS_DIR),
        names=names,
        verbosity=2 if verbose else 1,
    )

    blender = find_blender()
    if not Path(blender).exists() and blender != "blender":
        print(f"Blender not found at {blender}", file=sys.stderr)
        return 2

    cmd = [
        blender,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python-expr",
        script,
    ]
    print(f"Running tests with {blender}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
