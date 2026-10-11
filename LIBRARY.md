# Human-readable library snapshots and local-score history

The **readable index** is also what makes subsequent collection syncs faster. It is not a SQLite database: it is normal UTF-8 JSON/JSONL under:

`~/.local/share/osu-tools/library-index/` (or `$XDG_DATA_HOME/osu-tools/library-index/`).

Index contents:

- `manifest.json` — source-file fingerprints and checksums for index files
- `beatmaps-<id>.jsonl` — one beatmap per line, with title, difficulty, checksum, native mode, rank status, beatmap and set IDs
- `scores-<id>.jsonl` — one local saved score per line with player, beatmap checksum, score, mods bitmask, hits, combo and timestamp; **not** replay frame data
- `played-<id>.json` — sorted beatmap checksums with saved local scores (fast `all played` source)

All files can be opened with a text editor or `jq`. `osu collections sync` reads the JSONL beatmap index and small played list directly when the corresponding source is unchanged; when source fingerprint changes, the affected index is regenerated. A corrupt index is rebuilt from the original osu! database. There is no background service and no persistent process.

## A real snapshot, not just a disposable index

**Close osu!** and run:

```bash
osu library snapshot
osu library list
```

That archives the same readable data, **human-friendly `beatmaps.csv`, `scores.csv`, and `collections.csv`**, plus `collections.json` and verified byte-for-byte originals of `osu!.db`, `collection.db`, and `scores.db`, in a unique dated folder under `~/.local/share/osu-tools/snapshots/`. The `originals/*.db` files are what make the archive genuinely restorable. JSONL is not reversible to osu!'s original binary structure on its own.

To preserve automatically saved replay files too:

```bash
osu library snapshot --with-replays
```

This can take significant space and time for large `Data/r` directories, and each archived snapshot copies those replays again. Use it selectively; a standard snapshot already includes your local score metadata and exact `scores.db`. The snapshot command now prints the current stage and periodically prints replay counts/bytes copied; source files are hashed while they are copied, then the destination is verified once. There is no background transfer or async task. It backs up `.osr` files; `.osg` files are not included. Exported replays under `Replays/` are **not** included by this command. The existing `osu backup` tool remains available for its own backup workflow. Back up any additional important user files separately.

`osu library snapshot --index-only` archives only the readable exports; it **cannot** be used as a complete binary restore. This can run without the game-closed check, but database fingerprints must remain stable during creation.

Snapshots are **never silently deleted or overwritten**. Keep an eye on their size. Existing old SQLite cache files under `~/.cache/osu-tools/` can be removed manually after you verify the new index is working; the patch doesn't delete them automatically.

## Examples

```bash
osu library status
osu collections sync --timings
jq -r '.artist + " - " + .title + " [" + .difficulty + "]"' ~/.local/share/osu-tools/library-index/beatmaps-*.jsonl | head
jq -r 'select(.nmiss == 0) | .map_md5' ~/.local/share/osu-tools/library-index/scores-*.jsonl | head
```

*Privacy:* score exports contain player names and play history. Keep the index and snapshot folders private; do not attach your snapshot to public GitHub issues. The tools create these files under user-private directories and mark generated files `0600`.

## Limitations

- The readable score index represents only scores actually saved in `scores.db`. Unsaved failed attempts, recent online-only plays, and replay frames are not present.
- The first run (or a source change) still parses the original binary database. JSONL is chosen for readability and simplicity; it may not be the fastest possible indexing format for enormous libraries.
- These paths and native-mode rules target **osu!stable under Wine**. Real-world parsing must be validated on your installation, not just synthetic tests.

## When snapshots are slow

A **new** readable index must parse both `osu!.db` and `scores.db` once. You can warm that cache with `osu collections sync --timings`; unchanged sources are reused on subsequent runs. A full snapshot then exports CSV files and copies the three original game databases. `--with-replays` is significantly slower because it copies and verifies every saved `.osr` file.

If you only need searchable/readable records, the normal on-disk index already exists at `osu library status` and is refreshed by collection sync. Use `osu library snapshot --index-only` for a smaller archived export, with the explicit limitation that it is **not restorable**.

To check snapshot disk usage while a snapshot runs:

```bash
du -sh ~/.local/share/osu-tools/snapshots
du -sh ~/.local/share/osu-wine/osu!/Data/r
```

Do not publish these private snapshots to GitHub.
