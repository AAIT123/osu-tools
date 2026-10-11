"""CLI frontends: import submodules only when the corresponding command runs."""
import argparse
import hashlib
from pathlib import Path
import sys
import time
from . import paths
from .binary import FormatError
from .database import load_beatmaps, load_collections, dump_collections, played_hashes, player_from_header
from .collections import sync as sync_collection_rules
from .safety import SafetyError, sha256, write_verified
from .cache import cached_beatmaps, cached_played_hashes, source_fingerprint
from .policy import load_policy, init_policy, policy_path


COMMANDS = ['sync', 'sync-all', 'sync-modes', 'sync-variants', 'sync-loved', 'sync-played']


def _label(h, by_md5):
    bm = by_md5.get(h.lower())
    return bm.label if bm else h


def _report(diff, by_md5):
    for name in diff.created:
        print(f"Creating collection: {name}")
    for name, hashes in diff.additions.items():
        if not hashes:
            continue
        print(f'{name}: +{len(hashes)}')
        for h in hashes[:5]:
            print(f'  + {_label(h, by_md5)}')
        if len(hashes) > 5:
            print(f'    ... {len(hashes)-5} more')
        origins = sorted(diff.sources.get(name, {}).items(), key=lambda item: (-item[1], item[0]))
        for origin, count in origins[:5]:
            print(f'    from {origin}: {count}')
        if len(origins) > 5:
            print(f'    ... {len(origins)-5} additional source(s)')
    for name, hashes in diff.removals.items():
        print(f'{name}: -{len(hashes)} verifiably non-native entries')
        for h in hashes[:5]:
            print(f'  - {_label(h, by_md5)}')
    if not diff.has_changes():
        print('No changes needed.')
    print(f'Change total: +{diff.counts["hashes_added"]} / -{diff.counts["hashes_removed"]} '
          f'in {diff.counts["collections_changed"]} collection(s)')
    for msg in diff.warnings[:30]:
        print('NOTICE:', msg, file=sys.stderr)
    if len(diff.warnings) > 30:
        print(f'NOTICE: ... and {len(diff.warnings)-30} more messages', file=sys.stderr)
    if diff.counts.get('played_unknown'):
        print(f'NOTICE: {diff.counts["played_unknown"]} scored checksums not installed locally', file=sys.stderr)


