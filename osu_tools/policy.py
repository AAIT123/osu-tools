"""Explicit personal collection inclusion policy. No name-based inference."""
from dataclasses import dataclass, field
import json
from pathlib import Path
from . import paths

NATIVE = {'std': 'std all', 'taiko': 'taiko all', 'ctb': 'ctb', 'mania': 'mania all'}
# Only native osu!standard maps can convert to another mode. There is no
# meaningful 'std converts' collection, and native taiko/catch/mania maps
# cannot be converted into another ruleset.
CONVERT = {'taiko converts', 'ctb converts', 'mania converts'}
LEGACY_ROOT_SOURCES = {'std converts'}  # accepted for old configs but ignored
ALLOWED_TARGETS = set(NATIVE.values()) | CONVERT
DEFAULT_ROOT_SOURCES = list(NATIVE.values()) + sorted(CONVERT)


@dataclass
class Policy:
    variant_sources: dict[str, str] = field(default_factory=dict)
    root_sources: list[str] = field(default_factory=lambda: list(DEFAULT_ROOT_SOURCES))
    sync_loved: bool = True
    sync_played: bool = True
    convert_into_mode_all: bool = True

    def to_dict(self):
        return {'version': 1, 'variant_sources': self.variant_sources,
                'root_sources': self.root_sources, 'sync_loved': self.sync_loved,
                'sync_played': self.sync_played,
                'convert_into_mode_all': self.convert_into_mode_all}

    @classmethod
    def from_dict(cls, item):
        if not isinstance(item, dict) or item.get('version') != 1:
            raise ValueError('Unsupported collection policy version (expected 1)')
        variants = item.get('variant_sources', {})
        roots = item.get('root_sources', DEFAULT_ROOT_SOURCES)
        if not isinstance(variants, dict) or not isinstance(roots, list):
            raise ValueError('Policy variant_sources must be an object, root_sources must be an array')
        if any(not isinstance(k, str) or not isinstance(v, str) or v not in ALLOWED_TARGETS
               for k, v in variants.items()):
            raise ValueError('Variant sources must map exact collection names to a supported mode or converts aggregate')
        if any(not isinstance(n, str) or n not in (ALLOWED_TARGETS | LEGACY_ROOT_SOURCES) for n in roots):
            raise ValueError('root_sources may only contain known native/converts aggregates')
        if (not isinstance(item.get('sync_loved', True), bool)
                or not isinstance(item.get('sync_played', True), bool)
                or not isinstance(item.get('convert_into_mode_all', True), bool)):
            raise ValueError('sync_loved, sync_played and convert_into_mode_all must be booleans')
        return cls(dict(variants), list(dict.fromkeys(roots)),
                   item.get('sync_loved', True), item.get('sync_played', True),
                   item.get('convert_into_mode_all', True))


def policy_path() -> Path:
    return paths.config_dir() / 'collections.json'


def load_policy(path=None) -> Policy:
    path = Path(path) if path else policy_path()
    if not path.exists():
        return Policy()  # No variants inferred from their names.
    return Policy.from_dict(json.loads(path.read_text(encoding='utf-8')))


def init_policy(path=None) -> Path:
    path = Path(path) if path else policy_path()
    if path.exists():
        raise FileExistsError(f'Policy exists; will not overwrite {path}')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('x', encoding='utf-8') as f:
        json.dump(Policy().to_dict(), f, ensure_ascii=False, indent=2)
        f.write('\n')
    path.chmod(0o600)
    return path
