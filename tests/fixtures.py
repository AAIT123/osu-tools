"""Minimal synthetic legacy database fixtures; no real user data."""
from pathlib import Path
import struct
from osu_tools.binary import Writer

class W(Writer):
    def short(self, value): self.parts.append(struct.pack('<H', value))
    def long(self, value): self.parts.append(struct.pack('<q', value))
    def float(self, value): self.parts.append(struct.pack('<f', value))
    def double(self, value): self.parts.append(struct.pack('<d', value))

VERSION=20250202

def make_osudb(path: Path, maps, *, star_ratings_per_mode=1, timing_points=1,
               version=VERSION):
    w = W()
    w.int(version); w.int(0); w.byte(1); w.long(0); w.string('Test User')
    w.int(len(maps))
    for i, (md5, mode, status) in enumerate(maps):
        for s in (f'Artist {i}', f'Artist {i}', f'Song {i}', f'Song {i}', 'Creator',
                  'Expert', 'audio.mp3', md5, 'difficulty.osu'):
            w.string(s)
        w.byte(status)
        for _ in range(3): w.short(1)
        w.long(0)
        for _ in range(4): w.float(5.0)
        w.double(1.4)
        for _ in range(4):
            w.int(star_ratings_per_mode)
            for rating in range(star_ratings_per_mode):
                w.byte(0x08); w.int(rating)
                if version >= 20250107:
                    w.byte(0x0c); w.float(5.0)
                else:
                    w.byte(0x0d); w.double(5.0)
        for _ in range(3): w.int(500)
        w.int(timing_points)
        for _ in range(timing_points):
            w.double(500.0); w.double(0); w.byte(1)
        w.int(100+i); w.int(200+i); w.int(0)
        for _ in range(4): w.byte(0)
        w.short(0); w.float(0.7); w.byte(mode)
        w.string(''); w.string(''); w.short(0); w.string('')
        w.byte(0); w.long(0); w.byte(0); w.string(f'folder {i}')
        w.long(0)
        for _ in range(5): w.byte(0)
        w.int(0); w.byte(0)
    w.int(0)
    path.write_bytes(w.bytes())


def make_collections(path: Path, entries):
    w=W(); w.int(VERSION); w.int(len(entries))
    for name, hashes in entries:
        w.string(name); w.int(len(hashes))
        for h in hashes: w.string(h)
    path.write_bytes(w.bytes())


def make_scores(path: Path, entries):
    """entries = [(md5, [(mode,mods),...])]; all are saved plays."""
    w=W(); w.int(VERSION); w.int(len(entries))
    for hash_,scores in entries:
        w.string(hash_); w.int(len(scores))
        for mode, mods in scores:
            w.byte(mode); w.int(VERSION)
            for s in (hash_, 'Test User', 'replaymd5'): w.string(s)
            for _ in range(6): w.short(0)
            w.int(7777); w.short(55); w.byte(1)
            w.int(mods); w.string('')
            w.long(0); w.int(-1); w.long(0)
            if mods & 8388608: w.double(0.0)
    path.write_bytes(w.bytes())
