"""Refuse unsafe game-database writes; create verified, unique backups."""
from pathlib import Path
import hashlib
import os
import shutil
import tempfile
import time


class SafetyError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def game_is_running() -> bool:
    proc = Path('/proc')
    if not proc.exists():
        raise SafetyError('Cannot check /proc for osu!.exe; refusing a database write')
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / 'comm').read_bytes().lower()
            cmd = (entry / 'cmdline').read_bytes().lower()
        except (OSError, PermissionError):
            continue
        if b'osu!.exe' in comm or b'osu!.exe' in cmd:
            return True
    return False


def write_verified(path: Path, content: bytes, original_hash: str, *, force=False) -> Path:
    """Replace a non-symlink collection.db, backing up the exact file read."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SafetyError(f'Not a regular database file: {path}')
    if not force and game_is_running():
        raise SafetyError('osu! appears to be running; close it before using --apply')
    if sha256(path) != original_hash:
        raise SafetyError(f'{path.name} changed since the preview; aborting')
    original_mode = path.stat().st_mode & 0o777
    # O_EXCL ensures backups never overwrite each other, even within one second.
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = None
    for n in range(1000):
        candidate = path.with_name(f'{path.name}.bak.{stamp}.{n:03d}')
        try:
            with candidate.open('xb') as dst, path.open('rb') as src:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            os.chmod(candidate, original_mode)
            backup = candidate
            break
        except FileExistsError:
            continue
    if backup is None:
        raise SafetyError('Could not allocate a unique backup filename')
    if sha256(backup) != original_hash:
        raise SafetyError(f'Backup verification failed; original untouched: {backup}')
    # Same-directory tempfile + os.replace for atomic visibility.
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporary, original_mode)
        if sha256(path) != original_hash:
            raise SafetyError('Database changed while writing the temp file; original untouched')
        if not force and game_is_running():
            raise SafetyError('osu! started during write preparation; original untouched')
        os.replace(temporary, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup
