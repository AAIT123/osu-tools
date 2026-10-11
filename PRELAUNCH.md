# Pre-launch collection synchronization

**Optional and off by default.** On Artix/Linux there is no resident daemon or
systemd dependency. The installer puts a tiny hook into the **installed copy**
of the existing `osu` Bash launcher; it executes only when launching with plain
`osu` (zero arguments). It leaves normal subcommands and the checked-in launcher
unchanged. Re-running `./install.sh` regenerates the hook from the original.

The hook skips Python entirely until prelaunch is enabled. When enabled it
checks `osu!.db`, `scores.db`, `collection.db`, and the personal collections
policy using cheap file metadata. It runs on changed sources or after the
configured interval (default 24 hours). A successful run records the **post-apply**
file identities and timestamps; later unchanged launches return immediately.

## Try preview mode first

```bash
./install.sh
osu prelaunch enable --preview
osu prelaunch status
osu prelaunch run --force-check
cat ~/.cache/osu-tools/prelaunch.log
osu                  # next normal game launch performs the due check first
```

If the original launcher does not recognize the `prelaunch` subcommand, invoke
`~/.local/share/osu-tools/osu-prelaunch` directly with the same arguments.

After reviewing the collection preview and ensuring the policy reflects your
intent, **explicitly opt into writes**:

```bash
osu prelaunch enable --apply --max-additions 100
```

The automatic apply:

- will only run with osu! closed, before Wine launches the game;
- uses the same verified pre-write backup and atomic replacement as manual sync;
- never uses `--force`, `--allow-large`, `--create-missing`, `--from-root`,
  `--prune-mismatches` or any implicit variant inheritance;
- refuses automatic writes over 100 added memberships by default and **zero
  removals**; review large changes and apply them manually;
- logs the last report privately in `~/.cache/osu-tools/prelaunch.log`;
- never prevents the game from launching when an update fails; the next launch
  may retry if an error prevented a successful sync.

To disable or bypass:

```bash
osu prelaunch disable
OSU_TOOLS_SKIP_PRELAUNCH=1 osu    # bypass once, without changing settings
osu prelaunch status
```

The default 24-hour interval is a **maximum age**, not a minimum delay:
changes to scores, beatmaps, collections or policy trigger a check at the next
launch regardless of interval. To set the maximum age to 6 hours:

```bash
osu prelaunch enable --preview --interval-hours 6
# Or opt in to guarded writes explicitly:
osu prelaunch enable --apply --interval-hours 6 --max-additions 100
```

Optional periodic checks without a background daemon: if you already use cron
on Artix, add the following line to your user's crontab with `crontab -e`:

```cron
0 */6 * * * "$HOME/.local/share/osu-tools/osu-prelaunch" run
```

That reuses exactly the same lock, change detector and configuration. It skips
when the game is already running. Do **not** schedule `osu collections sync
--apply` directly, because it bypasses the prelaunch interval/lock.

## Backups and cache

Prelaunch refreshes the active readable index when source files change. An
actual collection edit creates a **verified `collection.db.bak.*`** before
writing. It does not create a complete archived library snapshot or copy
replays on every launch—those are expensive and would slow startup. Keep using
`osu library snapshot` occasionally with the game closed for restorable snapshots.

The JSON config lives at `~/.config/osu-tools/prelaunch.json` (mode 0600); the
last success fingerprint, lock and private report live in
`~/.cache/osu-tools/`. The check does not connect to the internet.
