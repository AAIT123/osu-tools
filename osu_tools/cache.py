"""Readable, persistent JSONL library snapshot used directly as the cache.

No SQLite or background service: the on-disk index is a normal set of UTF-8
JSON/JSONL files. Timestamped archival copies of these files plus binary
originals can be created with `osu library snapshot`.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from . import paths
from .binary import FormatError
from .database import Beatmap, load_beatmaps, played_hashes, iter_saved_scores

SCHEMA = 2
CACHE_FILENAME = 'manifest.json'  # compatibility for existing test integrations


def index_dir():
    return Path(os.environ.get('OSU_LIBRARY_INDEX',
                str(Path(os.environ.get('XDG_DATA_HOME', '~/.local/share')).expanduser()
                / 'osu-tools' / 'library-index'))).expanduser()


def source_fingerprint(path: Path) -> tuple:
    st = Path(path).stat()
    return (str(Path(path).resolve()), st.st_dev, st.st_ino, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


def _folder():
    base = index_dir()
    if base.is_symlink():
        raise OSError(f'Library index directory is a symlink: {base}')
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(base, 0o700)
    return base


def _manifest(base):
    try:
        obj = json.loads((base/CACHE_FILENAME).read_text(encoding='utf-8'))
        return obj if obj.get('schema') == SCHEMA else {'schema': SCHEMA}
    except (OSError, ValueError, AttributeError):
        return {'schema': SCHEMA}


def _save_json(path, data):
    _atomic(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix='.index-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_jsonl(path, records):
    fd, tmp = tempfile.mkstemp(prefix='.index-', dir=path.parent)
    h = hashlib.sha256()
    n = 0
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), 0o600)
            for item in records:
                line = (json.dumps(item, ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8')
                f.write(line)
                h.update(line)
                n += 1
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return n, h.hexdigest()


def _read_jsonl(path, digest):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for line in f:
            h.update(line)
            yield json.loads(line)
    if h.hexdigest() != digest:
        raise ValueError(f'Index digest mismatch: {path.name}')


def _tag(stamp):
    return hashlib.sha256(json.dumps(stamp).encode()).hexdigest()[:20]


def _ensure_source(path, stamp):
    if list(source_fingerprint(path)) != stamp:
        raise FormatError(f'{path.name} changed while building/reading snapshot; retry when osu! is idle')


def _notice(inform, message):
    if inform:
        inform(message)


def cached_beatmaps(path: Path, *, refresh=False, enabled=True, inform=None):
    path = Path(path)
    if not enabled:
        return load_beatmaps(path)
    stamp = list(source_fingerprint(path))
    try:
        base = _folder()
        meta = _manifest(base)
        entry = meta.get('beatmaps', {})
        file = base / entry.get('file', 'not-present')
        if (not refresh and entry.get('fingerprint') == stamp and file.is_file()
                and not file.is_symlink()):
            try:
                rows = list(_read_jsonl(file, entry['sha256']))
                if len(rows) != entry['count']:
                    raise ValueError('Index row count differs from manifest')
                maps = {row['md5']: Beatmap(**row) for row in rows}
                if len(maps) != len(rows):
                    raise ValueError('Duplicate checksum in index')
                _ensure_source(path, stamp)
                return entry['version'], entry['player'], maps
            except (KeyError, TypeError, ValueError, OSError):
                print('osu-tools: readable beatmap index damaged; rebuilding from osu!.db', file=sys.stderr)
        _notice(inform, 'Building readable beatmaps.jsonl index from osu!.db...')
        version, player, maps = load_beatmaps(path)
        _ensure_source(path, stamp)
        fname = f'beatmaps-{_tag(stamp)}.jsonl'
        n, digest = _write_jsonl(base/fname, (asdict(b) for b in maps.values()))
        _ensure_source(path, stamp)
        meta = _manifest(base)
        meta['beatmaps'] = dict(fingerprint=stamp, version=version, player=player,
                                file=fname, count=n, sha256=digest)
        _save_json(base/CACHE_FILENAME, meta)
        return version, player, maps
    except FormatError:
        raise
    except (OSError, ValueError) as e:
        print(f'osu-tools: readable index unavailable ({e}); reading osu!.db directly', file=sys.stderr)
        result = load_beatmaps(path)
        _ensure_source(path, stamp)
        return result


def cached_played_hashes(path: Path, *, refresh=False, enabled=True, inform=None):
    path = Path(path)
    if not enabled:
        return played_hashes(path)
    stamp = list(source_fingerprint(path))
    try:
        base = _folder()
        meta = _manifest(base)
        entry = meta.get('scores', {})
        playfile = base / entry.get('played_file', 'not-present')
        scorefile = base / entry.get('file', 'not-present')
        if (not refresh and entry.get('fingerprint') == stamp
                and playfile.is_file() and scorefile.is_file()
                and not playfile.is_symlink() and not scorefile.is_symlink()):
            try:
                raw = playfile.read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['played_sha256']:
                    raise ValueError('Played index digest mismatch')
                hashes = json.loads(raw)
                if not isinstance(hashes, list) or len(hashes) != entry['played_count']:
                    raise ValueError('Played index row count mismatch')
                result = set(hashes)
                if len(result) != len(hashes):
                    raise ValueError('Duplicate played hashes')
                _ensure_source(path, stamp)
                return result
            except (KeyError, TypeError, ValueError, OSError):
                print('osu-tools: readable score index damaged; rebuilding from scores.db', file=sys.stderr)
        _notice(inform, 'Building readable scores.jsonl + played.json index from scores.db...')
        played = set()
        def records():
            for record in iter_saved_scores(path):
                if record['map_md5']:
                    played.add(record['map_md5'])
                yield record
        ident = _tag(stamp)
        fname = f'scores-{ident}.jsonl'
        n, digest = _write_jsonl(base/fname, records())
        _ensure_source(path, stamp)
        pfile = f'played-{ident}.json'
        _save_json(base/pfile, sorted(played))
        raw = (base/pfile).read_bytes()
        meta = _manifest(base)
        meta['scores'] = dict(fingerprint=stamp, file=fname, score_count=n,
                              sha256=digest, played_file=pfile,
                              played_count=len(played),
                              played_sha256=hashlib.sha256(raw).hexdigest())
        _save_json(base/CACHE_FILENAME, meta)
        return played
    except FormatError:
        raise
    except (OSError, ValueError) as e:
        print(f'osu-tools: readable index unavailable ({e}); reading scores.db directly', file=sys.stderr)
        result = played_hashes(path)
        _ensure_source(path, stamp)
        return result
