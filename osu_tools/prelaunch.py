"""Opt-in, no-daemon prelaunch collection sync.

Fast path only calls stat() on source files and a small local state file. A
successful run (preview or apply) records the *post-run* fingerprints, so an
apply does not immediately reschedule itself. A running game always wins.
"""
import argparse
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from . import paths
from .cache import source_fingerprint
from .safety import game_is_running

SCHEMA = 1
MAX_INTERVAL = 30 * 24 * 3600


def config_path():
    return paths.config_dir() / 'prelaunch.json'


def state_path():
    return paths.cache_dir() / 'prelaunch-state.json'


def _safe_read_json(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'Refusing symlink: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def _atomic_json(path, item):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f'Refusing symlink: {path}')
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.prelaunch-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(item, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _atomic_text(path, content):
    """Private report: never create a world-readable intermediate log."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f'Refusing symlink: {path}')
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.prelaunch-log-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_config():
    try:
        item = _safe_read_json(config_path())
    except FileNotFoundError:
        return {'version': SCHEMA, 'mode': 'off', 'interval_seconds': 86400, 'max_additions': 100}
    if (not isinstance(item, dict) or item.get('version') != SCHEMA
            or item.get('mode') not in ('off', 'preview', 'apply')
            or type(item.get('interval_seconds')) is not int
            or not 0 <= item['interval_seconds'] <= MAX_INTERVAL
            or type(item.get('max_additions')) is not int
            or not 0 <= item['max_additions'] <= 1000):
        raise ValueError('Invalid prelaunch configuration; try osu prelaunch enable --preview')
    return item


def _fingerprints():
    root = paths.osu_root()
    sources = (root / 'osu!.db', root / 'collection.db',
               root / 'scores.db', paths.config_dir() / 'collections.json')
    result = {}
    for source in sources:
        try:
            result[str(source)] = list(source_fingerprint(source))
        except FileNotFoundError:
            result[str(source)] = None
    return result


def _last_state():
    try:
        value = _safe_read_json(state_path())
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) and value.get('version') == SCHEMA else {}


def _run_once(config, *, force=False, quiet=False):
    # Lock regardless of invocation source: manual, launcher or optional cron.
    lock = paths.cache_dir() / 'prelaunch.lock'
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if lock.is_symlink():
        raise ValueError(f'Refusing symlink: {lock}')
    with lock.open('a+b') as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if game_is_running():
            if not quiet:
                print('osu! is running; skipping prelaunch sync.')
            return 0
        before = _fingerprints()
        now = time.time()
        last = _last_state()
        if (not force and last.get('mode') == config['mode']
                and last.get('sources') == before
                and now - last.get('last_success', 0) < config['interval_seconds']):
            if not quiet:
                print('No changed source files; next scheduled check not due.')
            return 0
        from .cli import main_collections, run
        arguments = ['sync']
        if config['mode'] == 'apply':
            arguments += ['--apply', '--max-additions', str(config['max_additions']),
                          '--max-removals', '0']
        # Always save the full report; keep launcher output succinct.
        log = paths.cache_dir() / 'prelaunch.log'
        if log.is_symlink():
            raise ValueError(f'Refusing symlink: {log}')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = run(lambda: main_collections(arguments))
        _atomic_text(log, output.getvalue())
        if result != 0:
            print(f'Prelaunch sync failed; see {log}', file=sys.stderr)
            return result
        after = _fingerprints()
        if config['mode'] == 'preview' and after != before:
            print('Sources changed while preparing preview; retry next time.', file=sys.stderr)
            return 1
        _atomic_json(state_path(), {'version': SCHEMA, 'mode': config['mode'],
                                     'sources': after, 'last_success': time.time()})
        if not quiet:
            print(f'Prelaunch {config["mode"]} completed; report: {log}')
        return 0


def main_prelaunch(argv=None):
    parser = argparse.ArgumentParser(description='Optional, non-daemon collection sync before starting osu!')
    parser.add_argument('command', nargs='?', choices=['status', 'enable', 'disable', 'run'], default='status')
    choices = parser.add_mutually_exclusive_group()
    choices.add_argument('--apply', action='store_true', help='Explicitly enable guarded automatic writes')
    choices.add_argument('--preview', action='store_true', help='Only generate a dry-run report')
    parser.add_argument('--interval-hours', type=int, default=24,
                        help='Rescan unchanged sources at this interval (0-720 hours; default 24)')
    parser.add_argument('--max-additions', type=int, default=100,
                        help='Automatic write cap, 0-1000 (default 100)')
    parser.add_argument('--force-check', action='store_true',
                        help='Run even if sources unchanged and interval not elapsed')
    parser.add_argument('--quiet', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == 'enable':
        if not 0 <= args.interval_hours <= 720 or not 0 <= args.max_additions <= 1000:
            parser.error('--interval-hours must be 0-720 and --max-additions must be 0-1000')
        mode = 'apply' if args.apply else 'preview'
        data = {'version': SCHEMA, 'mode': mode,
                'interval_seconds': args.interval_hours * 3600,
                'max_additions': args.max_additions}
        _atomic_json(config_path(), data)
        print(f'Prelaunch {mode} enabled; check on next plain `osu` launch. '
              f'Interval {args.interval_hours}h, max automatic additions {args.max_additions}.')
        if mode == 'apply':
            print('Automatic apply creates verified backups. No pruning, force, or bulk override.')
        return 0
    if args.command == 'disable':
        item = load_config()
        item['mode'] = 'off'
        _atomic_json(config_path(), item)
        print('Prelaunch checks disabled.')
        return 0
    config = load_config()
    if args.command == 'status':
        print(f'Prelaunch: {config["mode"]}; interval: {config["interval_seconds"] // 3600}h; '
              f'write cap: {config["max_additions"]}; config: {config_path()}')
        print(f'Last report: {paths.cache_dir() / "prelaunch.log"}')
        return 0
    if config['mode'] == 'off':
        return 0
    try:
        return _run_once(config, force=args.force_check, quiet=args.quiet)
    except BlockingIOError:
        if not args.quiet:
            print('Another prelaunch check is already running; skipped.')
        return 0
