# osu-tools

A set of small, offline CLI tools for osu!stable running under osu-winello
on Linux. Built to avoid three things: tosu/memory-reading, browser
extensions, and Discord bots — everything here reads osu!'s own local files
directly instead.

Read `ARCHITECTURE.md` before changing anything structural, and
`LESSONS.md` before trusting a fix that "looks right." Both exist because
this project has already been burned by shortcuts once each.

## Install

```bash
sudo cp osu /usr/local/bin/osu
sudo chmod +x /usr/local/bin/osu
mkdir -p ~/.local/share/osu-tools
cp osu-current osu-fix-video osu-bpm-offset osu-pp osu-recent osu-collections osu-backup ~/.local/share/osu-tools/
chmod +x ~/.local/share/osu-tools/*
```

`osu` is a git-style dispatcher: `osu <name> [args]` runs
`~/.local/share/osu-tools/osu-<name>`. Bare `osu` (no args) launches the
game and auto-starts the map tracker.

Dependencies: `inotify-tools` (pacman), `ffmpeg`, and for the Python tools,
`pip install --user --break-system-packages rosu-pp-py librosa numpy soundfile`
(Arch/Artix's system Python is externally managed — see LESSONS.md).

## Tools

| Command | What it does | Needs |
|---|---|---|
| `osu` | Launches the game; bare invocation also starts the map tracker | — |
| `osu current [watch\|get\|folder]` | Tracks which exact `.osu` difficulty is currently open, via inotify — no tosu | `inotify-tools` |
| `osu fix-video [-c\|-a\|-s <pat>\|--force]` | Fixes the osu!stable video-freeze bug (issue #1197) by remuxing to FLV, with a re-encode fallback for codecs FLV can't carry unchanged | `ffmpeg`, `osu-current` running |
| `osu bpm-offset [--current]` | Beat-detection BPM/offset estimate from the audio file | `librosa` |
| `osu pp [file] [--mode] [--mods] [--acc]` | Local pp calculator (rosu-pp) for the current or a given map, all 4 modes | `rosu-pp-py` |
| `osu recent [--list]` | Your last local replay on the current map: real judgements and pp, all 4 modes, reads both `Replays/` and `Data/r` | `rosu-pp-py` |
| `osu collections [show <name>\|sync-loved\|sync-modes\|sync-variants] [--apply]` | Diagnoses and (with `--apply`) repairs collection.db against rules you define | — |
| `osu backup [--list\|--with-osudb\|--rebuild-scores]` | Verified, incremental backups of collection.db/scores.db/Data/r | — |

Everything defaults to **dry-run** where it writes anything at all
(`osu-collections`, `osu-backup --rebuild-scores`). Nothing touches a real
file without an explicit `--apply` or `--yes`/an interactive confirmation.

## Not built yet

Two tools are blocked on the osu! API (a free OAuth client, not the same
thing as tosu/a browser extension/a Discord bot — see the end of this
conversation's history for why that distinction mattered to the person who
commissioned this):

- `osu-profile` — real rank/pp/stats, can't be derived locally
- `osu-compare` — a map's real leaderboard

Also parked, same blocker: an `all new` collection-sync rule that needs to
resolve bare MD5 hashes back to beatmap identity, which is either an osu!
API lookup or the original `.osdb` file (from Piotrekol's Collection
Manager) if it still exists somewhere — `.osdb` carries map IDs directly,
`.db`/`collection.db` only ever stores hashes.
