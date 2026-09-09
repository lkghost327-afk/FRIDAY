from pathlib import Path
from tempfile import TemporaryDirectory
import os
import sys
import unittest
from unittest.mock import patch

from assistant_core.app import data_directory


class RepositoryPathTests(unittest.TestCase):
    def test_private_state_is_outside_checkout_for_source_and_executable(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            for persona, name in (("friday", "FRIDAY"), ("alfred", "ALFRED")):
                expected = Path(tmp) / "FanAssistants" / name
                self.assertEqual(data_directory("C:/arbitrary/repository/app.py", persona), expected)
                with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "C:/arbitrary/dist/assistant.exe"):
                    self.assertEqual(data_directory("ignored", persona), expected)


if __name__ == "__main__":
    unittest.main()
