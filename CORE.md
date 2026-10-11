# Shared core and performance notes

This overlay introduces the standard-library package `osu_tools/`. No import opens a network connection, reads databases, or runs a background service. Commands import the pieces they need at runtime.

| Module | Owns | Main consideration |
| --- | --- | --- |
| `paths.py` | osu!stable directory/config resolution | `OSU_SONGS` and XDG overrides |
| `binary.py` | Guarded streaming reader and binary writer | Bounds/count validation, exact byte widths |
| `database.py` | osu!.db, collection.db, scores.db | Iterate without reading the whole DB into memory first |
| `policy.py` | Exact-name personal inclusion rules | Prevent accidental merges from naming conventions |
| `collections.py` | Rule application, native-mode, convert handling | In-memory plan, deterministic append, opt-in native cleanup |
| `cache.py` | Reusable human-readable JSON/JSONL index | Fingerprint invalidation; no daemon |
| `library.py` | Timestamped readable CSV/JSONL archive + original DBs | Close game; hash-verifies copied originals |
| `safety.py` | osu! process detection, backup and atomic writes | Verify before/after; abort on conflicts |
| `api.py` | OAuth client credentials, token cache, v2 HTTP calls | Lazy network use, secret permissions |
| `cli.py` | `osu collections`, `osu library`, `osu profile`, `osu compare`, `osu doctor` | Small thin executable wrappers |

**Important:** this is only a first migration. The existing `osu-recent`, `osu-backup`, `osu-pp`, `osu-bpm-offset`, `osu-current`, and `osu-fix-video` remain as in upstream. Their duplicated binary readers and default paths should be migrated **individually**, after automated equivalence tests against representative real-world files. Replacing all of them at once would risk destabilizing proven workflows.

## Performance approach

- Streaming 128 KiB-buffered reads for database scans, bounded strings/counts for malformed inputs.
- No heavyweight audio/pp imports in unrelated commands.
- Avoid permanent local web servers and polling daemons.
- One network client per on-demand online command, cached public OAuth token (mode 0600), otherwise offline.
- One collection sync pass; linear hash-table membership checks rather than repeated nested collection scans.
- Avoid any expensive full-folder census unless `osu doctor --deep` is requested.

**Not benchmarked:** actual peak RSS, cold-start latency, 61k+ beatmapset scan time, and behavior with a live osu!stable/Wine client. Run these measurements before making performance claims.

Tests run with `python3 -m unittest discover -s tests -v`. Synthetic fixtures cover 2025+ Int-Float stars and target-practice score fields, but not every historical database revision or every osu! API response variation.

## Safer synchronization (follow-up fix)

The initial refactor could flood native aggregates because it implicitly
redistributed all root collection entries by native mode. Default sync is
now one-way, with reverse classification opt-in. Additions are attributed
to their source collection or rule, suspicious aggregate members are not
propagated to root, per-collection mismatch notices are consolidated, and
large writes require explicit approval. Source counts are an audit aid,
not proof the proposed changes match the user's personal intentions.

## Personal collection policy update

A later real-world dry-run showed 28,594 unintended additions through `std hdhr`. The corrected version **never infers a synchronization rule from a prefix**. Each variant source must be mapped by exact collection name in `collections.json`. See `COLLECTIONS.md`.

## Readable score/beatmap index and archiving

`cache.py` now uses a normal JSONL+JSON index that doubles as the source material for `osu library snapshot`. `library.py` adds human-friendly CSV exports and verified binary originals. Unlike the superseded SQLite cache, the on-disk index is directly inspectable. See `LIBRARY.md`.
