"""Timestamped, readable snapshots backed by the very same index used by sync.

The JSON exports are for browsing and indexing. Exact restore requires the
original .db files included in an archival snapshot. Saved replay files under
Data/r are optional due to their potentially considerable size.
"""
import csv
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from . import paths
from .cache import cached_beatmaps, cached_played_hashes, index_dir, source_fingerprint
from .database import load_collections
from .safety import SafetyError, game_is_running, sha256


def _csv_safe(v):
    # Neutralize spreadsheet formulas in artist/title/username columns.
    if isinstance(v, str) and v and v.lstrip()[:1] in ('=', '+', '-', '@'):
        return "'" + v
    return v


def _ticks_utc(ticks):
    try:
        return (datetime(1, 1, 1, tzinfo=timezone.utc)
                + timedelta(microseconds=int(ticks)//10)).isoformat()
    except (ValueError, OverflowError, TypeError):
        return ''


def snapshot_dir():
    return Path(os.environ.get('OSU_LIBRARY_SNAPSHOTS',
         str(Path(os.environ.get('XDG_DATA_HOME', '~/.local/share')).expanduser()
             / 'osu-tools' / 'snapshots'))).expanduser()


def _copy_verified(source, dest):
    """Copy and hash the source in one pass, then read back destination once.

    Avoids the repeated source/destination hashing the earlier snapshot loop
    did for each replay; still detects a bad destination before publication.
    """
    digest = hashlib.sha256()
    with Path(source).open('rb') as src, Path(dest).open('xb') as dst:
        os.fchmod(dst.fileno(), 0o600)
        for chunk in iter(lambda: src.read(1024 * 1024), b''):
            digest.update(chunk)
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    hexdigest = digest.hexdigest()
    if sha256(dest) != hexdigest:
        raise SafetyError(f'Copy mismatch for {source}; refusing incomplete snapshot')
    return hexdigest


def make_snapshot(*, with_replays=False, index_only=False, progress=None):
    """Create a new immutable archive. Defaults to including exact .db originals."""
    report = progress or (lambda message: None)
    if with_replays and index_only:
        raise ValueError('--with-replays requires raw database originals')
    if not index_only and game_is_running():
        raise SafetyError('Close osu! before making a restorable database snapshot')
    root = paths.osu_root()
    sources = {name: root/name for name in ('osu!.db', 'scores.db', 'collection.db')}
    if any(not p.is_file() or p.is_symlink() for p in sources.values()):
        raise FileNotFoundError('Expected regular osu!.db, scores.db, and collection.db under osu! root')
    stamps = {name: source_fingerprint(path) for name,path in sources.items()}
    report('Checking readable index (first build can take longer)...')
    cached_beatmaps(sources['osu!.db'])
    cached_played_hashes(sources['scores.db'])
    library = index_dir()
    idx = json.loads((library/'manifest.json').read_text(encoding='utf-8'))
    for k,name in [('beatmaps','osu!.db'),('scores','scores.db')]:
        if idx[k]['fingerprint'] != list(stamps[name]):
            raise SafetyError(f'{name} changed during index generation; retry')
    dest = snapshot_dir()
    if dest.is_symlink():
        raise SafetyError(f'Snapshot directory is a symlink: {dest}')
    dest.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(dest, 0o700)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = stamp
    n = 1
    while (dest/name).exists():
        name = f'{stamp}-{n}'
        n += 1
    temp = Path(tempfile.mkdtemp(prefix='.snapshot-', dir=dest))
    os.chmod(temp, 0o700)
    try:
        files = {}
        report('Copying cached readable index...')
        for table in ('beatmaps','scores'):
            entry = idx[table]
            for key in ('file','played_file'):
                if key not in entry:
                    continue
                item = entry[key]
                path = library/item
                if not path.is_file() or path.is_symlink():
                    raise SafetyError(f'Expected index file missing: {path}')
                shutil.copyfile(path, temp/item)
                os.chmod(temp/item, 0o600)
                digest = sha256(temp/item)
                if key == 'file' and digest != entry['sha256']:
                    raise SafetyError(f'Index file changed during snapshot: {item}')
                if key == 'played_file' and digest != entry['played_sha256']:
                    raise SafetyError(f'Index file changed during snapshot: {item}')
                files[item] = digest
        report('Exporting collections and CSV files...')
        db = load_collections(sources['collection.db'])
        contents = {'version': db.version, 'collections': [
            {'name': c.name, 'hashes': c.hashes} for c in db.collections]}
        collections_path = temp/'collections.json'
        collections_path.write_text(json.dumps(contents, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        os.chmod(collections_path, 0o600)
        files['collections.json'] = sha256(collections_path)
        # Human-friendly CSV views (not used as the cache; JSONL remains canonical).
        maps = {}
        maps_file = temp/idx['beatmaps']['file']
        with (temp/'beatmaps.csv').open('w', newline='', encoding='utf-8') as out:
            csvout = csv.writer(out)
            columns = ('md5','artist','title','difficulty','native_mode','ranked_status',
                       'beatmap_id','beatmapset_id','folder_name')
            csvout.writerow(columns)
            with maps_file.open('r', encoding='utf-8') as source:
                for line in source:
                    row = json.loads(line)
                    maps[row['md5']] = row
                    csvout.writerow([_csv_safe(row.get(k, '')) for k in columns])
        os.chmod(temp/'beatmaps.csv', 0o600)
        files['beatmaps.csv'] = sha256(temp/'beatmaps.csv')
        with (temp/'collections.csv').open('w', newline='', encoding='utf-8') as out:
            csvout = csv.writer(out)
            csvout.writerow(('collection','md5','artist','title','difficulty','native_mode'))
            for col in db.collections:
                for h in col.hashes:
                    row = maps.get(h.lower(), {})
                    csvout.writerow([_csv_safe(col.name), h,
                                    _csv_safe(row.get('artist', '')),
                                    _csv_safe(row.get('title', '')),
                                    _csv_safe(row.get('difficulty', '')),
                                    row.get('native_mode', '')])
        os.chmod(temp/'collections.csv', 0o600)
        files['collections.csv'] = sha256(temp/'collections.csv')
        with (temp/'scores.csv').open('w', newline='', encoding='utf-8') as out:
            csvout = csv.writer(out)
            columns = ('date_utc','map_md5','player','mode','score','max_combo',
                       'mods_bitmask','n300','n100','n50','ngeki','nkatu','nmiss')
            csvout.writerow(columns)
            with (temp/idx['scores']['file']).open('r', encoding='utf-8') as source:
                for line in source:
                    row = json.loads(line)
                    csvout.writerow([_ticks_utc(row.get('timestamp_ticks', 0))]
                                    + [_csv_safe(row.get(k, '')) for k in columns[1:]])
        os.chmod(temp/'scores.csv', 0o600)
        files['scores.csv'] = sha256(temp/'scores.csv')
        if not index_only:
            raw = temp/'originals'
            raw.mkdir(mode=0o700)
            report('Copying and verifying original databases (recovery copies)...')
            for srcname, source in sources.items():
                dst = raw/srcname
                files[f'originals/{srcname}'] = _copy_verified(source, dst)
                report(f'  Verified {srcname} ({dst.stat().st_size / (1024*1024):.1f} MiB)')
            if with_replays:
                replays = root/'Data'/'r'
                if replays.is_dir():
                    target = temp/'Data'/'r'
                    target.mkdir(parents=True)
                    report('Copying and verifying replay files (can take a long time)...')
                    count, copied_bytes = 0, 0
                    last_report = time.monotonic()
                    for source in replays.iterdir():
                        if not source.is_file() or source.is_symlink() or source.suffix.lower() != '.osr':
                            continue
                        dst = target/source.name
                        files[f'Data/r/{source.name}'] = _copy_verified(source, dst)
                        copied_bytes += dst.stat().st_size
                        count += 1
                        if count % 250 == 0 or time.monotonic() - last_report >= 5:
                            report(f'  {count:,} replays copied and verified ({copied_bytes / (1024*1024):.1f} MiB)')
                            last_report = time.monotonic()
                    report(f'  Completed: {count:,} replays ({copied_bytes / (1024*1024):.1f} MiB)')
        if any(source_fingerprint(p) != stamps[n] for n,p in sources.items()):
            raise SafetyError('A source database changed during snapshot; refusing inconsistent archive')
        if not index_only and game_is_running():
            raise SafetyError('osu! started during snapshot creation; refusing to publish an inconsistent archive')
        manifest = {'format': 'osu-tools-readable-snapshot-v1',
                    'created_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                    'source': str(root), 'restorable_binary': not index_only,
                    'includes_replays': with_replays, 'index': idx,
                    'source_fingerprints': {k: list(v) for k,v in stamps.items()},
                    'files_sha256': files}
        mpath = temp/'snapshot.json'
        mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        os.chmod(mpath, 0o600)
        (temp/'README.txt').write_text(
            'osu-tools library snapshot\n'
            'beatmaps-*.jsonl = beatmap metadata, one JSON object per line\n'
            'scores-*.jsonl = local score metadata, one JSON object per saved score\n'
            'played-*.json = deduplicated difficulty checksums with saved scores\n'
            'collections.json = collection names and their stored checksums\n'
            'beatmaps.csv / scores.csv / collections.csv = more readable views\n'
            'snapshot.json = source fingerprints and SHA-256 digests\n'
            'JSON files are readable exports; DO NOT restore by writing them as .db.\n'
            'Only files in originals/ can be used for byte-exact database restoration.\n'
            'Data/r replay files are included only if --with-replays was used.\n'
            'Contains usernames and play history: keep this directory private.\n',
            encoding='utf-8')
        os.chmod(temp/'README.txt', 0o600)
        report('Finalizing verified snapshot...')
        os.replace(temp, dest/name)
        return dest/name
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def list_snapshots():
    directory = snapshot_dir()
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir()
                  if p.is_dir() and not p.is_symlink() and (p/'snapshot.json').is_file())
