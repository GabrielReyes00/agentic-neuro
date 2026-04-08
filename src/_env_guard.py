"""Shared venv & working directory guard for CLI scripts.

Ensures the correct virtualenv is active and CWD is the project root,
even when invoked from a different directory or with a system Python.
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXPECTED_VENV = os.path.join(PROJECT_ROOT, ".venv")


def check_environment(marker_file: str = "lance_retriever.py"):
    """Verify venv and working directory at startup (CLI only).

    Args:
        marker_file: filename in src/ used to detect correct CWD.
    """
    if not os.path.isfile(os.path.join(os.getcwd(), "src", marker_file)):
        os.chdir(PROJECT_ROOT)
    current_prefix = os.path.abspath(getattr(sys, "prefix", ""))
    expected_abs = os.path.abspath(_EXPECTED_VENV)
    if os.path.isdir(expected_abs) and expected_abs not in current_prefix:
        correct_python = os.path.join(expected_abs, "bin", "python3")
        if os.path.isfile(correct_python):
            cmd = [correct_python] + sys.argv
            if sys.platform == "darwin" and os.path.isfile("/usr/bin/arch"):
                cmd = ["/usr/bin/arch", "-arm64"] + cmd
            result = subprocess.run(cmd, cwd=PROJECT_ROOT)
            sys.exit(result.returncode)
        print(
            f"Wrong Python ({sys.executable}) and venv not found at {expected_abs}",
            file=sys.stderr,
        )
        sys.exit(1)
