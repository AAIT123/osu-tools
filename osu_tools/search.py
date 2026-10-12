"""Read-only, bounded-memory search of the existing osu!.db metadata cache.

Collection membership and native mode are independent: a native standard map
may have a manual ``mania converts`` tag, but is never relabeled native mania.
"""
import heapq

from .database import LOVED_STATUS

MODE_NAMES = {0: 'std', 1: 'taiko', 2: 'catch', 3: 'mania'}
MODE_IDS = {v: k for k, v in MODE_NAMES.items()}


def _rank(map_, query, words):
    if not words:
        return 0
    artist = map_.artist.casefold()
    title = map_.title.casefold()
    difficulty = map_.difficulty.casefold()
    label = f'{artist} - {title} [{difficulty}]'
    if not all(word in label for word in words):
        return None
    if title == query or label == query:
        return 0
    if title.startswith(query):
        return 1
    if artist == query:
        return 2
    if artist.startswith(query):
        return 3
    if difficulty == query:
        return 4
    if query in title:
        return 5
    if query in artist:
        return 6
    if query in difficulty:
        return 7
    return 8


def search_beatmaps(maps, query='', *, native_mode=None, loved=False,
                    collection_hashes=None, beatmap_id=None, beatmapset_id=None,
                    limit=20):
    """Return (number_matched, <=limit sorted Beatmaps) without retaining all matches.

    A collection filter is an exact MD5 membership check; no policy inference,
    no implicit convert rules, no writes, and no dependency on online services.
    """
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    if native_mode is not None and native_mode not in MODE_NAMES:
        raise ValueError('Unknown native mode')
    if len(query) > 512:
        raise ValueError('Search query is too long (512 characters maximum)')
    query = ' '.join(query.casefold().split())
    words = query.split()
    if len(words) > 16:
        raise ValueError('Too many search terms (16 maximum)')
    total = 0

    def candidates():
        nonlocal total
        for map_ in maps.values():
            if native_mode is not None and map_.native_mode != native_mode:
                continue
            if loved and map_.ranked_status != LOVED_STATUS:
                continue
            if collection_hashes is not None and map_.md5.lower() not in collection_hashes:
                continue
            if beatmap_id is not None and map_.beatmap_id != beatmap_id:
                continue
            if beatmapset_id is not None and map_.beatmapset_id != beatmapset_id:
                continue
            rank = _rank(map_, query, words)
            if rank is None:
                continue
            total += 1
            key = (rank, map_.artist.casefold(), map_.title.casefold(),
                   map_.difficulty.casefold(), map_.md5.lower())
            yield key, map_

    found = heapq.nsmallest(limit, candidates(), key=lambda item: item[0])
    return total, [map_ for _, map_ in found]


def as_record(map_):
    return dict(md5=map_.md5, artist=map_.artist, title=map_.title,
                difficulty=map_.difficulty, label=map_.label,
                native_mode=map_.native_mode,
                native_mode_name=MODE_NAMES.get(map_.native_mode, 'unknown'),
                loved=map_.ranked_status == LOVED_STATUS,
                ranked_status=map_.ranked_status,
                beatmap_id=map_.beatmap_id,
                beatmapset_id=map_.beatmapset_id,
                folder_name=map_.folder_name)
