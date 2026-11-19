"""Discover only unit tests under tests/, under offline guards before imports."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import os

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))
from offline_guard import offline_boundaries


def main():
    runtime_environment = {key: value for key, value in os.environ.items()
                           if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
    with patch.dict(os.environ, runtime_environment, clear=True), offline_boundaries() as attempts:
        suite = unittest.defaultTestLoader.discover(str(root / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"Unmocked external boundary attempts: {len(attempts)}")
    return 0 if result.wasSuccessful() and not attempts else 1


if __name__ == "__main__":
    sys.exit(main())
