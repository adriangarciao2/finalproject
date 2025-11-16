import unittest
import shutil
from unittest.mock import patch, MagicMock

from mcp_tools.tests import run_maven


class TestMavenHelper(unittest.TestCase):
    def test_mvn_version_real(self):
        """Integration-like test: only runs if mvn is present on PATH."""
        mvn_path = shutil.which('mvn')
        if not mvn_path:
            self.skipTest("mvn not found in PATH; skipping real mvn helper test")

        out = run_maven(['-v'], project_root=None, timeout=30)
        # Flexible assertion: should mention Apache Maven or Maven home
        self.assertTrue(("Apache Maven" in out) or ("Maven home" in out) or ("Maven" in out))

    def test_run_maven_uses_shutil_which_and_runs(self):
        """Unit test: mock shutil.which and subprocess.run so test doesn't require Maven."""
        fake_mvn = r"C:\fake\maven\bin\mvn.CMD"

        fake_completed = MagicMock()
        fake_completed.stdout = "Apache Maven 3.9.11 (fake)\nMaven home: C:\fake\maven"

        with patch('shutil.which', return_value=fake_mvn) as mock_which:
            with patch('subprocess.run', return_value=fake_completed) as mock_run:
                out = run_maven(['-v'], project_root=None, timeout=10)

                # which should have been called for 'mvn'
                mock_which.assert_called_with('mvn')

                # subprocess.run should be invoked with the resolved path
                mock_run.assert_called()
                called_args = mock_run.call_args[0][0]
                self.assertEqual(called_args[0], fake_mvn)

                self.assertIn('Apache Maven', out)


if __name__ == '__main__':
    unittest.main()
