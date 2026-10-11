import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osu_tools.cli import main_collections
from osu_tools.safety import SafetyError
from osu_tools.database import load_collections
from tests.fixtures import make_collections, make_osudb, make_scores

A, B = 'a'*32, 'b'*32
class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'Songs').mkdir()
        make_osudb(self.root/'osu!.db',[(A,0,4),(B,1,7)])
        make_collections(self.root/'collection.db', [('all',[A]), ('std all',[]),
                                                       ('taiko all',[B]), ('ctb',[]),
                                                       ('mania all',[]), ('all loved',[]),
                                                       ('all played',[])])
        make_scores(self.root/'scores.db',[(A,[(0,0)])])
        self.patch = patch.dict(os.environ,{'OSU_SONGS': str(self.root/'Songs'), 'XDG_CACHE_HOME':str(self.root/'cache')})
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_dry_run_then_apply_then_noop(self):
        path=self.root/'collection.db'
        original=path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main_collections(['sync']),0)
        self.assertEqual(path.read_bytes(), original)
        with patch('osu_tools.safety.game_is_running',return_value=False),\
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main_collections(['sync','--apply']),0)
        self.assertNotEqual(path.read_bytes(),original)
        backups=list(self.root.glob('collection.db.bak.*'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),original)
        coll=load_collections(path)
        self.assertIn(B, coll.find('all').hashes)
        self.assertIn(B, coll.find('all loved').hashes)
        self.assertIn(A, coll.find('all played').hashes)
        updated=path.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main_collections(['sync']),0)
        self.assertEqual(path.read_bytes(),updated)

    def test_bulk_apply_refused_without_explicit_approval(self):
        many = [(f'{i:032x}', 0, 7) for i in range(1100)]
        make_osudb(self.root/'osu!.db', many)
        path = self.root/'collection.db'
        original = path.read_bytes()
        with patch('osu_tools.safety.game_is_running',return_value=False),\
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(SafetyError, 'bulk apply'):
                main_collections(['sync-loved', '--apply'])
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.root.glob('collection.db.bak.*')))
        with patch('osu_tools.safety.game_is_running',return_value=False),\
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main_collections(['sync-loved', '--apply', '--allow-large']), 0)
        self.assertEqual(len(load_collections(path).find('all loved').hashes), 1100)

    def test_mass_prune_refused_without_explicit_approval(self):
        many = [(f'{i:032x}', 0, 4) for i in range(110)]
        make_osudb(self.root/'osu!.db', many)
        make_collections(self.root/'collection.db', [('all',[]), ('std all', []),
                          ('ctb', [h for h,_,_ in many]), ('taiko all', []),
                          ('mania all', []), ('all loved', []), ('all played', [])])
        path = self.root/'collection.db'
        original = path.read_bytes()
        with patch('osu_tools.safety.game_is_running',return_value=False),\
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(SafetyError, 'bulk apply'):
                main_collections(['sync','--prune-mismatches','--apply'])
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.root.glob('collection.db.bak.*')))

if __name__=='__main__': unittest.main()
