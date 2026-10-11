"""Policy-driven synchronization of personal osu!stable collections.

Only explicitly configured variant names propagate into their aggregate;
there is no automatic prefix matching. Native mode is checked before upward
propagation, and converts remain explicit manual tags.
"""
from dataclasses import dataclass, field

from .database import CollectionsDB, Beatmap, LOVED_STATUS
from .policy import Policy, load_policy, CONVERT, LEGACY_ROOT_SOURCES

MODE_GROUPS = {'std': (0, 'std all'), 'taiko': (1, 'taiko all'),
               'ctb': (2, 'ctb'), 'mania': (3, 'mania all')}
@dataclass
class Changes:
    additions: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    removals: dict[str, list[str]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    # Destination name -> originating collection/rule -> number of new hashes
    sources: dict[str, dict[str, int]] = field(default_factory=dict)

    def has_changes(self):
        return bool(self.created) or any(self.additions.values()) or any(self.removals.values())


def sync(data: CollectionsDB, by_md5: dict[str, Beatmap], *, operations=('sync',),
         played: set[str] | None = None, create_missing=False,
         prune_mismatches=False, from_root=False, policy: Policy | None = None) -> Changes:
    """Compute a plan by changing only the in-memory copy of collections.

    `sync` by default uses explicit policy variant -> native group -> all,
    plus loved/played (if enabled in the policy).
    `modes` and `from_root=True` explicitly enable bulk root -> native mode.
    Wrong-native records remain untouched unless prune_mismatches=True.
    """
    policy = policy if policy is not None else load_policy()
    chosen = set(operations)
    if 'sync' in chosen:
        chosen.remove('sync')
        chosen.update(('variants', 'all', 'loved', 'played'))
    if from_root:
        chosen.add('modes')
    invalid = chosen - {'variants', 'modes', 'all', 'loved', 'played'}
    if invalid:
        raise ValueError(f'Unknown sync operation(s): {sorted(invalid)}')

    diff = Changes()
    by_key = {h.lower(): bm for h, bm in by_md5.items()}
    seen = {c.name: {h.lower() for h in c.hashes} for c in data.collections}
    warned = set()

    def warn(message):
        if message not in warned:
            diff.warnings.append(message)
            warned.add(message)

    def target(name, *, required=True):
        c = data.find(name)
        if c is None and create_missing:
            c = data.ensure(name, True)
            seen[name] = set()
            diff.created.append(name)
            diff.additions.setdefault(name, [])
        if c is None and required:
            warn(f'Missing collection {name!r}: create it in osu!, or use --create-missing')
        return c

    def add(name, hashes, *, source):
        c = target(name)
        if c is None:
            return
        s = seen[c.name]
        for h in hashes:
            if not h:
                continue
            key = h.lower()
            if key not in s:
                s.add(key)
                c.hashes.append(h)
                diff.additions.setdefault(c.name, []).append(h)
                entry = diff.sources.setdefault(c.name, {})
                entry[source] = entry.get(source, 0) + 1

    def standard_converts(c):
        """Only known native osu!standard (mode 0) difficulties can convert.

        Unknown checksums and other native modes stay in their manual tags,
        but never propagate to playable-mode aggregates or the root.
        """
        accepted, wrong, unknown = [], [], []
        for h in c.hashes:
            bm = by_key.get(h.lower())
            if bm is None:
                unknown.append(h)
            elif bm.native_mode == 0:
                accepted.append(h)
            else:
                wrong.append(h)
        if wrong:
            example = by_key[wrong[0].lower()]
            warn(f'{c.name}: {len(wrong)} non-standard difficulty(ies) ignored as converts '
                 f'(example: {example.label}, native mode {example.native_mode})')
        if unknown:
            warn(f'{c.name}: {len(unknown)} unknown checksum(s) not propagated as converts')
        return accepted

    if any(name in LEGACY_ROOT_SOURCES for name in policy.root_sources):
        warn("Policy has obsolete 'std converts' source; it will be ignored. "
             "Remove it from ~/.config/osu-tools/collections.json")

    # Collections are FLAT in osu!stable. Only exact names explicitly listed
    # in the personal policy are propagation rules. Never guess from prefixes.
    if 'variants' in chosen:
        for source_name, destination in policy.variant_sources.items():
            c = data.find(source_name)
            if c is None:
                continue  # No need to warn about optional variants.
            if destination in CONVERT:
                add(destination, standard_converts(c),
                    source=f'configured convert variant: {source_name}')
                continue
            native_id = next(mode_id for mode_id, mode_group in MODE_GROUPS.values()
                             if mode_group == destination)
            accepted = []
            wrong = []
            unresolved = []
            for h in c.hashes:
                bm = by_key.get(h.lower())
                if bm is None:
                    unresolved.append(h)
                elif bm.native_mode == native_id:
                    accepted.append(h)
                else:
                    wrong.append(h)
            add(destination, accepted, source=f'configured variant: {source_name}')
            if wrong:
                bm = by_key[wrong[0].lower()]
                warn(f'{source_name}: {len(wrong)} non-native entries ignored for {destination}; '
                     f'keep manual tags/convert tags intact (example: {bm.label})')
            if unresolved:
                warn(f'{source_name}: {len(unresolved)} unresolved checksum(s), not propagated')

    # An explicit convert aggregate carries the user's intentional playable-mode
    # classification. It is *not* inferred from a .osu file's native mode.
    # When enabled, the declared convert also belongs in that mode's aggregate.
    # Other non-native members of the aggregate remain excluded/diagnosed.
    convert_exceptions = {name: set() for _, name in MODE_GROUPS.values()}
    if policy.convert_into_mode_all:
        for convert_name in policy.root_sources:
            if convert_name not in CONVERT:
                continue
            c = data.find(convert_name)
            if c is None:
                continue
            target_name = MODE_GROUPS[convert_name.split(' ', 1)[0]][1]
            eligible = standard_converts(c)
            convert_exceptions[target_name].update(h.lower() for h in eligible)
            if 'all' in chosen or 'variants' in chosen:
                add(target_name, eligible, source=f'explicit standard converts: {convert_name}')

    # Explicit aggregate sources propagate upward to root. A native aggregate
    # accepts native difficulties and explicitly tagged convert exceptions.
    if 'all' in chosen or 'variants' in chosen:
        for name in policy.root_sources:
            if name in LEGACY_ROOT_SOURCES:
                continue  # Backward-compatible: old policy is readable, never active.
            c = data.find(name)
            if c is None:
                continue
            if name in CONVERT:
                add('all', standard_converts(c), source=f'configured standard converts: {name}')
                continue
            native_id = next(mode_id for mode_id, mode_group in MODE_GROUPS.values()
                             if mode_group == name)
            accepted, wrong, unresolved = [], [], []
            for h in c.hashes:
                bm = by_key.get(h.lower())
                if h.lower() in convert_exceptions[name]:
                    accepted.append(h)
                elif bm is None:
                    unresolved.append(h)
                elif bm.native_mode == native_id:
                    accepted.append(h)
                else:
                    wrong.append(h)
            add('all', accepted, source=f'configured native group: {name}')
            if wrong:
                warn(f'{name}: {len(wrong)} non-native entries not propagated to all')
            if unresolved:
                warn(f'{name}: {len(unresolved)} unresolved checksum(s), not propagated to all')

    # Explicit reverse classification for root maps, preserving convert
    # exceptions by using each .osu difficulty's actual native mode.
    if 'modes' in chosen or prune_mismatches:
        for mode, (native_id, name) in MODE_GROUPS.items():
            c = data.find(name)
            if not c:
                continue
            wrong = [h for h in c.hashes
                     if h.lower() in by_key and by_key[h.lower()].native_mode != native_id
                     and h.lower() not in convert_exceptions[name]]
            if wrong:
                warn(f'{name}: {len(wrong)} known non-native member(s) '
                     f'(use --prune-mismatches only after review)')
            if wrong and prune_mismatches:
                add('all', wrong, source=f'pruned from: {name}')
                bad = {h.lower() for h in wrong}
                c.hashes[:] = [h for h in c.hashes if h.lower() not in bad]
                seen[c.name] = {h.lower() for h in c.hashes}
                diff.removals[name] = wrong

    if 'modes' in chosen:
        root = target('all')
        if root:
            buckets = {mode: [] for mode in MODE_GROUPS}
            for h in root.hashes:
                bm = by_key.get(h.lower())
                if bm is not None:
                    for mode, (native_id, _) in MODE_GROUPS.items():
                        if bm.native_mode == native_id:
                            buckets[mode].append(h)
                            break
            for mode, (_, name) in MODE_GROUPS.items():
                add(name, buckets[mode], source='root: all (explicit reverse sync)')

    if 'loved' in chosen and policy.sync_loved:
        loved = [h for h, bm in by_md5.items() if bm.ranked_status == LOVED_STATUS]
        add('all loved', loved, source='installed Loved status')
    if 'played' in chosen and policy.sync_played:
        if played is None:
            warn('scores.db not available: exact local played sync skipped')
        else:
            add('all played', [h for h in by_md5 if h.lower() in played],
                source='local scores.db')
            diff.counts['played_unknown'] = len(played - set(by_key))

    diff.counts['collections_changed'] = len(set(diff.created) | {k for k, v in diff.additions.items() if v} | {k for k, v in diff.removals.items() if v})
    diff.counts['hashes_removed'] = sum(map(len, diff.removals.values()))
    diff.counts['hashes_added'] = sum(map(len, diff.additions.values()))
    return diff