def main_collections(argv=None):
    parser = argparse.ArgumentParser(description='Audit and safely sync a personal osu!stable collection layout')
    parser.add_argument('command', nargs='?', default='summary',
                        choices=['summary', 'show', 'policy-init', 'policy-show', *COMMANDS])
    parser.add_argument('name', nargs='?', help='Collection to show')
    parser.add_argument('--policy', help='JSON rules file; default ~/.config/osu-tools/collections.json')
    parser.add_argument('--apply', action='store_true', help='Write changes after verified backup')
    parser.add_argument('--force', action='store_true', help='Override osu! process detection (unsafe)')
    parser.add_argument('--create-missing', action='store_true', help='Create missing destination collections')
    parser.add_argument('--from-root', action='store_true',
                        help='Also classify maps in all into native mode groups (large changes possible)')
    parser.add_argument('--max-additions', type=int, default=1000,
                        help='Maximum new memberships allowed per apply, default 1000')
    parser.add_argument('--max-removals', type=int, default=100,
                        help='Maximum native-aggregate removals allowed per apply, default 100')
    parser.add_argument('--allow-large', action='store_true',
                        help='Explicitly approve an apply exceeding --max-additions after reviewing the preview')
    parser.add_argument('--prune-mismatches', action='store_true', help='Remove known wrong-native hashes from native aggregates (preview first)')
    parser.add_argument('--refresh-cache', action='store_true', help='Reparse osu!.db and scores.db and refresh the disk cache')
    parser.add_argument('--no-cache', action='store_true', help='Read original osu! databases directly (for troubleshooting)')
    parser.add_argument('--timings', action='store_true', help='Show database and sync durations')
    args = parser.parse_args(argv)
    if args.max_additions < 0 or args.max_removals < 0:
        parser.error('--max-additions and --max-removals must be nonnegative')
    if args.command == 'policy-init':
        print(f'Created conservative policy: {init_policy(args.policy)}')
        print('Edit variant_sources to opt selected variant collections into upward propagation.')
        return 0
    if args.command == 'policy-show':
        import json
        policy = load_policy(args.policy)
        print(f'Policy: {args.policy or policy_path()}')
        print(json.dumps(policy.to_dict(), indent=2, ensure_ascii=False))
        return 0
    policy = load_policy(args.policy)
    root = paths.osu_root()
    if args.apply and args.command in COMMANDS:
        from .safety import game_is_running
        if not args.force and game_is_running():
            raise SafetyError('osu! appears to be running; close it before using --apply')
    t0 = time.perf_counter()
    map_path = root / 'osu!.db'
    map_source = source_fingerprint(map_path)
    _, _, maps = cached_beatmaps(map_path, refresh=args.refresh_cache,
                                enabled=not args.no_cache,
                                inform=lambda text: print(text, file=sys.stderr))
    t_maps = time.perf_counter()
    colpath = root / 'collection.db'
    database = load_collections(colpath)  # always live; never cache mutable target
    t_collections = time.perf_counter()

    if args.command == 'summary':
        missing = 0
        print(f'{len(maps)} installed difficulties, {len(database.collections)} collection(s)')
        for c in database.collections:
            dead = sum(h.lower() not in maps for h in c.hashes)
            missing += dead
            print(f'  {c.name:<32} {len(c.hashes):>6} entries   {dead} unresolved')
        print(f'Total unresolved collection entries: {missing} (some may be obsolete hashes)')
        return 0
    if args.command == 'show':
        if not args.name:
            parser.error('show requires a collection name')
        found = [c for c in database.collections if args.name.casefold() in c.name.casefold()]
        if not found:
            print(f'No matching collection: {args.name}', file=sys.stderr)
            return 1
        for c in found:
            print(f'{c.name} ({len(c.hashes)} entries)')
            for h in c.hashes:
                print(' ', _label(h, maps))
        return 0

    operations = (args.command.removeprefix('sync-'),) if args.command != 'sync' else ('sync',)
    # Any writing command validates the database bytes before its first mutation.
    original_hash = sha256(colpath)
    t_hash = time.perf_counter()
    played = None
    score_source = None
    if args.command in {'sync', 'sync-played'} and policy.sync_played:
        scores = root / 'scores.db'
        if scores.is_file():
            score_source = source_fingerprint(scores)
            played = cached_played_hashes(scores, refresh=args.refresh_cache,
                                          enabled=not args.no_cache,
                                          inform=lambda text: print(text, file=sys.stderr))
        elif args.command == 'sync-played':
            raise FileNotFoundError(f'No scores.db found at {scores}')
    t_scores = time.perf_counter()
    print(f'Policy: {args.policy or policy_path()} ({len(policy.variant_sources)} explicit variant rule(s)); other variants stay untouched')
    changes = sync_collection_rules(database, maps, operations=operations,
                                    played=played, create_missing=args.create_missing,
                                    prune_mismatches=args.prune_mismatches,
                                    from_root=args.from_root, policy=policy)
    _report(changes, maps)
    if args.timings:
        t_end = time.perf_counter()
        print(f'Timings: beatmaps {t_maps-t0:.3f}s, collections {t_collections-t_maps:.3f}s, '
              f'collection hash {t_hash-t_collections:.3f}s, scores {t_scores-t_hash:.3f}s, '
              f'sync/report {t_end-t_scores:.3f}s, '
              f'total {t_end-t0:.3f}s')
    too_large = (changes.counts['hashes_added'] > args.max_additions or
                 changes.counts['hashes_removed'] > args.max_removals)
    if too_large:
        print('BULK-CHANGE WARNING: '
              f"{changes.counts['hashes_added']} additions (limit {args.max_additions}), "
              f"{changes.counts['hashes_removed']} removals (limit {args.max_removals}). "
              'Check the source breakdown above.', file=sys.stderr)
        if args.apply and not args.allow_large:
            raise SafetyError('Refusing a bulk apply. Review the dry run, then pass '
                              '--allow-large only if you really intend these changes.')
    if not changes.has_changes():
        return 0
    if not args.apply:
        print('Dry run only. Re-run with --apply after closing osu!.')
        return 0
    # Source databases might be rewritten by osu! between cache lookup
    # and apply. Never apply a plan based on stale cached metadata/scores.
    if source_fingerprint(map_path) != map_source:
        raise SafetyError('osu!.db changed during sync; redo the preview')
    if score_source is not None and source_fingerprint(scores) != score_source:
        raise SafetyError('scores.db changed during sync; redo the preview')
    payload = dump_collections(database)
    # Verify the proposed bytes before touching original.
    _verify_payload(payload, database)
    backup = write_verified(colpath, payload, original_hash, force=args.force)
    check = load_collections(colpath)
    if dump_collections(check) != payload:
        raise SafetyError(f'Post-write validation failed! Restore from {backup}')
    print(f'Applied. Verified backup: {backup}')
    return 0



