# Cache update: readable library index

The previous `~/.cache/osu-tools/library-v1.sqlite3` cache has been replaced by a **readable JSONL index** under `~/.local/share/osu-tools/library-index/` (configurable via `$XDG_DATA_HOME` or `$OSU_LIBRARY_INDEX`). It is the active cache, not merely a separate export.

`osu collections sync` reads the beatmap JSONL and the small played hash list when `osu!.db` and `scores.db` are unchanged. Source file size, inode, path and nanosecond timestamps control invalidation. The program keeps `collection.db` live and never writes into osu!'s files without `--apply`.

To create a **readable, restorable, timestamped archival copy**, run `osu library snapshot` after closing osu!. It includes `beatmaps.csv`, `scores.csv`, `collections.csv`, JSONL index files, and binary-original database files. `--with-replays` additionally copies automatically saved `Data/r/*.osr` replay files. See [LIBRARY.md](LIBRARY.md) and [COLLECTIONS.md](COLLECTIONS.md).

The existing SQLite file isn't automatically deleted; remove it yourself only after verifying the new index works. Previous `--timings`, `--refresh-cache`, and `--no-cache` flags still work. No network connection, background process, or user-credential access is involved.
