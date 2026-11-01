import os
from pathlib import Path
import subprocess
import sys
import unittest


class ImportSafetyTests(unittest.TestCase):
    def test_clean_process_imports_without_configuration_or_side_effects(self):
        root = Path(__file__).resolve().parents[1]
        environment = {key: value for key, value in os.environ.items() if key not in {
            "DATABASE_URL", "OPENAI_API_KEY", "GEE_PROJECT", "CORS_ORIGINS",
            "GOOGLE_APPLICATION_CREDENTIALS", "GEE_SERVICE_ACCOUNT_JSON",
        }}
        environment["PYTHONPATH"] = str(root)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(root / "tests/import_safety_probe.py")],
            cwd=root / "tests", env=environment, capture_output=True, text=True, encoding="utf-8",
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"boundary_attempts": 0', result.stdout)
