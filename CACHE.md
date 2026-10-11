# Cache update: readable library index

The previous `~/.cache/osu-tools/library-v1.sqlite3` cache has been replaced by a **readable JSONL index** under `~/.local/share/osu-tools/library-index/` (configurable via `$XDG_DATA_HOME` or `$OSU_LIBRARY_INDEX`). It is the active cache, not merely a separate export.

`osu collections sync` reads the beatmap JSONL and the small played hash list when `osu!.db` and `scores.db` are unchanged. Source file size, inode, path and nanosecond timestamps control invalidation. The program keeps `collection.db` live and never writes into osu!'s files without `--apply`.

To create a **readable, restorable, timestamped archival copy**, run `osu library snapshot` after closing osu!. It includes `beatmaps.csv`, `scores.csv`, `collections.csv`, JSONL index files, and binary-original database files. `--with-replays` additionally copies automatically saved `Data/r/*.osr` replay files. See [LIBRARY.md](LIBRARY.md) and [COLLECTIONS.md](COLLECTIONS.md).

The existing SQLite file isn't automatically deleted; remove it yourself only after verifying the new index works. Previous `--timings`, `--refresh-cache`, and `--no-cache` flags still work. No network connection, background process, or user-credential access is involved.

## Faster database rebuilds (October 2026)

The binary `osu!.db` reader now consumes each star-rating array and timing-point
array in bounded chunks instead of making multiple Python reads per entry. It
still checks rating type markers, array limits, truncation and the database
version before accepting the result. This speeds up a **cold index rebuild**
without changing the readable JSONL format or collection synchronization rules.
Cached JSONL is also read directly into the lookup without an intermediate
full list of dictionaries, reducing peak RAM usage.

To compare on your own installation, run a normal warm sync first, then force
one rebuild while osu! is closed:

```sh
osu collections sync --timings
osu collections sync --timings --refresh-cache
osu collections sync --timings
```

`--refresh-cache` can reprocess the score index too, so compare the separate
`beatmaps` and `scores` timings. These commands are dry runs unless you add
`--apply`; there is no background service or API request.
