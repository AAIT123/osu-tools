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


def _scan_verified_index(path, consume):
    """Stream every cached score and verify digest, count and source identity.

    Collector state is discarded on retry, so partial corrupted data can never
    leak into a result returned after rebuilding the index.
    """
    stamp = list(cache.source_fingerprint(path))
    folder = cache.index_dir()
    entry = cache._manifest(folder).get('scores', {})
    if entry.get('fingerprint') != stamp:
        raise ValueError('Score index is stale')
    scorefile = folder / entry['file']
    if scorefile.is_symlink() or not scorefile.is_file():
        raise ValueError('Score index is missing or a symlink')
    seen = 0
    for row in cache._read_jsonl(scorefile, entry['sha256']):
        consume(row)
        seen += 1
    if seen != entry['score_count']:
        raise ValueError('Index record count mismatch')
    if list(cache.source_fingerprint(path)) != stamp:
        raise FormatError('scores.db changed during local score lookup; retry when osu! is idle')


def _collect(path, factory, inform=None):
    """Shared validated JSONL scan for browsing, bests and statistics."""
    path = Path(path)
    cache.cached_played_hashes(path, inform=inform)
    for attempt in range(2):
        consume, finish = factory()  # restart after a damaged index
        try:
            _scan_verified_index(path, consume)
            return finish()
        except (OSError, KeyError, TypeError, ValueError, UnicodeError) as exc:
            if attempt:
                raise FormatError(f'Unable to validate readable score index: {exc}') from exc
            if inform:
                inform('Score index invalid; rebuilding from scores.db...')
            cache.cached_played_hashes(path, refresh=True, inform=inform)
    raise AssertionError('unreachable')


def _matches(row, mode, player, eligible):
    return ((mode is None or row['mode'] == mode)
            and (not player or row['player'].casefold() == player.casefold())
            and (eligible is None or row['map_md5'] in eligible))


def find_scores(path: Path, *, limit=20, order='recent', mode=None,
                player=None, eligible=None, inform=None):
    """Top-N recent or raw-score results from an integrity-checked index."""
    def factory():
        heap = []
        matched = 0
        seen = 0

        def consume(row):
            nonlocal matched, seen
            seen += 1
            if not _matches(row, mode, player, eligible):
                return
            matched += 1
            date = row['timestamp_ticks']
            key = (date, row['score']) if order == 'recent' else (row['score'], date)
            item = (key, seen, row)
            if len(heap) < limit:
                heapq.heappush(heap, item)
            elif item[:2] > heap[0][:2]:
                heapq.heapreplace(heap, item)

        def finish():
            return matched, [item[2] for item in sorted(heap, reverse=True)]
        return consume, finish
    return _collect(path, factory, inform=inform)


def best_saved_per_difficulty(path: Path, *, limit=20, mode=None,
                              player=None, eligible=None, inform=None):
    """Highest *raw score* per (player, checksum, played mode, mod mask).

    Not an official PB or pp calculation: only saved local records are used.
    A modified difficulty checksum is a different map, by design.
    """
    def factory():
        best = {}
        matched = 0

        def consume(row):
            nonlocal matched
            if not _matches(row, mode, player, eligible):
                return
            matched += 1
            key = (row['player'].casefold(), row['map_md5'], row['mode'], row['mods_bitmask'])
            old = best.get(key)
            rank = (row['score'], row['timestamp_ticks'])
            if old is None or rank > (old['score'], old['timestamp_ticks']):
                best[key] = row

        def finish():
            top = heapq.nlargest(limit, best.values(),
                                 key=lambda r: (r['score'], r['timestamp_ticks']))
            return matched, len(best), top
        return consume, finish
    return _collect(path, factory, inform=inform)


def summarize_saved_scores(path: Path, *, mode=None, player=None, inform=None):
    """Per-mode counts, unique maps, and mean per-play accuracy of saved scores."""
    def factory():
        data = {}
        all_maps = set()
        total = 0

        def consume(row):
            nonlocal total
            if not _matches(row, mode, player, None):
                return
            total += 1
            m = row['mode']
            if m not in data:
                data[m] = dict(plays=0, maps=set(), by_map={}, accuracy_sum=0.0,
                               accuracy_samples=0, latest_ticks=0)
            agg = data[m]
            agg['plays'] += 1
            h = row['map_md5']
            agg['maps'].add(h)
            all_maps.add(h)
            agg['by_map'][h] = agg['by_map'].get(h, 0) + 1
            agg['latest_ticks'] = max(agg['latest_ticks'], row['timestamp_ticks'])
            acc = accuracy(row)
            if acc is not None:
                agg['accuracy_sum'] += acc
                agg['accuracy_samples'] += 1

        def finish():
            modes = []
            for m in sorted(data):
                agg = data[m]
                top_map, top_count = sorted(agg['by_map'].items(),
                                            key=lambda item: (-item[1], item[0]))[0]
                samples = agg['accuracy_samples']
                modes.append(dict(mode=m, mode_name=(MODE_NAMES[m] if 0 <= m < 4 else f'unknown-{m}'),
                                  plays=agg['plays'], unique_difficulties=len(agg['maps']),
                                  mean_accuracy_percent=(round(agg['accuracy_sum'] / samples, 2)
                                                         if samples else None),
                                  accuracy_samples=samples,
                                  latest_utc=utc_time(agg['latest_ticks']),
                                  most_played_map_md5=top_map, most_played_count=top_count))
            return dict(saved_scores=total, unique_difficulties=len(all_maps), modes=modes)
        return consume, finish
    return _collect(path, factory, inform=inform)


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