def main_library(argv=None):
    parser = argparse.ArgumentParser(description='Human-readable library and score snapshots')
    parser.add_argument('command', nargs='?', choices=['snapshot','list','status'], default='status')
    parser.add_argument('--with-replays', action='store_true',
                        help='Also copy Data/r .osr files (potentially large)')
    parser.add_argument('--index-only', action='store_true',
                        help='Readable JSON only; NOT sufficient for exact database restoration')
    args = parser.parse_args(argv)
    from . import library
    from .cache import index_dir
    if args.command == 'snapshot':
        path = library.make_snapshot(with_replays=args.with_replays,
                                     index_only=args.index_only,
                                     progress=lambda message: print(message, flush=True))
        print(f'Snapshot created: {path}')
        print('JSON exports are readable; originals/*.db are the lossless copies'
              if not args.index_only else 'Index-only: not a restorable binary backup')
    elif args.command == 'list':
        paths_list = library.list_snapshots()
        print(f'{len(paths_list)} archived snapshot(s)')
        for path in paths_list:
            print(' ', path)
    else:
        print(f'Active readable index: {index_dir()}')
        print(f'Archive directory: {library.snapshot_dir()}')
        print('Use: osu library snapshot [--with-replays], osu library list')
    return 0


def _verify_payload(payload, expected):
    from io import BytesIO
    from .binary import Reader
    r = Reader(BytesIO(payload))
    if r.int() != expected.version or r.count() != len(expected.collections):
        raise FormatError('Generated collection payload header mismatch')
    for c in expected.collections:
        if r.string() != c.name or r.count() != len(c.hashes):
            raise FormatError('Generated collection payload mismatch')
        for h in c.hashes:
            if r.string() != h:
                raise FormatError('Generated collection payload checksum mismatch')
    if not r.eof():
        raise FormatError('Generated collection payload has extra bytes')


def _local_player():
    return player_from_header(paths.osu_root() / 'osu!.db')


def main_profile(argv=None):
    parser = argparse.ArgumentParser(description='Public osu! user profile without opening a browser')
    parser.add_argument('username', nargs='?', help='Username or ID; defaults to osu!.db username')
    parser.add_argument('--mode', default='std', choices=['std', 'taiko', 'catch', 'mania'])
    args = parser.parse_args(argv)
    from .api import Client
    mode = {'std': 'osu', 'taiko': 'taiko', 'catch': 'fruits', 'mania': 'mania'}[args.mode]
    name = args.username or _local_player()
    if not name:
        parser.error('Specify a username (osu!.db has no local username)')
    result = Client().user(name, mode)
    if not result:
        print(f'No profile found for {name}', file=sys.stderr)
        return 1
    stats = result.get('statistics') or {}
    print(f'{result.get("username", name)} | {mode} | {result.get("country_code", "?")}')
    print(f'pp: {(stats.get("pp") or 0):,.2f} | global rank: {stats.get("global_rank") or "unranked"} | '
          f'country rank: {stats.get("country_rank") or "unranked"}')
    print(f'accuracy: {(stats.get("hit_accuracy") or 0):.2f}% | plays: {stats.get("play_count", 0):,} '
          f'| total hits: {stats.get("total_hits", 0):,}')
    print(f'https://osu.ppy.sh/users/{result.get("id")}/{mode}')
    return 0


def _mods(m):
    if not m:
        return 'NM'
    return ''.join(x.get('acronym','?') if isinstance(x,dict) else str(x) for x in m)


def _score(s):
    user = s.get('user') or {}
    pp = s.get('pp')
    pp_text = f'{pp:.1f}pp' if isinstance(pp, (int,float)) else f'score {s.get("score",0):,}'
    return (f'{user.get("username", "?"):<18} {pp_text:<17} '
            f'{(s.get("accuracy") or 0)*100:6.2f}%  {s.get("max_combo",0):>5}x  {_mods(s.get("mods"))}')


