"""On-demand estimated legacy pp for verified, locally saved osu!stable scores.

No network access and no global Songs scan. Each candidate .osu file is checked
against the score checksum. No user database or readable-index modifications.
"""
import hashlib
import os
from pathlib import Path
from . import paths

# Deliberately conservative: native non-std difficulties do not convert.
MODS_NO_ESTIMATE = 128 | 2048 | 8192 | 8388608  # RX, AT, AP, TP
MAX_MAP_BYTES = 16 * 1024 * 1024
MAX_FILES_PER_FOLDER = 300


class MapLocator:
    """Lookup installed .osu files only in their osu!.db-reported folder."""

    def __init__(self, songs=None):
        self.songs = Path(songs or paths.songs_dir()).resolve()
        self.folders = {}

    def find(self, beatmap):
        md5 = beatmap.md5.lower()
        folder_name = Path(beatmap.folder_name)
        if (not beatmap.folder_name or folder_name.is_absolute()
                or '..' in folder_name.parts):
            return None
        candidate = self.songs / folder_name
        try:
            folder = candidate.resolve(strict=True)
            if not folder.is_relative_to(self.songs) or not folder.is_dir():
                return None
        except (OSError, RuntimeError):
            return None
        if folder not in self.folders:
            checksums = {}
            try:
                with os.scandir(folder) as directory:
                    names = sorted((item for item in directory
                                    if item.name.lower().endswith('.osu') and
                                    item.is_file(follow_symlinks=False)),
                                   key=lambda item: item.name)
                if len(names) > MAX_FILES_PER_FOLDER:
                    self.folders[folder] = {}
                    return None
                for entry in names:
                    file = Path(entry.path)
                    if file.stat().st_size > MAX_MAP_BYTES:
                        continue
                    with file.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'md5').hexdigest()
                    checksums.setdefault(digest, file)
            except OSError:
                return None
            self.folders[folder] = checksums
        return self.folders[folder].get(md5)


def _rosu_engine():
    try:
        import rosu_pp_py as rosu
    except ImportError as exc:
        raise ValueError('rosu_pp_py is required for local pp: install rosu-pp-py') from exc
    return rosu


def estimate(row, map_path, native_mode, rosu=None):
    """Calculate estimated pp using local hit counts (never leaderboard pp)."""
    played_mode = row['mode']
    if played_mode not in (0, 1, 2, 3):
        raise ValueError('Unknown played ruleset')
    if played_mode != native_mode and native_mode != 0:
        raise ValueError('Only native standard difficulties can be converted')
    mods = int(row['mods_bitmask'])
    if mods & MODS_NO_ESTIMATE:
        raise ValueError('Unsupported assist/practice mod for pp estimation')
    if not sum(row[name] for name in ('n300', 'n100', 'n50', 'ngeki', 'nkatu', 'nmiss')):
        raise ValueError('No hit counts recorded for this saved score')
    rosu = rosu or _rosu_engine()
    beatmap = rosu.Beatmap(path=str(map_path))
    if hasattr(beatmap, 'is_suspicious') and beatmap.is_suspicious():
        raise ValueError('Suspicious .osu file (rosu-pp refused to evaluate)')

    kwargs = dict(mods=mods, combo=int(row['max_combo']),
                  n300=int(row['n300']), n100=int(row['n100']),
                  n50=int(row['n50']), n_geki=int(row['ngeki']),
                  n_katu=int(row['nkatu']))
    if hasattr(rosu, 'Performance'):
        if played_mode != native_mode:
            mode = {1: 'Taiko', 2: 'Catch', 3: 'Mania'}[played_mode]
            beatmap.convert(getattr(rosu.GameMode, mode), mods)
        result = rosu.Performance(lazer=False, misses=int(row['nmiss']), **kwargs).calculate(beatmap)
    elif hasattr(rosu, 'Calculator'):
        result = rosu.Calculator(mode=played_mode, n_misses=int(row['nmiss']),
                                 **kwargs).performance(beatmap)
    else:
        raise ValueError('Unsupported rosu-pp-py version; update rosu-pp-py')
    pp = float(result.pp)
    if not 0 <= pp < 1_000_000:
        raise ValueError('Invalid pp result from rosu-pp-py')
    difficulty = getattr(result, 'difficulty', None)
    stars = getattr(difficulty, 'stars', None)
    return round(pp, 2), round(float(stars), 2) if stars is not None else None


def local_estimates(rows, maps, *, songs=None, rosu=None):
    """Estimate pp for bounded input; return enriched outcomes and skip reasons."""
    if len(rows) > 20:
        raise ValueError('Limit pp calculation to 20 saved scores per invocation')
    locator = MapLocator(songs)
    outcomes = []
    from .scores import enrich
    for score in rows:
        item = enrich(score, maps)
        item['estimated_pp'] = None
        item['estimated_stars'] = None
        bm = maps.get(score['map_md5'])
        if bm is None:
            item['pp_skipped'] = 'Difficulty is not installed or not indexed'
        else:
            file = locator.find(bm)
            if file is None:
                item['pp_skipped'] = 'Matching .osu file not found in indexed beatmap folder'
            else:
                try:
                    item['estimated_pp'], item['estimated_stars'] = estimate(
                        score, file, bm.native_mode, rosu=rosu)
                    item['pp_skipped'] = None
                except (ValueError, RuntimeError, OSError, TypeError) as exc:
                    item['pp_skipped'] = str(exc)
        outcomes.append(item)
    return outcomes
