"""Public osu! API v2 response-shape checks; no credentials or network.

The documented endpoints can return either legacy/lazer scores unless callers
request legacy_only=1. The CLI preserves previous default behavior.
"""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_tools.api import Client
from osu_tools.cli import main_compare, main_profile


class ApiContractTests(unittest.TestCase):
    def test_legacy_only_is_opt_in(self):
        client = Client(token='fake')
        with patch.object(client, 'get', return_value={'scores': []}) as get:
            client.beatmap_scores(123, 'mania')
            get.assert_called_with('beatmaps/123/scores', {'mode': 'mania'})
            client.beatmap_scores(123, 'mania', legacy_only=True)
            get.assert_called_with('beatmaps/123/scores', {'mode': 'mania', 'legacy_only': 1})
            client.user_score(123, 7, 'taiko', legacy_only=True)
            get.assert_called_with('beatmaps/123/scores/users/7',
                                   {'mode': 'taiko', 'legacy_only': 1})

    def test_public_profile_report(self):
        resp = dict(username='Tester', id=123, country_code='JP',
                    statistics=dict(pp=1234.56, global_rank=100, country_rank=5,
                                    hit_accuracy=97.5, play_count=42, total_hits=2000))
        with patch('osu_tools.api.Client.user', return_value=resp), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main_profile(['Tester', '--mode', 'taiko']), 0)
        self.assertIn('1,234.56', out.getvalue())
        self.assertIn('https://osu.ppy.sh/users/123/taiko', out.getvalue())

    def test_compare_ranks_and_personal_placement_with_mock_responses(self):
        beatmap = dict(id=12, mode='osu', version='Expert', difficulty_rating=5.2,
                       beatmapset=dict(artist='Artist', title='Track'))
        score = dict(user=dict(username='Winner'), pp=100.5, accuracy=.985,
                     max_combo=500, mods=[dict(acronym='HD')], score=10000)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'map.osu'
            path.write_text('osu file')
            with patch('osu_tools.api.Client.beatmap_for_checksum', return_value=beatmap), \
                 patch('osu_tools.api.Client.beatmap_scores', return_value={'scores': [score]}) as scores, \
                 patch('osu_tools.api.Client.user', return_value=dict(username='Tester', id=44)), \
                 patch('osu_tools.api.Client.user_score', return_value={'position': 3, 'score': score}) as personal, \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main_compare([str(path), '--user', 'Tester', '--top', '1', '--legacy-only']), 0)
            result = out.getvalue()
            self.assertIn('#1', result)
            self.assertIn('98.50%', result)
            self.assertIn('position #3', result)
            scores.assert_called_once_with(12, 'osu', legacy_only=True)
            personal.assert_called_once_with(12, 44, 'osu', legacy_only=True)


if __name__ == '__main__':
    unittest.main()