def main_compare(argv=None):
    parser = argparse.ArgumentParser(description='Online leaderboard of your currently selected map')
    parser.add_argument('map', nargs='?', help='.osu map path; defaults to last tracked one')
    parser.add_argument('--mode', choices=['std', 'taiko', 'catch', 'mania'])
    parser.add_argument('--top', type=int, default=10)
    parser.add_argument('--user', help='Profile to compare; default local player')
    args = parser.parse_args(argv)
    if not 1 <= args.top <= 50:
        parser.error('--top must be between 1 and 50')
    mapfile = Path(args.map) if args.map else paths.current_map()
    with mapfile.open('rb') as f:
        checksum = hashlib.file_digest(f, 'md5').hexdigest()  # required by osu! map lookup
    from .api import Client
    client = Client()
    beatmap = client.beatmap_for_checksum(checksum)
    if not beatmap:
        print('Map checksum not found online (map may be modified/outdated).', file=sys.stderr)
        return 1
    mode = ({'std':'osu', 'taiko':'taiko','catch':'fruits','mania':'mania'}[args.mode]
            if args.mode else beatmap.get('mode','osu'))
    bmset = beatmap.get('beatmapset') or {}
    print(f'{bmset.get("artist","?")} - {bmset.get("title","?")} '
          f'[{beatmap.get("version","?")}] | {mode} | {beatmap.get("difficulty_rating", 0)}★')
    print(beatmap.get('url') or f'https://osu.ppy.sh/beatmaps/{beatmap["id"]}')
    data = client.beatmap_scores(beatmap['id'], mode) or {}
    scores = data.get('scores', []) if isinstance(data, dict) else []
    if not scores:
        print('No public leaderboard scores returned for this map/mode.')
    for rank, s in enumerate(scores[:args.top], 1):
        print(f'#{rank:<3} {_score(s)}')
    username = args.user
    if not username:
        try: username = _local_player()
        except (OSError, FormatError): pass
    if username:
        usr = client.user(username, mode)
        if usr:
            placement = client.user_score(beatmap['id'], usr['id'], mode)
            if placement and placement.get('score'):
                print(f'\n{usr.get("username", username)} online: '
                      f'position #{placement.get("position", "?")} | {_score(placement["score"])}')
            else:
                print(f'\n{usr.get("username", username)}: no online score found')
    return 0


def main_doctor(argv=None):
    import importlib.util
    import shutil
    parser = argparse.ArgumentParser(description='Check osu-tools setup without starting background tasks')
    parser.add_argument('--deep', action='store_true', help='Count beatmap folders (slower on large libraries)')
    args = parser.parse_args(argv)
    print('osu-tools diagnostics')
    for label, p in [('Songs', paths.songs_dir()), ('osu!.db', paths.osu_root()/'osu!.db'),
                     ('collection.db', paths.osu_root()/'collection.db'),
                     ('scores.db', paths.osu_root()/'scores.db'), ('Current state', paths.state_file())]:
        print(f'  {label}: {"OK" if p.exists() else "missing"} ({p})')
    for command in ['inotifywait', 'ffmpeg', 'ffprobe']:
        print(f'  {command}: {"OK" if shutil.which(command) else "missing"}')
    for module in ['rosu_pp_py', 'librosa', 'numpy', 'soundfile']:
        print(f'  Python {module}: {"OK" if importlib.util.find_spec(module) else "optional / not installed"}')
    try:
        from .api import credentials
        credentials()
        print('  osu! API credentials: configured')
    except Exception as e:
        print('  osu! API credentials: not ready (' + str(e).split(';')[0] + ')')
    if args.deep:
        import os
        if paths.songs_dir().is_dir():
            count = sum(e.is_dir(follow_symlinks=False) for e in os.scandir(paths.songs_dir()))
            try: limit = int(Path('/proc/sys/fs/inotify/max_user_watches').read_text().strip())
            except (OSError, ValueError): limit = None
            print(f'  Inotify direct beatmap folders: {count}, configured watches: {limit}')
    return 0


def run(main):
    try:
        return main()
    except (OSError, FormatError, SafetyError, ValueError) as exc:
        print(f'osu-tools: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:
        from .api import ApiError
        if isinstance(exc, ApiError):
            print(f'osu-tools API: {exc}', file=sys.stderr)
            return 1
        raise
