"""Cache invalidation, repeat-hit speed path, safety and offline test coverage."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osu_tools import cache
from osu_tools.binary import FormatError
from osu_tools.cli import main_collections
from tests.fixtures import make_collections, make_osudb, make_scores

A, B, C = 'a'*32, 'b'*32, 'c'*32


class LibraryCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'Songs').mkdir()
        self.patch = patch.dict(os.environ, {
            'OSU_SONGS': str(self.root / 'Songs'),
            'XDG_CACHE_HOME': str(self.root / 'cachedir'),
            'XDG_DATA_HOME': str(self.root / 'datadir'),
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.osudb = self.root / 'osu!.db'
        self.scores = self.root / 'scores.db'
        self.coll = self.root / 'collection.db'
        make_osudb(self.osudb, [(A, 0, 4), (B, 1, 7)])
        make_scores(self.scores, [(A, [(0, 0)])])
        make_collections(self.coll, [
            ('all', [A]), ('std all', []), ('taiko all', [B]),
            ('ctb', []), ('mania all', []), ('all loved', []), ('all played', [])
        ])

    def test_beatmap_cache_hit_does_not_parse_source(self):
        initial = cache.cached_beatmaps(self.osudb)
        self.assertEqual(set(initial[2]), {A, B})
        with patch.object(cache, 'load_beatmaps', side_effect=AssertionError('reparsed')):
            cached = cache.cached_beatmaps(self.osudb)
        self.assertEqual(cached, initial)
        self.assertTrue((cache.index_dir()/cache.CACHE_FILENAME).exists())

    def test_scores_cache_hit_does_not_parse_source(self):
        self.assertEqual(cache.cached_played_hashes(self.scores), {A})
        with patch.object(cache, 'played_hashes', side_effect=AssertionError('reparsed')):
            self.assertEqual(cache.cached_played_hashes(self.scores), {A})

    def test_beatmap_source_change_rebuilds(self):
        cache.cached_beatmaps(self.osudb)
        make_osudb(self.osudb, [(C, 3, 7)])
        self.assertEqual(set(cache.cached_beatmaps(self.osudb)[2]), {C})
        with patch.object(cache, 'load_beatmaps', side_effect=AssertionError('reparsed')):
            self.assertEqual(set(cache.cached_beatmaps(self.osudb)[2]), {C})

    def test_scores_change_rebuilds(self):
        cache.cached_played_hashes(self.scores)
        make_scores(self.scores, [(B, [(1, 0)])])
        self.assertEqual(cache.cached_played_hashes(self.scores), {B})

    def test_same_size_changed_mtime_invalidates(self):
        cache.cached_beatmaps(self.osudb)
        now = self.osudb.stat().st_mtime_ns
        os.utime(self.osudb, ns=(now, now + 1_000_000))
        with patch.object(cache, 'load_beatmaps', wraps=cache.load_beatmaps) as read:
            cache.cached_beatmaps(self.osudb)
        self.assertEqual(read.call_count, 1)

    def test_refresh_forces_reparse(self):
        cache.cached_played_hashes(self.scores)
        with patch.object(cache, 'iter_saved_scores', wraps=cache.iter_saved_scores) as read:
            cache.cached_played_hashes(self.scores, refresh=True)
        self.assertEqual(read.call_count, 1)

    def test_no_cache_does_not_create_cache_file(self):
        cache.cached_beatmaps(self.osudb, enabled=False)
        cache.cached_played_hashes(self.scores, enabled=False)
        self.assertFalse((cache.index_dir()/cache.CACHE_FILENAME).exists())

    def test_source_changes_during_parsing_refused(self):
        def change_file(path):
            result = original(path)
            make_osudb(self.osudb, [(C, 3, 7)])
            return result
        original = cache.load_beatmaps
        with patch.object(cache, 'load_beatmaps', side_effect=change_file):
            with self.assertRaisesRegex(FormatError, 'changed while'):
                cache.cached_beatmaps(self.osudb)

    def test_corrupted_cache_falls_back_to_source(self):
        cache.cached_beatmaps(self.osudb)
        cachepath = cache.index_dir()/cache.CACHE_FILENAME
        manifest = cache._manifest(cache.index_dir())
        (cache.index_dir()/manifest['beatmaps']['file']).write_bytes(b'invalid jsonl\n')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            _, _, maps = cache.cached_beatmaps(self.osudb)
        self.assertEqual(set(maps), {A, B})
        self.assertIn('damaged', err.getvalue())

    def test_integrated_cache_and_safe_apply(self):
        before = self.coll.read_bytes()
        for args in (['sync', '--timings'], ['sync', '--timings']):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main_collections(args), 0)
            self.assertIn('Timings:', out.getvalue())
            self.assertEqual(self.coll.read_bytes(), before)
        with patch('osu_tools.safety.game_is_running', return_value=False), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main_collections(['sync', '--apply']), 0)
        self.assertEqual(len(list(self.root.glob('collection.db.bak.*'))), 1)
        self.assertEqual(list(self.root.glob('collection.db.bak.*'))[0].read_bytes(), before)

    def test_apply_refuses_changed_source_during_sync(self):
        from osu_tools import cli
        original = cli.sync_collection_rules
        def swap_source(*args, **kwargs):
            changes = original(*args, **kwargs)
            make_osudb(self.osudb, [(C, 0, 4)])
            return changes
        with patch('osu_tools.safety.game_is_running', return_value=False), \
             patch.object(cli, 'sync_collection_rules', side_effect=swap_source), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(Exception, 'osu!.db changed during sync'):
                cli.main_collections(['sync','--apply'])
        self.assertFalse(list(self.root.glob('collection.db.bak.*')))


if __name__ == '__main__':
    unittest.main()
