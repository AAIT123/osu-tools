# Offline beatmap search

`osu search` searches **installed difficulties**, not online beatmapsets or saved
scores. It reads the existing readable `osu!.db` index: no API credentials,
network call, Songs directory walk, background service, or database writes.

```bash
osu search Kobaryo
osu search 'Search title' --mode taiko --limit 10
osu search --collection 'mania converts' --mode std
osu search --collection 'std hdhr' 'Granat'
osu search --loved --mode mania --limit 20
osu search --beatmap-id 123456
osu search --set-id 123456 --json
osu search Kobaryo --timings
```

The positional text is matched case-insensitively against artist, title and
difficulty. All whitespace-separated terms must be present, but may occur in
different fields. Results prefer exact and prefix matches, with deterministic
ties; no relevance scoring service is needed. At most 100 results are retained,
but the command reports the total match count.

**`--mode` means the difficulty's *native* mode**, not the ruleset in which a
standard map was played. For example, a standard difficulty explicitly tagged
in `mania converts` matches `--collection 'mania converts' --mode std`, but
not `--mode mania`. The command neither infers conversion nor changes
collections. `--collection` matches one *exact* collection name, ignoring case;
ambiguous or absent names cause an error. Unresolved checksums in collections
are counted and reported separately, not silently treated as maps.

`--loved` filters the status from the local osu!.db metadata; it is not a live
online rank-status check. `--beatmap-id` and `--set-id` filter by identifiers
stored locally. The JSON output includes checksum, native mode, local ranked
status, difficulty ID, beatmapset ID, and folder name. Folder names are metadata,
**not** guaranteed valid `.osu` paths. This command does not verify files on
disk; use checksum verification when performing pp calculations.

The initial cache build still reads `osu!.db`; later searches reuse
`~/.local/share/osu-tools/library-index/`. If osu! updates its database, the
cache is refreshed. Search time is dominated by loading the existing index,
not by network traffic. `osu scores search ...` is a **different** command
and only searches locally *saved score records*.
