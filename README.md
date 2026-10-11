# osu-tools

Fast CLI utilities for **osu!stable on Linux/Wine**, designed around a lower-end computer and a personal gameplay/mapping workflow. The goal isn't to reject browsers, Discord bots, overlays or tosu: it's to avoid loading one for a small task when a local command can answer it. Online integrations are useful when local data cannot provide the answer.

**Project status:** Development version. The shared Python core centralizes collection and score parsing, readable index/snapshots, safety checks and optional public API access. Automated synthetic tests pass; the collection sync and readable snapshot have also been run successfully on an Artix/Wine installation. Native-standard-only convert filtering and authenticated API responses still need validation on additional real libraries. Review dry runs before any write.

## Install / upgrade

From an existing clone of the original repo, unpack the overlay over the top (see `INTEGRATION.md`), then:

```bash
bash install.sh
osu doctor
osu collections sync               # dry run, never writes
# Review per-source counts and check for unexpected bulk additions first.
# Close osu! before applying small, intentional changes:
osu collections sync --apply       # guarded at 1000 additions / 100 removals
# Optional: move known wrong-native hashes OUT of native aggregates:
osu collections sync --prune-mismatches        # inspect removals
osu collections sync --prune-mismatches --apply # with osu! closed
```

The installer places scripts and `osu_tools/` in `~/.local/share/osu-tools`, and `osu` in `~/.local/bin` without sudo. Set `OSU_TOOLS_DIR`, `OSU_BIN_DIR`, `OSU_SONGS`, `OSU_LAUNCH_CMD` as needed. Python **3.11+** is required for the refactored commands. The original optional requirements remain (`inotify-tools`, `ffmpeg`, `rosu-pp-py`, `librosa`, etc. per command).

## Commands

| Command | Description | Source |
| --- | --- | --- |
| `osu` | Launch osu! and start last-opened-map tracker | Existing Wine launcher |
| `osu current` | Last opened `.osu` file (heuristic, not guaranteed live state) | inotify |
| `osu pp` | Local pp / difficulty calculation | rosu-pp-py |
| `osu recent` | Last saved replay / pp | local replay files |
| **`osu scores [recent|best|map|search]`** | Offline saved-score lookup, per-mode accuracy and JSON output | local `scores.db` + readable cache |
| `osu fix-video` | Video compatibility workaround | ffmpeg |
| `osu bpm-offset` | Audio timing estimate | librosa |
| `osu backup` | Verified backups of game data | osu! databases |
| **`osu library snapshot [--with-replays]`** | Readable JSONL library and local scores, with exact original database copies | local files |
| `osu library list` | List retained archival snapshots | local files |
| `osu collections policy-init` / `policy-show` / `policy-add` / `policy-remove` | Manage exact variant-to-aggregate rules without name guessing | JSON configuration |
| **`osu prelaunch enable --preview`** | Opt into a cheap file-change check before launching the game | local files |
| **`osu collections sync`** | Order-preserving sync with explicit policy rules (dry-run default) | local osu!.db, collection.db, scores.db |
| `osu collections sync-variants` | Only policy-listed variant propagation (including converts) | local collections |
| `osu collections sync-modes` | Explicitly classify root `all` entries by the *difficulty's native mode* (potentially many additions) | local osu!.db |
| `osu collections sync-all` | Mode aggregates (and explicit converts) up to root `all` | local collections |
| `osu collections sync-loved` | Add locally known Loved difficulties to `all loved` | local osu!.db |
| `osu collections sync-played` | Add exactly identified saved local-score difficulties to `all played` | local scores.db |
| `osu collections show NAME` | Show members of matching collection(s) | local DB |
| **`osu profile [USER] [--mode std]`** | Public pp/rank/profile information | osu! API (opt-in) |
| **`osu compare [MAP.osu] [--top N] [--legacy-only]`** | Online beatmap leaderboard and your online score (optional legacy-only filter) | osu! API (opt-in) |
| **`osu doctor [--deep]`** | Lightweight path/dependency/config diagnostic | local system |

**Database edits are dry-run by default**, require `--apply`, refuse to write if osu! appears to be running, verify a uniquely named backup and atomically replace the original. A bulk-change guard blocks applies exceeding 1,000 additions or 100 removals unless explicitly approved with `--allow-large` (or thresholds adjusted). `--force` overrides the process check but is **unsafe**. Old tools such as `osu fix-video` have their own safety behavior; these new guarantees refer specifically to the refactored `osu collections` commands.

## Your collection scheme

This project originally encoded **one person's collection naming habits**, not a universal osu! hierarchy. osu!stable has *flat collections*, not actual nested folders. The hierarchy below is a logical inclusion policy:

```text
all
├── std all        ← ONLY explicitly configured std variant sources
├── taiko all      ← ONLY explicitly configured taiko variant sources
├── mania all      ← ONLY explicitly configured mania variant sources
└── ctb            ← ONLY explicitly configured catch variant sources

all loved
all played
all new  (reserved; discovery-by-year workflow not yet built)

# Explicit cross-mode tags (native osu!standard maps ONLY):
taiko converts       ← standard difficulties played as taiko
mania converts       ← standard difficulties played as mania
ctb converts         ← standard difficulties played as catch
# There is no 'std converts'; native taiko/catch/mania cannot become converts.
```

