"""Readable archival snapshot and conservative personal-policy tests."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osu_tools import cache
from osu_tools.library import make_snapshot, list_snapshots
from osu_tools.database import load_beatmaps, load_collections
from osu_tools.collections import sync
from osu_tools.policy import Policy, init_policy, load_policy
from tests.fixtures import make_collections, make_osudb, make_scores

A, B = 'a'*32, 'b'*32


class ReadableLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'Songs').mkdir()
        self.env = patch.dict(os.environ, {
            'OSU_SONGS': str(self.root/'Songs'),
            'XDG_DATA_HOME': str(self.root/'data'),
            'XDG_CONFIG_HOME': str(self.root/'config'),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        make_osudb(self.root/'osu!.db', [(A,0,4),(B,1,7)])
        make_scores(self.root/'scores.db', [(A,[(0,0)]),(B,[(1,8388608)])])
        make_collections(self.root/'collection.db', [('all',[A]), ('std all',[]),
                     ('taiko all',[]), ('all played',[]), ('std hdhr', [A,B])])

    def test_index_is_readable_and_used_for_cache(self):
        _,_,maps=cache.cached_beatmaps(self.root/'osu!.db')
        played=cache.cached_played_hashes(self.root/'scores.db')
        self.assertEqual(set(maps),{A,B})
        self.assertEqual(played,{A,B})
        manifest=json.loads((cache.index_dir()/'manifest.json').read_text())
        scorepath=cache.index_dir()/manifest['scores']['file']
        details=[json.loads(l) for l in scorepath.read_text().splitlines()]
        self.assertEqual(len(details),2)
        self.assertEqual(details[1]['map_md5'],B)
        self.assertEqual(details[1]['mods_bitmask'],8388608)
        self.assertTrue('score' in details[1])
        with patch.object(cache,'load_beatmaps',side_effect=AssertionError('Parsed source again')):
            cache.cached_beatmaps(self.root/'osu!.db')
        with patch.object(cache,'iter_saved_scores',side_effect=AssertionError('Parsed source again')):
            cache.cached_played_hashes(self.root/'scores.db')

    def test_snapshot_progress_and_verification(self):
        from osu_tools.library import _copy_verified
        src = self.root/'little.osr'
        dst = self.root/'little-copy.osr'
        src.write_bytes(b'local replay bytes')
        digest = _copy_verified(src, dst)
        import hashlib
        self.assertEqual(digest, hashlib.sha256(src.read_bytes()).hexdigest())
        self.assertEqual(src.read_bytes(), dst.read_bytes())
        progress = []
        with patch('osu_tools.library.game_is_running', return_value=False):
            make_snapshot(progress=progress.append)
        self.assertTrue(any('original databases' in line for line in progress))
        self.assertTrue(any('Finalizing' in line for line in progress))

    def test_archived_snapshot_has_readable_and_exact_originals(self):
        with patch('osu_tools.library.game_is_running',return_value=False):
            path=make_snapshot()
        self.assertEqual(len(list_snapshots()),1)
        self.assertEqual((path/'originals'/'collection.db').read_bytes(),
                         (self.root/'collection.db').read_bytes())
        self.assertEqual((path/'originals'/'scores.db').read_bytes(),
                         (self.root/'scores.db').read_bytes())
        self.assertEqual((path/'originals'/'osu!.db').read_bytes(),
                         (self.root/'osu!.db').read_bytes())
        self.assertTrue((path/'collections.json').exists())
        self.assertIn('Artist 0', (path/'beatmaps.csv').read_text())
        self.assertIn('Test User', (path/'scores.csv').read_text())
        self.assertIn('all', (path/'collections.csv').read_text())
        self.assertTrue(list(path.glob('beatmaps-*.jsonl')))
        self.assertTrue(list(path.glob('scores-*.jsonl')))
        self.assertTrue(json.loads((path/'snapshot.json').read_text())['restorable_binary'])
        with patch('osu_tools.library.game_is_running',return_value=False):
            next_path=make_snapshot()
        self.assertNotEqual(path,next_path)

    def test_snapshot_refuses_live_osu_or_inconsistent_source(self):
        with patch('osu_tools.library.game_is_running',return_value=True):
            with self.assertRaisesRegex(Exception,'Close osu!'):
                make_snapshot()
        self.assertEqual(list_snapshots(),[])

    def test_policy_init_empty_and_no_implicit_std_hdhr(self):
        path=init_policy()
        self.assertEqual(path, self.root/'config'/'osu-tools'/'collections.json')
        with self.assertRaises(FileExistsError):
            init_policy()
        policy=load_policy()
        _,_,maps=load_beatmaps(self.root/'osu!.db')
        db=load_collections(self.root/'collection.db')
        ch=sync(db,maps,operations=('sync',),played=set(),policy=policy)
        self.assertNotIn('std all',ch.additions)
        self.assertNotIn(B,db.find('all').hashes)
        policy.variant_sources['std hdhr']='std all'
        ch=sync(db,maps,operations=('variants',),policy=policy)
        self.assertIn(A,db.find('std all').hashes)
        self.assertNotIn(B,db.find('std all').hashes)  # non-native

if __name__=='__main__':
    unittest.main()
