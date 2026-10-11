# osu-tools: readable library + explicit collection policy patch

This overlay assumes you have already installed the **safer sync** and **caching** patches from the preceding steps. Do not use this overlay by itself on an older, unmodified clone.

## Why this patch

- The previous implicit prefix rule interpreted `std hdhr` as a variant source and proposed 28,594 unwanted additions to `std all`. This is a **policy bug**, not a cache bug.
- A separate opaque SQLite cache is less useful to you than a readable, inspectable snapshot that is also reused by commands.

## Changes

1. **No implicit variant propagation.** Variants must be mapped by exact name in `~/.config/osu-tools/collections.json`. `std hdhr` is not automatically merged anywhere. Parent aggregates and explicit converts still propagate to root `all`, subject to native-mode checks.
2. **Readable JSON/JSONL cache.** The cache contains beatmap metadata, saved score records and played difficulty checksums; it rebuilds when source files change. `collection.db` continues to be read live.
3. **Timestamped restorable snapshots.** `osu library snapshot` archives the same readable files and verified copies of all three binary databases. `--with-replays` adds `Data/r/*.osr` files.
4. **New commands:** `osu collections policy-init`, `osu collections policy-show`, `osu library status`, `osu library snapshot`, `osu library list`.
5. No silent pruning, no automatic migrations of your original binary databases, and no runtime daemon.

## Upgrade commands

```bash
# In your existing clone (your earlier overlays must already be installed):
unzip -o ~/Downloads/osu-tools-readable-library-patch.zip
python3 -m unittest discover -s tests -v
./install.sh

osu collections policy-init
osu collections policy-show
osu collections sync --timings       # DRY RUN; std hdhr should not show as an origin

# Optional: edit ~/.config/osu-tools/collections.json to opt specific variants into sync.
# Example only, not activated automatically: collections.policy.example.json

# With osu! CLOSED:
osu library snapshot --with-replays  # potentially sizable; without flag = DB files only
```

**Do not use `--apply` until the new preview matches your desired collections.** The synthetic tests passed, but neither your actual database nor a live Wine process was available here.

## Follow-up: converts into their playable mode's `all` and snapshot progress

- Enabled policy-controlled `taiko converts → taiko all → all` (and the other mode equivalents). No automatic guesses about converts; configured convert collections act as explicit exceptions.
- `--prune-mismatches` preserves non-native difficulties that are explicitly tagged in the appropriate convert aggregate.
- Added `convert_into_mode_all` to the version-1 personal policy, defaulting to true; earlier policy files still load.
- The snapshot CLI reports its stages and replay counts, and avoids extra full-file hashing on database/replay copies while retaining a destination read-back verification.
- You can commit these **source files and tests** to GitHub now; do not commit actual private library snapshots or API credentials.

## Publishing-ready follow-up: native standard converts only (2026-10-11)

- Convert tags are restricted to **native osu!standard (mode 0)** maps. `taiko converts`, `ctb converts`, and `mania converts` still flow to their playable-mode `all` and root `all`; they exclude native taiko/catch/mania and unknown hashes.
- Explicit variant → converts rules use the same restriction. Invalid entries stay in manual collections with a concise diagnostic.
- `std converts` is removed from new policy defaults/examples. Old `root_sources` entries remain readable but are ignored with a warning, so existing local policy files continue working.
- Added regression tests for excluded non-standard converts, unresolvable checksums, legacy policy loading and variant filtering.
- Consolidated earlier source overlays with GitHub publishing instructions and a protective `.gitignore`. No database mutation is performed by installation or test runs.
