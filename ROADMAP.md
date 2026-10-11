# Roadmap: small tools, useful integrations

**Overlay progress (synthetic tests only):** `osu collections sync`, manual converts tag support, exact saved-score `all played`, `osu doctor`, `osu profile`, `osu compare`, and a shared lightweight Python core have first implementations. They are **not** validated on the author's real installation. Items below represent validation or future expansion, not claims that no code exists.

This is a prioritized set of **ideas**, not committed deliverables. Every new tool should answer: Does it remove repeated friction? Is the data trustworthy? What happens offline? How much CPU, RAM, network traffic, and setup does it cost?

## P0 — trust and maintainability

- **Collection sync engine:** one idempotent `osu collections sync` implementing the author's specific inclusion rules. Configurable later; preserve collection order; preview conflicts and converts; verified backup and read-back on apply.
- **Precise `all played`:** start with exact checksums in local scores/replays; optionally add a clearly separate most-played-beatmapsets report.
- **Automated tests:** sanitized synthetic `.db`/`.osr` fixtures; regression coverage for parser versions, mode accuracy, sync precedence, order preservation, and failure handling.
- **Install/health check:** `osu doctor` to check paths, dependencies, watcher limits, Wine process detection, API settings, and current-map freshness. Read-only by default.
- **Lightweight packaging:** user-local installation option, version pinning, lazy imports, no API requests on offline code paths.

## P1 — high-value player tools

- **`osu compare`:** leaderboard plus local best, map/ruleset alignment, sensible API caching and offline error messages. Validate API response variations before release.
- **`osu profile`:** rank/pp and lightweight profile snapshots; clearly distinguish network data from local estimates.
- **`osu score`:** one-command lookup of recent/best local saved scores on a map, filtered by mods and mode, with pp computed on demand. Inspired by bot score commands without needing a bot.
- **`osu map`:** length, BPM changes, AR/OD/CS/HP with mod adjustments, timing points, object counts, and optional links. Avoid recalculating star ratings until asked.
- **`osu search`:** fast local search by artist/title/mapper/BPM/stars using a cache indexed from osu!.db; rebuild when stale.
- **`osu clipboard`:** copy formatted current-map info, pp estimates, or score summaries, only when invoked.

## P2 — mapping and library maintenance

- **`osu timing`:** inspect inherited/uninherited timing points; detect inconsistent BPM/offset segments, with a preview instead of editing automatically. Inspired by timing tools such as ArrowVortex.
- **`osu hitsounds`:** check missing or inconsistent hit-sound samples; report only initially.
- **`osu assets`:** find missing backgrounds/videos/audio, duplicate assets, and oversize videos; propose reversible fixes.
- **`osu collections export/import`:** JSON or CSV previews and a safe bridge for sharing mappings/collection definitions; never overwrite another user's collection database blindly.
- **`osu library audit`:** stale hashes, orphaned files, missing audio, collection inconsistencies, and disk usage, as an on-demand report.
- **`osu discovery --year YEAR`:** **report only** initially: search candidate beatmapsets by year/status and identify which are installed; be clear about the API's search coverage, pagination and rate limits. Downloads would be a separate explicit opt-in feature with a legitimate source and bandwidth limits.

## P3 — optional integrations

- **Live adapter:** read from an optional provider (e.g. tosu) only when live combo/accuracy/clock state is requested. Never require it for simple offline commands.
- **Hotkey interface:** tiny optional keybindings or shell launcher integration, no full GUI necessary.
- **Output modes:** normal terminal output, `--json` for scripts, and compact `--one-line` for overlays or status bars.
- **Small TUI:** optional, only if workflows become too complex for flags; should exit cleanly and stay light on idle resources.

## Optimization rules

Measure before optimizing. Useful benchmarks include cold start, warm start, peak RAM, time scanning 50k+ folders, large `osu!.db` parse time, and API calls per command. Cache parsed index data keyed by source file metadata (with validation), stream large scans when possible, avoid importing `librosa` during unrelated commands, and don't run a permanent service unless a feature demonstrably needs one.

## Not doing by default

- Running an always-on web server, Discord bot, or browser.
- Silently modifying `.osu`, media, or database files.
- Automatically classifying convert difficulties into every supported mode.
- Treating beatmapset-level online history as exact difficulty-level play history.
- Bulk downloading beatmaps without clear source, preview, limits, and user consent.
