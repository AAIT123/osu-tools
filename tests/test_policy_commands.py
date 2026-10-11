import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_tools.cli import main_collections


class PolicyCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        p = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.dir)})
        p.start()
        self.addCleanup(p.stop)

    def call(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main_collections(arguments)

    def test_explicit_add_and_remove(self):
        self.assertEqual(self.call(['policy-add', 'taiko dr', 'taiko all']), 0)
        filename = self.dir/'osu-tools'/'collections.json'
        self.assertEqual(filename.stat().st_mode & 0o777, 0o600)
        saved = json.loads(filename.read_text())
        self.assertEqual(saved['variant_sources'], {'taiko dr': 'taiko all'})
        self.assertEqual(self.call(['policy-remove', 'taiko dr']), 0)
        self.assertEqual(json.loads(filename.read_text())['variant_sources'], {})

    def test_unrelated_std_hdhr_never_inferred(self):
        self.assertEqual(self.call(['policy-add', 'mania ln', 'mania all']), 0)
        saved = json.loads((self.dir/'osu-tools'/'collections.json').read_text())
        self.assertNotIn('std hdhr', saved['variant_sources'])

    def test_bad_sources_and_targets_rejected(self):
        with self.assertRaises(SystemExit):
            self.call(['policy-add', 'taiko hr', 'std converts'])
        with self.assertRaises(SystemExit):
            self.call(['policy-add', 'taiko all', 'taiko all'])
        self.assertEqual(self.call(['policy-remove', 'not here']), 1)


if __name__ == '__main__':
    unittest.main()
