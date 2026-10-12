"""No real user data, network, or rosu dependency required."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from osu_tools.database import Beatmap
from osu_tools.local_pp import MapLocator, estimate, local_estimates


def score(**updates):
    result = dict(map_md5='a'*32, mode=1, mods_bitmask=16, max_combo=99,
                  n300=90, n100=10, n50=0, ngeki=0, nkatu=0, nmiss=1,
                  score=100000, timestamp_ticks=0, player='test', replay_md5='r')
    result.update(updates)
    return result


def fake_beatmap(md5, mode=0, folder='song'):
    return Beatmap(md5, 'Artist', 'Title', 'Hard', mode, 0, 123, 456, folder)


class FakeModern:
    class GameMode:
        Taiko = 1
        Catch = 2
        Mania = 3

    class Beatmap:
        def __init__(self, path):
            self.path = path
            self.conversion = None

        def is_suspicious(self):
            return False

        def convert(self, mode, mods):
            self.conversion = (mode, mods)

    class Performance:
        def __init__(self, **kw):
            self.kw = kw

        def calculate(self, bm):
            FakeModern.last_kwargs = self.kw
            FakeModern.last_map = bm
            return SimpleNamespace(pp=123.456, difficulty=SimpleNamespace(stars=5.234))


class FakeOld:
    Beatmap = FakeModern.Beatmap

    class Calculator:
        def __init__(self, **kwargs):
            FakeOld.last_kwargs = kwargs

        def performance(self, bm):
            return SimpleNamespace(pp=87.653)


class LocalPPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.songs = Path(self.tmp.name)
        (self.songs / 'song').mkdir()
        (self.songs / 'song' / 'one.osu').write_bytes(b'osu file content')
        self.md5 = hashlib.md5(b'osu file content').hexdigest()
        self.bm = fake_beatmap(self.md5)
        self.row = score(map_md5=self.md5)

    def test_bounded_exact_checksum_lookup_and_folder_cache(self):
        locator = MapLocator(self.songs)
        self.assertEqual(locator.find(self.bm), self.songs/'song'/'one.osu')
        self.assertEqual(locator.find(self.bm), self.songs/'song'/'one.osu')
        self.assertIsNone(locator.find(fake_beatmap('f'*32)))

    def test_reject_path_escape_and_symlink(self):
        locator = MapLocator(self.songs)
        self.assertIsNone(locator.find(fake_beatmap(self.md5, folder='../foo')))
        self.assertIsNone(locator.find(fake_beatmap(self.md5, folder='/etc')))
        (self.songs/'link').symlink_to(self.songs.parent)
        self.assertIsNone(locator.find(fake_beatmap(self.md5, folder='link')))

    def test_correct_legacy_counts_and_mods_modern_engine(self):
        pp, stars = estimate(self.row, self.songs/'song'/'one.osu', 0, FakeModern)
        self.assertEqual((pp, stars), (123.46, 5.23))
        self.assertEqual(FakeModern.last_map.conversion, (1, 16))
        self.assertFalse(FakeModern.last_kwargs['lazer'])
        self.assertEqual(FakeModern.last_kwargs['misses'], 1)
        self.assertEqual(FakeModern.last_kwargs['n300'], 90)
        self.assertEqual(FakeModern.last_kwargs['n100'], 10)
        self.assertEqual(FakeModern.last_kwargs['mods'], 16)

    def test_native_no_conversion_and_old_engine(self):
        row = score(mode=3, mods_bitmask=0, n300=90, ngeki=15, nkatu=20)
        pp, stars = estimate(row, self.songs/'song'/'one.osu', 3, FakeOld)
        self.assertEqual((pp, stars), (87.65, None))
        self.assertEqual(FakeOld.last_kwargs['mode'], 3)
        self.assertEqual(FakeOld.last_kwargs['n_katu'], 20)
        pp, _ = estimate(row, self.songs/'song'/'one.osu', 3, FakeModern)
        self.assertIsNone(FakeModern.last_map.conversion)

    def test_nonstandard_converts_never_estimated(self):
        with self.assertRaisesRegex(ValueError, 'Only native standard'):
            estimate(self.row, self.songs/'song'/'one.osu', 3, FakeModern)

    def test_skip_unsuitable_mods_and_zero_hits(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported assist'):
            estimate(score(mods_bitmask=128), self.songs/'song'/'one.osu', 1, FakeModern)
        with self.assertRaisesRegex(ValueError, 'Unsupported assist'):
            estimate(score(mods_bitmask=8192), self.songs/'song'/'one.osu', 1, FakeModern)
        # SpunOut alone is not a reason to skip an estimate.
        self.assertGreater(estimate(score(mods_bitmask=4096),
                                    self.songs/'song'/'one.osu', 1, FakeModern)[0], 0)
        with self.assertRaisesRegex(ValueError, 'No hit counts'):
            estimate(score(n300=0, n100=0, nmiss=0), self.songs/'song'/'one.osu', 1, FakeModern)

    def test_outcomes_skip_unknown_or_unavailable_and_do_not_write(self):
        before = (self.songs/'song'/'one.osu').read_bytes()
        outcomes = local_estimates([self.row, score(map_md5='a'*32)],
                                   {self.md5: self.bm}, songs=self.songs, rosu=FakeModern)
        self.assertEqual(outcomes[0]['estimated_pp'], 123.46)
        self.assertIsNone(outcomes[0]['pp_skipped'])
        self.assertIsNone(outcomes[1]['estimated_pp'])
        self.assertIn('not installed', outcomes[1]['pp_skipped'])
        self.assertEqual((self.songs/'song'/'one.osu').read_bytes(), before)

    def test_mismatched_file_not_calculated(self):
        mismatch = fake_beatmap('a'*32)
        result = local_estimates([score()], {'a'*32: mismatch}, songs=self.songs, rosu=FakeModern)
        self.assertIsNone(result[0]['estimated_pp'])
        self.assertIn('not found', result[0]['pp_skipped'])

    def test_batch_size_limited(self):
        with self.assertRaisesRegex(ValueError, '20'):
            local_estimates([self.row]*21, {self.md5: self.bm}, songs=self.songs, rosu=FakeModern)


if __name__ == '__main__':
    unittest.main()

class PPCommandTests(unittest.TestCase):
    def setUp(self):
        import os
        from tests.fixtures import make_osudb, make_scores
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Songs' / 'folder 0').mkdir(parents=True)
        payload = b'example .osu score fixture'
        self.hash = hashlib.md5(payload).hexdigest()
        (self.root / 'Songs' / 'folder 0' / 'difficulty.osu').write_bytes(payload)
        make_osudb(self.root/'osu!.db', [(self.hash, 0, 4)])
        make_scores(self.root/'scores.db', [(self.hash, [(1, 0)])])
        # fixtures intentionally have zero hit counts; pp calculation must
        # skip them instead of guessing a score.
        self.env = patch.dict(os.environ, {'OSU_SONGS': str(self.root/'Songs'),
                                      'XDG_DATA_HOME': str(self.root/'data')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_pp_command_json_and_missing_hitcounts(self):
        import contextlib
        import io
        import json
        from osu_tools.cli import main_scores
        with patch('osu_tools.local_pp._rosu_engine', return_value=FakeModern):
            with contextlib.redirect_stdout(io.StringIO()) as sink:
                self.assertEqual(main_scores(['pp', '--mode', 'taiko', '--json']), 0)
        result = json.loads(sink.getvalue())
        self.assertEqual(result['matching_count'], 1)
        self.assertEqual(len(result['scores']), 1)
        self.assertIsNone(result['scores'][0]['estimated_pp'])
        self.assertIn('No hit counts', result['scores'][0]['pp_skipped'])
        self.assertEqual(result['scores'][0]['mode_name'], 'taiko')

    def test_pp_limit_restriction(self):
        from osu_tools.cli import main_scores
        with self.assertRaises(SystemExit) as caught:
            main_scores(['pp', '--limit', '21'])
        self.assertEqual(caught.exception.code, 2)
