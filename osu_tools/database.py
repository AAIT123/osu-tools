"""Minimal, streaming readers for stable's map/collection/score databases.

The format is versioned. Unknown layouts cause explicit errors; we never guess
field widths and then write a corrupted collection database back.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from .binary import Reader, Writer, FormatError

LOVED_STATUS = 7
TARGET_PRACTICE_MOD = 8388608


@dataclass(frozen=True)
class Beatmap:
    md5: str
    artist: str
    title: str
    difficulty: str
    native_mode: int
    ranked_status: int
    beatmap_id: int
    beatmapset_id: int
    folder_name: str

    @property
    def label(self):
        return f'{self.artist} - {self.title} [{self.difficulty}]'


@dataclass
class Collection:
    name: str
    hashes: list[str] = field(default_factory=list)


@dataclass
class CollectionsDB:
    version: int
    collections: list[Collection]

    def find(self, name: str) -> Optional[Collection]:
        return next((c for c in self.collections if c.name == name), None)

    def ensure(self, name: str, create=False) -> Optional[Collection]:
        coll = self.find(name)
        if coll is None and create:
            coll = Collection(name)
            self.collections.append(coll)
        return coll


def _map_entry(r: Reader, version: int) -> Beatmap:
    if version < 20191106:
        r.int()  # entry length (old versions)
    artist = r.string() or ''
    r.string() # artist unicode
    title = r.string() or ''
    r.string() # title unicode
    r.string() # mapper
    diff = r.string() or ''
    r.string() # audio filename
    md5 = r.string() or ''
    r.string() # .osu file name
    status = r.byte()
    r.skip(2 * 3 + 8) # objects and last modification ticks
    r.skip(4 if version < 20140609 else 16) # AR/CS/HP/OD
    r.double() # slider velocity
    if version >= 20140609:
        for _ in range(4):
            for _ in range(r.count(limit=100_000)):
                int_marker = r.byte()
                r.int() # mod bitmask
                float_marker = r.byte()
                if int_marker != 0x08 or float_marker != (0x0c if version >= 20250107 else 0x0d):
                    raise FormatError('Unexpected star rating pair format; unsupported database revision')
                if version >= 20250107:
                    r.single()
                else:
                    r.double()
    r.skip(12) # drain, total and preview time
    for _ in range(r.count(limit=10_000_000)):
        r.skip(17) # timing point
    beatmap_id = r.int() # formerly known as difficulty id
    beatmapset_id = r.int() # formerly known as beatmap id
    r.int() # thread id
    r.skip(4 + 2 + 4) # grades, local offset, stack leniency
    mode = r.byte()
    r.string(); r.string() # source and tags
    r.skip(2) # online offset
    r.string() # title font
    r.skip(1 + 8 + 1) # unplayed, last played, osz2
    folder = r.string() or ''
    r.skip(8 + 5) # last checked, ignore flags
    if version < 20140609:
        r.short()
    r.skip(4 + 1) # modification time, mania scroll speed
    if mode not in range(4):
        raise FormatError(f'Invalid native mode {mode} for {md5}')
    return Beatmap(md5, artist, title, diff, mode, status, beatmap_id, beatmapset_id, folder)


def load_beatmaps(path: Path):
    """Return (version, player name, md5->Beatmap), reading sequentially."""
    with Path(path).open('rb', buffering=128*1024) as f:
        r = Reader(f)
        version = r.int()
        if not 20000000 <= version <= 20991231:
            raise FormatError(f'Unexpected osu!.db version {version}')
        r.int(); r.boolean(); r.long()
        player = r.string()
        out = {}
        for _ in range(r.count(limit=5_000_000)):
            bm = _map_entry(r, version)
            if bm.md5:
                out[bm.md5.lower()] = bm
        r.int() # permissions
        if not r.eof():
            raise FormatError('Extra bytes at end of osu!.db (format may have changed)')
    return version, player, out


def player_from_header(path: Path):
    with Path(path).open('rb') as f:
        r = Reader(f)
        r.int(); r.int(); r.boolean(); r.long()
        return r.string()


def load_collections(path: Path) -> CollectionsDB:
    with Path(path).open('rb') as f:
        r = Reader(f)
        version = r.int()
        if not 20000000 <= version <= 20991231:
            raise FormatError(f'Unexpected collection.db version {version}')
        entries = []
        names = set()
        for _ in range(r.count(limit=200_000)):
            name = r.string()
            if name is None or name in names:
                raise FormatError(f'Missing or duplicate collection name: {name!r}')
            names.add(name)
            hashes = [r.string() for _ in range(r.count(limit=5_000_000))]
            if any(h is None for h in hashes):
                raise FormatError(f'Null beatmap hash in collection {name}')
            entries.append(Collection(name, hashes))
        if not r.eof():
            raise FormatError('Extra bytes at end of collection.db')
        return CollectionsDB(version, entries)


def dump_collections(data: CollectionsDB) -> bytes:
    w = Writer()
    w.int(data.version)
    w.int(len(data.collections))
    for col in data.collections:
        w.string(col.name)
        w.int(len(col.hashes))
        for h in col.hashes:
            w.string(h)
    return w.bytes()


def played_hashes(path: Path) -> set[str]:
    """Exact difficulty checksums with >=1 saved score; not a complete play history."""
    result = set()
    with Path(path).open('rb', buffering=128*1024) as f:
        r = Reader(f)
        r.int()  # version
        for _ in range(r.count(limit=5_000_000)):
            md5 = r.string()
            count = r.count(limit=5_000_000)
            if md5 and count:
                result.add(md5.lower())
            for _ in range(count):
                r.byte()  # mode
                r.int()   # score version
                r.string(); r.string(); r.string()  # map, player, replay hashes
                r.skip(12 + 4 + 2 + 1) # judgements, score, combo, perfect
                mods = r.int()
                r.string() # life graph
                r.skip(8 + 4 + 8) # timestamp, -1 sentinel, online id
                if mods & TARGET_PRACTICE_MOD:
                    r.double()
        if not r.eof():
            raise FormatError('Extra bytes at end of scores.db')
    return result


def iter_saved_scores(path: Path):
    """Stream readable local score metadata, one score per object.

    No replay frames are embedded in scores.db; retain original files for
    byte-for-byte restoration. Counts are stored exactly as written.
    """
    with Path(path).open('rb', buffering=128*1024) as f:
        r = Reader(f)
        version = r.int()
        if not 20000000 <= version <= 20991231:
            raise FormatError(f'Unexpected scores.db version {version}')
        for _ in range(r.count(limit=5_000_000)):
            map_md5 = r.string() or ''
            for _ in range(r.count(limit=5_000_000)):
                mode = r.byte()
                score_version = r.int()
                replay_map_md5 = r.string()
                player = r.string()
                replay_md5 = r.string()
                hits = [r.short() for _ in range(6)]
                score = r.int()
                combo = r.short()
                perfect = r.boolean()
                mods = r.int()
                r.string()  # life graph (omitted: potentially long/noisy)
                ticks = r.long()
                local_id = r.int()
                online_id = r.long()
                target_accuracy = r.double() if mods & TARGET_PRACTICE_MOD else None
                yield {
                    'map_md5': map_md5.lower(), 'mode': mode,
                    'score_version': score_version, 'replay_map_md5': replay_map_md5,
                    'player': player, 'replay_md5': replay_md5,
                    'n300': hits[0], 'n100': hits[1], 'n50': hits[2],
                    'ngeki': hits[3], 'nkatu': hits[4], 'nmiss': hits[5],
                    'score': score, 'max_combo': combo, 'perfect': perfect,
                    'mods_bitmask': mods, 'timestamp_ticks': ticks,
                    'local_score_id': local_id, 'online_score_id': online_id,
                    'target_practice_accuracy': target_accuracy,
                }
        if not r.eof():
            raise FormatError('Extra bytes at end of scores.db')
