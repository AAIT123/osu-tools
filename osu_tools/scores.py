"""Offline saved-score lookup over the human-readable scores JSONL cache.

No replay parsing, API calls, database writes, or resident service.
Only saved records from scores.db are searchable; unsaved plays may be absent.
"""
from datetime import datetime, timezone
import heapq
import hashlib
from pathlib import Path
import re
from . import cache, paths
from .binary import FormatError

MODE_IDS = {'std': 0, 'taiko': 1, 'catch': 2, 'mania': 3}
MODE_NAMES = ('std', 'taiko', 'catch', 'mania')
_MD5 = re.compile(r'^[0-9a-fA-F]{32}$')

# osu!stable legacy mod bitmask. NC contains DT, PF contains SD.
MOD_BITS = ((1,'NF'), (2,'EZ'), (4,'TD'), (8,'HD'), (16,'HR'),
            (32,'SD'), (64,'DT'), (128,'RX'), (256,'HT'), (512,'NC'),
            (1024,'FL'), (2048,'AT'), (4096,'SO'), (8192,'AP'),
            (16384,'PF'), (32768,'4K'), (65536,'5K'), (131072,'6K'),
            (262144,'7K'), (524288,'8K'), (1048576,'FI'),
            (2097152,'RD'), (4194304,'CN'), (8388608,'TP'),
            (16777216,'9K'), (33554432,'CO'), (67108864,'1K'),
            (134217728,'3K'), (268435456,'2K'), (536870912,'V2'))


def mod_string(bits):
    if not bits:
        return 'NM'
    # Subsume constituent bits of NC and PF rather than printing NC+DT.
    ignore = (64 if bits & 512 else 0) | (32 if bits & 16384 else 0)
    parts = [name for mask,name in MOD_BITS if bits & mask and not mask & ignore]
    covered = 0
    for mask, _ in MOD_BITS:
        covered |= mask
    if bits & ~covered:
        parts.append(hex(bits & ~covered))
    return ''.join(parts) or 'NM'


def accuracy(row):
    n300 = row['n300']; n100 = row['n100']; n50 = row['n50']
    geki = row['ngeki']; katu = row['nkatu']; miss = row['nmiss']
    mode = row['mode']
    if mode == 0:
        total = n300 + n100 + n50 + miss
        numer = 300*n300 + 100*n100 + 50*n50
        denom = 300*total
    elif mode == 1:
        denom = 2*(n300+n100+miss)
        numer = 2*n300 + n100
    elif mode == 2:
        denom = n300+n100+n50+katu+miss
        numer = n300+n100+n50
    elif mode == 3:
        denom = 300*(geki+n300+katu+n100+n50+miss)
        numer = 300*(geki+n300) + 200*katu + 100*n100 + 50*n50
    else:
        return None
    return round(100 * numer/denom, 2) if denom else None


def utc_time(ticks):
    try:
        ts = ticks / 10_000_000 - 62_135_596_800
        if ts < 0: return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def map_checksum(value):
    """Accept a .osu path, a raw checksum, or the special current-map tag."""
    if value == ':current':
        value = str(paths.current_map())
    if _MD5.fullmatch(value):
        return value.lower()
    path = Path(value).expanduser()
    if not path.is_file() or path.suffix.lower() != '.osu':
        raise ValueError('Map must be an existing .osu file, 32-character MD5, or :current')
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'md5').hexdigest()


def _read_matching(path, limit, order, mode, player, eligible):
    """Keep only top N; validate the entire JSONL digest before returning."""
    stamp = list(cache.source_fingerprint(path))
    folder = cache.index_dir()
    manifest = cache._manifest(folder)
    entry = manifest.get('scores', {})
    if entry.get('fingerprint') != stamp:
        raise ValueError('Score index is stale')
    scorefile = folder / entry['file']
    if scorefile.is_symlink() or not scorefile.is_file():
        raise ValueError('Score index is missing or a symlink')
    heap = []
    matched = 0
    seen = 0
    for row in cache._read_jsonl(scorefile, entry['sha256']):
        seen += 1
        if mode is not None and row['mode'] != mode:
            continue
        if player and row['player'].casefold() != player.casefold():
            continue
        if eligible is not None and row['map_md5'] not in eligible:
            continue
        matched += 1
        date = row['timestamp_ticks']
        key = (date, row['score']) if order == 'recent' else (row['score'], date)
        item = (key, seen, row)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)
    if seen != entry['score_count']:
        raise ValueError('Index record count mismatch')
    if list(cache.source_fingerprint(path)) != stamp:
        raise FormatError('scores.db changed during local score lookup; retry when osu! is idle')
    return matched, [item[2] for item in sorted(heap, reverse=True)]


def find_scores(path: Path, *, limit=20, order='recent', mode=None,
                player=None, eligible=None, inform=None):
    """Ensure a fresh score index, then select from its verified JSONL.

    Corrupted readable data is rebuilt from scores.db once. The source file
    is never written. A damaged original scores.db remains an explicit error.
    """
    path = Path(path)
    cache.cached_played_hashes(path, inform=inform)
    for attempt in range(2):
        try:
            return _read_matching(path, limit, order, mode, player, eligible)
        except (OSError, KeyError, TypeError, ValueError, UnicodeError) as exc:
            if attempt:
                raise FormatError(f'Unable to validate readable score index: {exc}') from exc
            if inform: inform('Score index invalid; rebuilding from scores.db...')
            cache.cached_played_hashes(path, refresh=True, inform=inform)
    raise AssertionError('unreachable')


def match_maps(query, maps):
    search = query.casefold()
    return {md5 for md5, bm in maps.items()
            if search in bm.artist.casefold() or search in bm.title.casefold()
            or search in bm.difficulty.casefold()}


def enrich(row, maps):
    result = dict(row)
    bm = maps.get(row['map_md5'])
    result['map_label'] = bm.label if bm else f'Unknown / uninstalled map ({row["map_md5"]})'
    result['accuracy_percent'] = accuracy(row)
    result['mods'] = mod_string(row['mods_bitmask'])
    result['date_utc'] = utc_time(row['timestamp_ticks'])
    result['mode_name'] = (MODE_NAMES[row['mode']] if 0 <= row['mode'] < len(MODE_NAMES)
                           else f'unknown-{row["mode"]}')
    return result
