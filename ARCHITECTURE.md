# Architecture

## Why no tosu

tosu (or gosumemory) reads osu!'s live process memory and is the normal way
to get "what map is currently open" on Linux. It was deliberately avoided
here — the person wanted this to not depend on a memory reader, a browser
extension, or a Discord bot. Everything in this repo reads files osu!
already writes to disk instead.

## How "current map" tracking actually works (`osu-current`)

`inotifywait -mrq -e open` on the whole `Songs/` folder. osu! reads a
difficulty's `.osu` file whenever you enter Play or the editor on it, so
"the most recently opened `.osu` file" is a solid proxy for "the exact
difficulty I'm on right now" — not just the beatmapset folder, the specific
file. That distinction matters: `osu-pp`/`osu-recent` need the exact
difficulty (different diffs have wildly different star ratings), while
`osu-fix-video`/`osu-bpm-offset` only need the containing folder, which
they get via `dirname` on the tracked path.

**Recursive inotify watches cost one kernel watch per folder.** A large
Songs library (tested against 61k+ folders in production) can exceed
`fs.inotify.max_user_watches` before the watch even starts. `osu-current
watch` checks the actual folder count against the actual current limit
*before* calling `inotifywait`, and prints the exact `sysctl` command to
fix it if needed, rather than failing with the kernel's own       cryptic
`ENOSPC`.

**Multiple OS processes for one logical watcher is normal, not a bug.**
`inotifywait | while read; do ... done` is a shell pipeline, and bash forks
a subshell for the pipe's consumer side. Both the parent and that subshell
show up under `pgrep` with identical command lines (fork doesn't change
argv). Confirm with `ps -o pid,ppid,cmd -p <pid1>,<pid2>` — if one's PPID
is the other's PID, it's one watcher, not two. This was misdiagnosed once
in this project's history; see LESSONS.md.

## Binary file formats (`osu-collections`, `osu-backup`, `osu-recent`)

`osu!.db`, `collection.db`, `scores.db`, and `.osr` replay files are all
implemented directly from
https://github.com/ppy/osu/wiki/Legacy-database-file-structure and
https://osu.ppy.sh/wiki/osu!_File_Formats/Osr_(file_format) — no
third-party library. Cross-validated against three independent
reimplementations (Piotrekol/CollectionManager's own README cites the same
wiki page; kovaxis/osu-db in Rust and holly-hacker/osu-database-reader in
C# target the same layout).

The osu!.db format is version-gated: star-rating pairs are Int-Double
before revision 20250107 and Int-Float from then on. Anyone's real client
in 2026 is well past that boundary, but the reader still branches on it
correctly.

**Every parser was validated by round-tripping a synthetic fixture built
with a matching `Writer` class**, checking for zero leftover bytes after
parsing — not just "doesn't throw." A field-width mistake almost always
either throws mid-parse or leaves trailing bytes; a clean round-trip with
neither is strong (not absolute) evidence the layout is right. Do this for
any new binary format work here rather than trusting the spec alone.

## Safety pattern for anything that writes to osu!'s own files

`osu-collections sync-* --apply` and `osu-backup` are the only things here
that touch `collection.db`/`scores.db` directly. Both follow the same
pattern, and any future write-capable tool should too:

1. **Dry-run by default.** Compute and print exactly what would change;
   require an explicit `--apply` to actually write anything.
2. **Refuse while osu! looks running**, checking `/proc/*/comm` and
   `/proc/*/cmdline` for `osu!.exe`. The game can hold its own in-memory
   copy of these files and silently overwrite a change on exit. `--force`
   overrides, for when the detection is wrong.
3. **Backup before write, verified, never overwritten.** Copy the
   original, hash-verify the copy, only then write. Backup filenames
   disambiguate on collision (matters if multiple `--apply` calls run
   within the same second — timestamps alone aren't unique enough).
4. **Atomic write.** Write to a temp path, then `os.replace`/`mv` over the
   real file, so a crash mid-write can't leave a half-written file in
   place of a working one.

## pp/difficulty calculation (`osu-pp`, `osu-recent`)

`rosu-pp-py` (pip), not a hand-rolled difficulty algorithm — that's a
genuinely hard problem or expertise to have and re-implementing it wasn't
in scope. Confirmed empirically (not just from docs) that:
- it accepts either a legacy mod bitmask int or an acronym string, and
  both produce identical pp for the same mods
- `Performance.calculate()` accepts a previous result in place of a
  `Beatmap` to reuse difficulty attributes across repeated calls at
  different accuracies (used for `osu-pp`'s default accuracy-spread
  output, avoids recomputing difficulty 5 times)
- `Beatmap.convert(mode, mods)` handles cross-mode conversion (e.g. a std
  map played as taiko), including mania's key-count mod (`"6K"` etc.)

Per-mode accuracy formulas (`osu-recent`) are from
https://osu.ppy.sh/wiki/Accuracy — taiko, catch and mania each use
different judgement types and weights from std; see that page before
touching `analyze_judgements()`.

## Replay discovery (`osu-recent`)

Two folders, different purposes:
- `Replays/` — replays the person explicitly exported (F2 on the results
  screen)
- `Data/r` — the replay behind *every passed local score*, named
  `<beatmap md5>-<time>.osr`, with a same-named `.osg` spectator-data
  companion that must be skipped, not parsed as a replay

**Data/r only ever contains passes.** A failed or quit attempt never lands
there, so "most recent play" from this folder means "most recent pass,"
which matters when `osu-recent` reports pp for what it found — there is no
way to surface a fail from this folder.

File names in `Data/r` cannot be trusted to describe file contents
(confirmed by testing against a deliberately mismatched filename) — the
beatmap hash is read from inside the file's own header, never taken from
the filename.
