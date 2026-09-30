# Lessons

Concrete mistakes and near-misses from building this, in case they save
someone from repeating them. Ordered roughly by how much damage they could
have caused.

## A fix that stops the error isn't a fix

`osu-fix-video` originally choked on mpeg4/Xvid-coded `.avi` videos — FFmpeg
refused to stream-copy them into FLV, citing spec non-compliance, and
named the exact flag to force it through: `-strict -1`. Adding that flag
made the error go away and the command exit 0.

That was the wrong fix. Actually reading the resulting file back — full
decode, not just `ffprobe`'s summary — showed FFmpeg's own demuxer
detecting **32 phantom streams** in what should have been one, and a
full-decode pass failing outright ("Decode error rate 1 exceeds maximum").
The flag silenced FFmpeg's complaint; it didn't produce a working file.

The actual fix: try the fast stream-copy first (works for the overwhelming
majority of videos, preserves exact quality), and only when that's
*rejected* fall back to a real re-encode into FLV's native codec. Confirmed
clean (single stream, zero decode warnings) before shipping.

**Takeaway: an error message's own suggested flag is a lead, not a
verdict. Read the output file back and verify it, especially for anything
touching media/binary formats where "no crash" and "actually correct" are
very different bars.**

## Verify the whole file after an edit, not just the part you touched

Adding `sync_variants` to `osu-collections` used an existing line
(`def sync_modes(...):`) as an insertion anchor, intending to reproduce
that same line after the new function. The reproduction was silently
dropped. Python didn't catch it: the orphaned function body became
unreachable code after a `return`, at the same indentation — syntactically
valid, semantically gone. It only surfaced when the person tried to run
`sync-modes` directly and got `NameError`.

Fixing that same bug, the same class of mistake happened again immediately
— restoring the `def` line but dropping the next line (`mode_collection =
{...}`) that was supposed to follow it.

**Takeaway: after any edit near existing code, view the complete resulting
function before moving on — don't trust that a "successful" edit tool
call did what was intended. And re-run the full regression suite, not
just a test of the new piece, before calling anything shipped.**

## "Two processes" isn't automatically "duplicate process"

`inotifywait | while read; do ... done` is a shell pipeline. Bash forks a
subshell to run the pipe's consumer side, and that subshell is a literal
fork of the parent — same argv, since fork doesn't change it. Both show up
under `pgrep -f` with identical command lines.

This was misread as "osu launched a second watcher on top of the person's
manual one," which led to building pgrep-based duplicate-prevention logic
for a problem that most likely never existed in the first place. The real
test: `ps -o pid,ppid,cmd -p <pid1>,<pid2>` — if one's PPID is the other's
PID, it's one logical process, not two.

**Takeaway: before diagnosing a "duplicate," check the actual process
tree, not just whether a name appears twice in a listing.**

## grep/pgrep self-matching in test harnesses

A test that inlines its own commands into one large shell invocation can
have its own command-line text match whatever pattern it's searching for
— e.g. `pgrep -f "osu-current"` matching the orchestrating shell's own
`sh -c "...osu-current..."` invocation. This produced a false "duplicate
found" result that took real debugging effort to trace back to the test
itself rather than the code under test.

**Takeaway: write process-matching tests as standalone script files, not
inlined multi-line shell commands, and prefer anchored patterns
(`pattern$`) over loose substring matches.**

## File extension detection needs to anchor to the actual field, not "contains"

`osu-fix-video`'s video-finder originally matched any `Events` line
containing `.ext` for a known video extension, anywhere in the line. A
background/thumbnail image named `Artist - Song.webm_snapshot_00.01.960.png`
matched `.webm` as a substring and was misidentified as the video — on a
map where the actual video line came later in the file, this silently
"used up" the search before the real video was ever reached, reporting "no
video referenced" for a map that had one.

Fixed by requiring the extension to be immediately followed by the closing
quote in a single regex pass, not a coarse line-match followed by a
separate fine-grained extraction.

**Takeaway: never treat "the extension appears somewhere in this string"
as equivalent to "this is a file with that extension." Anchor to where the
filename actually ends.**

## Two small but real gaps from insufficient real-world testing

- The original `osu-fix-video` extension whitelist didn't include `.m4v`
  — a real, existing video on a real map was silently skipped. Whitelist
  now includes `.m4v` and `.webm`.
- Real osu! filenames and paths routinely contain double spaces, periods
  mid-filename, and (in the osu! install path itself) a literal `!`,
  which triggers bash history expansion in interactive shells even inside
  double quotes. `set +H` in `.bashrc` is the durable fix; a backslash
  placed *outside* the quotes works ad hoc.

**Takeaway: test against real filenames, not clean synthetic ones. `!`,
double spaces, and embedded periods are all things osu!'s own ecosystem
produces routinely.**

## Don't silently swallow a subprocess's output

`osu`'s auto-start of `osu-current watch` originally redirected all its
output to `/dev/null`. This meant a carefully-built self-diagnosing error
message (computing the exact `sysctl` fix for an inotify watch-limit
problem) never reached the person when it actually mattered — only when
they ran the command manually in a foreground terminal, which isn't how
`osu`'s auto-start works. Fixed by logging to a file instead of `/dev/null`
and surfacing the log immediately if the subprocess dies within moments of
starting.

**Takeaway: a subprocess started in the background should still have
somewhere for its errors to go. `/dev/null` is rarely the right choice for
anything that can fail.**

## Environment gotchas, not code bugs

- **PEP 668**: Arch/Artix's system Python refuses bare `pip install`.
  `pip install --user --break-system-packages <pkg>` is safe (installs to
  the home directory, never touches anything pacman tracks) for personal
  scripts like these.
- **osu!stable's own corruption patterns are game-level, not
  Wine-specific** — `osu!.db` corruption/rebuild events are reported to
  wipe or hide collections and corrupt `scores.db` on Windows too. No
  source found connecting this to Wine/osu-winello specifically; that
  would be an inference, not a finding.
