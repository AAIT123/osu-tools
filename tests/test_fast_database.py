"""Bulk-read parsing must retain stable's strict version/format checks."""
from pathlib import Path
import struct
import tempfile
import unittest

from osu_tools.binary import FormatError
from osu_tools.database import load_beatmaps
from tests.fixtures import make_osudb


class BulkDatabaseReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'osu!.db'
        self.md5 = 'b' * 32

    def test_many_star_pairs_and_timing_points(self):
        make_osudb(self.db, [(self.md5, 0, 7)],
                   star_ratings_per_mode=75, timing_points=120)
        version, player, maps = load_beatmaps(self.db)
        self.assertEqual(version, 20250202)
        self.assertEqual(player, 'Test User')
        self.assertEqual(maps[self.md5].native_mode, 0)
        self.assertEqual(maps[self.md5].ranked_status, 7)

    def test_legacy_double_star_values(self):
        make_osudb(self.db, [(self.md5, 3, 4)],
                   version=20241231, star_ratings_per_mode=17,
                   timing_points=3)
        self.assertEqual(load_beatmaps(self.db)[2][self.md5].native_mode, 3)

    def test_corrupted_nonfirst_star_marker_is_rejected(self):
        make_osudb(self.db, [(self.md5, 1, 4)],
                   star_ratings_per_mode=8)
        raw = self.db.read_bytes()
        pair = bytes([0x08]) + struct.pack('<i', 1) + bytes([0x0c]) + struct.pack('<f', 5.0)
        self.assertEqual(raw.count(pair), 4)
        broken = raw.replace(pair, bytes([0x08]) + struct.pack('<i', 1)
                             + bytes([0x0d]) + struct.pack('<f', 5.0), 1)
        self.db.write_bytes(broken)
        with self.assertRaisesRegex(FormatError, 'star rating pair'):
            load_beatmaps(self.db)

    def test_truncated_star_rating_array_is_rejected(self):
        make_osudb(self.db, [(self.md5, 1, 4)],
                   star_ratings_per_mode=16, timing_points=0)
        raw = self.db.read_bytes()
        # Remove the bytes after the first star section: the declared four
        # sections cannot all be read without running past EOF.
        self.db.write_bytes(raw[:raw.find(b'\x08\x00\x00\x00\x00\x0c') + 55])
        with self.assertRaises(FormatError):
            load_beatmaps(self.db)

    def test_truncated_timing_point_array_is_rejected(self):
        make_osudb(self.db, [(self.md5, 1, 4)],
                   star_ratings_per_mode=0, timing_points=20)
        # Deliberately leave part of the final entry incomplete.
        self.db.write_bytes(self.db.read_bytes()[:-65])
        with self.assertRaises(FormatError):
            load_beatmaps(self.db)