Example: a **native standard** difficulty tagged in `taiko converts` remains native standard, but the default sync adds it to **`taiko all` and root `all`** because you explicitly identified it as a taiko convert. A native taiko/catch/mania difficulty in a converts collection is left there as a manual tag but **never propagated through that convert rule**; unknown checksums are also excluded. An obsolete `std converts` entry in an existing policy is ignored with a warning. It does not implicitly add it to `std all`; `--from-root` can perform that reverse native classification explicitly. `--prune-mismatches` protects these intentional convert exceptions while still warning about unrelated non-native members of native aggregates. A standard map in a separately configured `taiko hd` variant is *reported*, never guessed to be a convert. The default never redistributes every root member into mode aggregates, and it never infers rules from a collection name like `std hdhr`. Unknown checksums and manually tagged collections are preserved. This behavior is configurable via `convert_into_mode_all` and `root_sources` in the policy; the program doesn't write osu!'s files unless you explicitly use `--apply` with the game closed.

`all played` uses **saved scores from `scores.db`**, not the API's most-played *beatmapsets* (which cannot identify the exact difficulty played). Failures/quits and scores not saved locally may be absent. `all new` remains reserved: discovery/download-by-year needs a separate design, not a collection checksum rule.

See [COLLECTIONS.md](COLLECTIONS.md) for exact sync semantics.

## Opt-in API setup

The public profile and leaderboard tools use a client-credentials OAuth application: [osu! account settings](https://osu.ppy.sh/home/account/edit), OAuth section. Place credentials in `~/.config/osu-tools/api.conf`:

```ini
client_id = YOUR_ID
client_secret = YOUR_SECRET
```

Then run `chmod 600 ~/.config/osu-tools/api.conf`. Alternatively use environment variables `OSU_API_CLIENT_ID`, `OSU_API_CLIENT_SECRET`. Token caching is on disk with restricted permissions, and API calls happen **only** when an online command is used. No secret belongs in Git.

## Readable library and explicit sync policy

`osu collections sync` no longer guesses variant inheritance from prefixes. `std hdhr` is **not** a sync source unless you opt it in under `variant_sources` in your personal `~/.config/osu-tools/collections.json` policy. Other native-mode aggregates can still flow to root `all`, with mode checks. Create/review the default policy using:

```bash
osu collections policy-init
osu collections policy-show
osu collections sync --timings      # dry-run; review source breakdown
```

The active read-only index is now human-readable JSON/JSONL under `~/.local/share/osu-tools/library-index/`. It stores **beatmap metadata and saved local score details** and is reused as a cache on later runs; archival snapshots also include readable CSV views. On demand, and with osu! **closed**, archive these readable files along with byte-exact originals that can be restored:

```bash
osu library snapshot               # original .db files + readable exports
osu library snapshot --with-replays # additionally back up Data/r/*.osr
osu library list
```

Read [COLLECTIONS.md](COLLECTIONS.md) for the exact personal policy and convert behavior, and [LIBRARY.md](LIBRARY.md) for export, cache invalidation and restore limitations. The original binary files are essential for exact recovery; JSON exports alone aren't reversible into all osu!stable database fields.

## Pre-launch sync and explicit collection policy editing

Optional pre-launch checks are **disabled by default**. After installing, use
`osu prelaunch enable --preview` to first produce a report when invoking plain
`osu` (game launch). After reviewing it, `osu prelaunch enable --apply` opts
into guarded automatic writes, capped at **100 additions / zero removals** per
run by default. Changing beatmaps, saved scores, collections, or policy causes
a new check; unchanged files are skipped until the 24-hour interval is due.
There is no daemon, and a failed sync never prevents the game from starting.
You can bypass once with `OSU_TOOLS_SKIP_PRELAUNCH=1 osu`.

You can add or remove **specific variant** rules without hand-editing JSON:

```bash
osu collections policy-add 'taiko dr' 'taiko all'
osu collections policy-remove 'taiko dr'
osu collections policy-show
```

No `std hdhr` rule is created unless you explicitly add it. See
[PRELAUNCH.md](PRELAUNCH.md) for interval, safety, optional cron and log details.

## Optimization direction

The refactor centralizes DB readers, config paths, safe writes, collection rules and API transport in the tiny standard-library `osu_tools/` package. The original pp, recent, video, backup, current tracker and BPM scripts remain separate and unchanged in this overlay, avoiding untested rewrites. Follow-up work should migrate their duplicated readers and checks incrementally **with tests**. More features are outlined in [ROADMAP.md](ROADMAP.md); measuring cold-start, large-library memory and actual runtime is more useful than guessing optimizations.

## Tests and feedback

```bash
python3 -m unittest discover -s tests -v
```

Tests generate synthetic `.db` files; they do **not** use your files or credentials. See [CORE.md](CORE.md) and [INTEGRATION.md](INTEGRATION.md). When filing an issue, remove usernames, private scores, token files, and other sensitive information before sharing logs.

## Saved local score browsing

`osu scores` shows the latest saved local plays, `osu scores best` ranks by **raw score** (not pp), `osu scores map :current` filters the last tracked difficulty, and `osu scores search 'artist or title'` finds saved scores for installed maps. The `--mode` filter uses the played ruleset (including standard converts), and `--json` produces machine-readable results. See [SCORES.md](SCORES.md).
