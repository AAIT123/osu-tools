"""Resolve osu!stable locations without reading or scanning files."""
from pathlib import Path
import os


def songs_dir() -> Path:
    return Path(os.environ.get('OSU_SONGS', '~/.local/share/osu-wine/osu!/Songs')).expanduser()


def osu_root() -> Path:
    return songs_dir().parent


def state_file() -> Path:
    return Path(os.environ.get('OSU_CURRENT_STATE', '~/.cache/osu-current-map')).expanduser()


def cache_dir() -> Path:
    return Path(os.environ.get('XDG_CACHE_HOME', '~/.cache')).expanduser() / 'osu-tools'


def config_dir() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME', '~/.config')).expanduser() / 'osu-tools'


def current_map() -> Path:
    p = state_file()
    try:
        path = Path(p.read_text(encoding='utf-8').strip())
    except OSError as exc:
        raise FileNotFoundError(f'No tracked beatmap in {p}; is osu current watch running?') from exc
    if not path.is_file():
        raise FileNotFoundError(f'Tracked beatmap is no longer present: {path}')
    return path
