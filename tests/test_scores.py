"""Offline saved-score browser: binary->JSONL, integrity and display math."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_tools import cache
from osu_tools.cli import main_scores
from osu_tools.scores import accuracy, find_scores, mod_string, map_checksum, utc_time
from tests.fixtures import make_osudb, make_scores

A = 'a' * 32
B = 'b' * 32
C = 'c' * 32


def score(mode=0, **kwargs):
    base = dict(mode=mode, n300=0, n100=0, n50=0, ngeki=0, nkatu=0,
                nmiss=0, score=10000, timestamp_ticks=0, player='Test User',
                map_md5=A, mods_bitmask=0, max_combo=35)
    base.update(kwargs)
    return base


class ScoreFormatTests(unittest.TestCase):
    def test_accuracy_rulesets_and_zero_denominator(self):
        self.assertEqual(accuracy(score(0, n300=2, n100=1, n50=1, nmiss=1)), 50.0)
        self.assertEqual(accuracy(score(1, n300=1, n100=1, nmiss=1)), 50.0)
        self.assertEqual(accuracy(score(2, n300=2, n100=1, n50=1, nkatu=1, nmiss=1)), 66.67)
        self.assertEqual(accuracy(score(3, ngeki=1, n300=1, nkatu=1, n100=1, n50=1, nmiss=1)), 52.78)
        self.assertIsNone(accuracy(score(0)))

    def test_mods_and_date(self):
        self.assertEqual(mod_string(0), 'NM')
        self.assertEqual(mod_string(64 | 512), 'NC')
        self.assertEqual(mod_string(32 | 16384), 'PF')
        self.assertIn('HD', mod_string(8 | 64))
        self.assertIsNone(utc_time(0))
        self.assertEqual(utc_time(621355968000000000), '1970-01-01 00:00 UTC')

    def test_map_resolution_checksum_and_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'hello.osu'
            p.write_bytes(b'osu file\n')
            import hashlib
            self.assertEqual(map_checksum(str(p)), hashlib.md5(p.read_bytes()).hexdigest())
            self.assertEqual(map_checksum(A.upper()), A)
            with self.assertRaises(ValueError):
                map_checksum(str(Path(td)/'missing.osu'))


class ScoreIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'Songs').mkdir()
        patches = patch.dict(os.environ, {'OSU_SONGS': str(self.root/'Songs'),
                         'XDG_DATA_HOME': str(self.root/'data'),
                         'XDG_CACHE_HOME': str(self.root/'cache')})
        patches.start(); self.addCleanup(patches.stop)
        make_osudb(self.root/'osu!.db', [(A, 0, 4), (B, 3, 4)])
        make_scores(self.root/'scores.db', [(A, [(0, 8), (0, 0)]), (B, [(3, 0)])])

    def test_recent_and_search_cli_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main_scores(['recent', '--json']), 0)
        obj = json.loads(out.getvalue())
        self.assertEqual(obj['matching_count'], 3)
        self.assertEqual(len(obj['scores']), 3)
        self.assertTrue(all('Artist ' in r['map_label'] for r in obj['scores']))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main_scores(['search', 'Song 1', '--json']), 0)
        obj = json.loads(out.getvalue())
        self.assertEqual(obj['matching_count'], 1)
        self.assertEqual(obj['scores'][0]['mode_name'], 'mania')

    def test_filter_map_mode_player_and_top(self):
        result = find_scores(self.root/'scores.db', limit=1, mode=0, eligible={A}, player='test user')
        self.assertEqual(result[0], 2)
        self.assertEqual(len(result[1]), 1)
        result = find_scores(self.root/'scores.db', limit=5, mode=3, eligible={A})
        self.assertEqual(result[0], 0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main_scores(['map', A, '--json']), 0)
        self.assertEqual(json.loads(out.getvalue())['matching_count'], 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main_scores(['best', '--mode', 'mania', '--json']), 0)
        self.assertEqual(json.loads(out.getvalue())['matching_count'], 1)

    def test_index_read_does_not_parse_original_on_cache_hit(self):
        find_scores(self.root/'scores.db', limit=1)
        with patch.object(cache, 'iter_saved_scores', side_effect=AssertionError('should reuse JSONL')):
            self.assertEqual(find_scores(self.root/'scores.db', limit=2)[0], 3)

    def test_corruption_rebuilds_verified_index(self):
        find_scores(self.root/'scores.db', limit=5)
        meta = cache._manifest(cache.index_dir())
        (cache.index_dir()/meta['scores']['file']).write_text('corrupt!\n')
        messages = []
        self.assertEqual(find_scores(self.root/'scores.db', limit=5, inform=messages.append)[0], 3)
        self.assertTrue(any('rebuilding' in m for m in messages))
        self.assertEqual(find_scores(self.root/'scores.db', limit=5)[0], 3)

    def test_source_change_invalidates_index(self):
        self.assertEqual(find_scores(self.root/'scores.db', limit=5)[0], 3)
        make_scores(self.root/'scores.db', [(B, [(3, 0)])])
        self.assertEqual(find_scores(self.root/'scores.db', limit=5)[0], 1)

    def test_limit_validation(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main_scores(['recent', '--limit', '0'])


if __name__ == '__main__':
    unittest.main()
