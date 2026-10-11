# Local saved-score browser

`osu scores` reads **saved local plays** from osu!stable's `scores.db`, using
osu-tools' existing verified, readable `scores-*.jsonl` library index.
No OAuth key, replay parsing, background daemon, network request, or write to an
osu! database is needed. The tool rebuilds only a stale or damaged readable
index. This also works while offline.

## Commands

```sh
osu scores                              # 20 most recently saved scores
osu scores recent --limit 10 --mode taiko
osu scores best --limit 10             # highest raw score, NOT pp
osu scores map ~/path/to/difficulty.osu
osu scores map :current                # same as bare 'map'; heuristic tracker
osu scores map e6d1...32-character-md5
osu scores search 'Kobaryo' --mode mania
osu scores recent --player 'Username' --json
```

Use `--limit 1..100` and optionally `--mode std|taiko|catch|mania`,
`--player NAME`, or `--json`. `--player` is an exact case-insensitive username
match. `search` matches installed map title, artist, or difficulty text,
case-insensitively; it doesn't search online beatmaps. `map` defaults to the
last tracked `.osu` file (`osu-current` is a heuristic, not guaranteed live
state) and also accepts a checksum directly. Both `recent` and `search` operate
on saved score **records**, not unique beatmaps.

The **played ruleset** of the score is used for `--mode`, so a native standard
beatmap played as a taiko convert will match `--mode taiko` when the local score
record says taiko. The score's map label comes from `osu!.db`, independently of
played mode. All dates are UTC. Accuracy is computed from local hit counts for
the recorded ruleset; when hit counts are zero, accuracy is shown as unknown.
The raw score sort is **not** a pp ranking or an online leaderboard.

## Limitations and privacy

- This reflects **only scores actually saved to `scores.db`**. Failed, quit,
  unsaved, or missing imported scores may be absent.
- The readable cache contains private play history. Avoid publishing it to Git
  or sharing `--json` output unless you intend to.
- `scores.db` isn't modified; the score index is verified against the original
  file's metadata, checksummed and rebuilt if damaged. A corrupted original
  database remains an error.
- Online profile and leaderboard lookups remain separate: `osu profile` and
  `osu compare` require API credentials. `osu compare --legacy-only` requests
  only legacy scores from the public osu! API, where supported.

The installed launcher routes `osu scores` directly to `osu-scores`; all
existing launcher subcommands and the prelaunch behavior remain unchanged.
The direct executable is at `~/.local/share/osu-tools/osu-scores`.
