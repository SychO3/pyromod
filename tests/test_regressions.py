import subprocess
import sys
import unittest
from pathlib import Path

from pyromod.types.identifier import Identifier


ROOT = Path(__file__).resolve().parents[1]


class ImportRegressionTests(unittest.TestCase):
    def test_import_pyromod_succeeds_in_subprocess(self):
        result = subprocess.run(
            [sys.executable, "-c", "import pyromod; print('import ok')"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            self.fail(
                "Importing pyromod failed.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

        self.assertIn("import ok", result.stdout)


class IdentifierRegressionTests(unittest.TestCase):
    def test_matches_handles_scalar_and_list_values(self):
        listener_identifier = Identifier(
            chat_id=12345,
            message_id=77,
            from_user_id=["alice", 1001],
        )
        update_identifier = Identifier(
            chat_id=[12345, "example_chat"],
            message_id=77,
            from_user_id=1001,
        )

        self.assertTrue(listener_identifier.matches(update_identifier))

    def test_matches_rejects_non_matching_values(self):
        listener_identifier = Identifier(chat_id=12345, from_user_id=["alice", 1001])
        update_identifier = Identifier(chat_id=[12345, "example_chat"], from_user_id=2002)

        self.assertFalse(listener_identifier.matches(update_identifier))

    def test_count_populated_counts_only_non_null_fields(self):
        identifier = Identifier(chat_id=12345, from_user_id=["alice", 1001])

        self.assertEqual(identifier.count_populated(), 2)


if __name__ == "__main__":
    unittest.main()
