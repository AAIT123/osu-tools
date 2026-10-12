"""Offline search deliberately does not infer cross-mode converts."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from osu_tools.database import Beatmap, LOVED_STATUS
from osu_tools.search import search_beatmaps, as_record
from osu_tools.cli import main_search
from tests.fixtures import make_osudb, make_collections

A, B, C = 'a'*32, 'b'*32, 'c'*32


def beatmap(md5, artist, title, difficulty, mode, status=4, id=101, set_id=201):
    return Beatmap(md5, artist, title, difficulty, mode, status, id, set_id, 'folder')


class SearchLogicTests(unittest.TestCase):
    def setUp(self):
        self.maps = {
            A: beatmap(A, 'Kobaryo', 'Search Me', 'Hard', 0, id=101),
            B: beatmap(B, 'Kobaryo', 'Search Me', 'Oni', 1, id=102),
            C: beatmap(C, 'Other', 'Kobaryo remix', 'Expert', 3, LOVED_STATUS, id=103),
        }

    def test_artist_title_difficulty_words_and_stable_order(self):
        count, found = search_beatmaps(self.maps, 'Kobaryo search')
        self.assertEqual(count, 2)
        self.assertEqual([b.md5 for b in found], [A, B])
        self.assertEqual(search_beatmaps(self.maps, 'kobaryo ReMiX')[1][0].md5, C)
        self.assertEqual(search_beatmaps(self.maps, 'does not exist')[0], 0)

    def test_loved_native_mode_and_ids(self):
        self.assertEqual(search_beatmaps(self.maps, 'kobaryo', loved=True)[1][0].md5, C)
        self.assertEqual(search_beatmaps(self.maps, 'kobaryo', native_mode=1)[1][0].md5, B)
        self.assertEqual(search_beatmaps(self.maps, '', beatmap_id=103)[1][0].md5, C)
        self.assertEqual(search_beatmaps(self.maps, '', beatmapset_id=201)[0], 3)

    def test_convert_tag_has_native_standard_mode(self):
        # Manual 'mania converts' membership does NOT reclassify native standard.
        count, maps = search_beatmaps(self.maps, '', collection_hashes={A, B}, native_mode=0)
        self.assertEqual((count, [b.md5 for b in maps]), (1, [A]))
        self.assertEqual(as_record(maps[0])['native_mode_name'], 'std')
        self.assertEqual(search_beatmaps(self.maps, '', collection_hashes={A}, native_mode=3)[0], 0)

    def test_limit_bounded_and_deterministic_even_when_insertion_changes(self):
        maps = {
            f'{i:032x}': beatmap(f'{i:032x}', 'Artist', f'Title {i:05d}', 'Hard', 0)
            for i in reversed(range(5000))
        }
        total, first = search_beatmaps(maps, 'Title', limit=4)
        total2, second = search_beatmaps(dict(reversed(list(maps.items()))), 'Title', limit=4)
        self.assertEqual(total, 5000)
        self.assertEqual(total2, total)
        self.assertEqual([b.md5 for b in first], [b.md5 for b in second])
        self.assertEqual(len(first), 4)

    def test_invalid_filters(self):
        for args in ({'limit': 0}, {'limit': 101}, {'native_mode': 99}):
            with self.assertRaises(ValueError):
                search_beatmaps(self.maps, 'x', **args)
        with self.assertRaises(ValueError):
            search_beatmaps(self.maps, 'a ' * 17)


class SearchCLITests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        songs = self.root/'Songs'
        songs.mkdir()
        env = patch.dict(os.environ, {'OSU_SONGS': str(songs),
                                     'XDG_DATA_HOME': str(self.root/'data')})
        env.start()
        self.addCleanup(env.stop)
        make_osudb(self.root/'osu!.db', [(A, 0, 4), (B, 1, 4), (C, 3, LOVED_STATUS)])
        make_collections(self.root/'collection.db', [('mania converts', [A, 'f'*32]),
                                                   ('test', [B])])

    def call(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main_search(args), 0)
        return out.getvalue()

    def test_collection_exact_and_unknown_checksum_count_json(self):
        data = json.loads(self.call(['--collection', 'mania converts', '--json']))
        self.assertEqual(data['matching_count'], 1)
        self.assertEqual(data['collection_unresolved'], 1)
        self.assertEqual(data['beatmaps'][0]['native_mode_name'], 'std')
        self.assertEqual(json.loads(self.call(['--collection', 'MANIA CONVERTS', '--mode', 'mania', '--json']))['matching_count'], 0)

    def test_native_filters_and_query(self):
        data = json.loads(self.call(['song', '--mode', 'taiko', '--json']))
        self.assertEqual(data['matching_count'], 1)
        self.assertEqual(data['beatmaps'][0]['beatmap_id'], 101)
        data = json.loads(self.call(['--loved', '--json']))
        self.assertEqual(data['matching_count'], 1)

    def test_invalid_collection_and_unfiltered_all(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main_search([])
        with self.assertRaisesRegex(ValueError, 'No collection'):
            main_search(['--collection', 'man'])

    def test_cached_does_not_parse_again(self):
        self.call(['Song'])
        from osu_tools import cache
        with patch.object(cache, 'load_beatmaps', side_effect=AssertionError('cache not used')):
            self.call(['Song', '--limit', '1'])


if __name__ == '__main__':
    unittest.main()
