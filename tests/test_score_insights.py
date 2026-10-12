"""Saved-score grouping and summaries over real synthetic binary DB fixtures."""
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
from osu_tools.scores import best_saved_per_difficulty, summarize_saved_scores
from tests.fixtures import make_osudb, make_scores

A = 'a' * 32
B = 'b' * 32


class ScoreInsightsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'Songs').mkdir()
        env = patch.dict(os.environ, {'OSU_SONGS': str(self.root / 'Songs'),
                                   'XDG_DATA_HOME': str(self.root / 'data'),
                                   'XDG_CACHE_HOME': str(self.root / 'cache')})
        env.start()
        self.addCleanup(env.stop)
        # A is native standard but is intentionally scored using taiko and mania.
        make_osudb(self.root / 'osu!.db', [(A, 0, 4), (B, 3, 4)])
        self.scores = self.root / 'scores.db'
        make_scores(self.scores, [(A, [(1, 0, 100), (1, 0, 150),
                                      (1, 8, 90), (3, 0, 20)]),
                                  (B, [(3, 0, 200)])])

    def cli_json(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main_scores(args + ['--json']), 0)
        return json.loads(out.getvalue())

    def test_best_grouping_keeps_modes_and_mods_distinct(self):
        n, groups, rows = best_saved_per_difficulty(self.scores, limit=20)
        self.assertEqual((n, groups), (5, 4))
        self.assertEqual([r['score'] for r in rows], [200, 150, 90, 20])
        taiko = self.cli_json(['pbs', '--mode', 'taiko'])
        self.assertEqual((taiko['matching_count'], taiko['unique_groups']), (3, 2))
        self.assertEqual([r['score'] for r in taiko['scores']], [150, 90])
        self.assertTrue(all(r['mode_name'] == 'taiko' for r in taiko['scores']))

    def test_summary_reports_unique_maps_and_most_played(self):
        report = self.cli_json(['summary'])
        self.assertEqual((report['saved_scores'], report['unique_difficulties']), (5, 2))
        modes = {r['mode_name']: r for r in report['modes']}
        self.assertEqual((modes['taiko']['plays'], modes['taiko']['unique_difficulties']), (3, 1))
        self.assertEqual(modes['taiko']['most_played_count'], 3)
        self.assertEqual(modes['taiko']['most_played_map_md5'], A)
        self.assertEqual((modes['mania']['plays'], modes['mania']['unique_difficulties']), (2, 2))
        self.assertIsNone(modes['mania']['mean_accuracy_percent'])
        self.assertEqual(self.cli_json(['summary', '--mode', 'taiko'])['saved_scores'], 3)

    def test_best_query_and_player(self):
        # Search is map-label-based; 'Song 0' corresponds to A.
        top = self.cli_json(['pbs', 'Song 0', '--player', 'test user', '--limit', '1'])
        self.assertEqual((top['matching_count'], top['unique_groups']), (4, 3))
        self.assertEqual([r['score'] for r in top['scores']], [150])
        self.assertEqual(self.cli_json(['pbs', '--player', 'nobody'])['matching_count'], 0)
        self.assertEqual(self.cli_json(['summary', '--mode', 'catch'])['modes'], [])

    def test_two_players_have_independent_bests(self):
        make_scores(self.scores, [(A, [(1, 0, 100, 0, 'Player A'),
                                      (1, 0, 200, 0, 'Player B')])])
        plays, groups, top = best_saved_per_difficulty(self.scores)
        self.assertEqual((plays, groups), (2, 2))
        self.assertEqual({r['player'] for r in top}, {'Player A', 'Player B'})
        plays, groups, top = best_saved_per_difficulty(self.scores, player='player a')
        self.assertEqual((plays, groups), (1, 1))
        self.assertEqual(top[0]['score'], 100)

    def test_corruption_rebuilds_and_scores_db_unchanged(self):
        original = self.scores.read_bytes()
        best_saved_per_difficulty(self.scores)
        meta = cache._manifest(cache.index_dir())
        (cache.index_dir() / meta['scores']['file']).write_text('bad\n')
        n, groups, _ = best_saved_per_difficulty(self.scores)
        self.assertEqual((n, groups), (5, 4))
        self.assertEqual(self.scores.read_bytes(), original)

    def test_original_recent_and_best_commands_unchanged(self):
        recent = self.cli_json(['recent', '--limit', '2'])
        self.assertEqual(recent['matching_count'], 5)
        self.assertEqual(len(recent['scores']), 2)
        best = self.cli_json(['best', '--limit', '1'])
        self.assertEqual(best['scores'][0]['score'], 200)


if __name__ == '__main__':
    unittest.main()
