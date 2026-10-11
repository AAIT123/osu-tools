# Integrating the consolidated osu-tools source overlay

This release ZIP contains **source files**, not your personal osu! libraries. Apply it **inside the existing git checkout** of `AAIT123/osu-tools`, which already has the original launcher, `osu-backup`, `osu-current`, `osu-recent`, `osu-pp`, and mapping scripts. It consolidates all earlier refactor/cache/safety fixes: do not re-extract the older ZIPs afterward.

```bash
cd /path/to/your/osu-tools  # directory with .git/ and osu
unzip -o ~/Downloads/osu-tools-publish-ready.zip
python3 -m unittest discover -s tests -v
./install.sh
osu collections policy-show
osu collections sync --timings    # dry run; no writes
```

**Your saved personal policy is not replaced.** The old `"std converts"` entry is accepted for backward compatibility, but ignored with a warning. You can remove that entry from `~/.config/osu-tools/collections.json` manually. No automatic name-prefix classification: `std hdhr` stays excluded unless explicitly configured. Only native standard difficulties can propagate from `taiko/ctb/mania converts`, always preserving manual membership.

Your current library snapshot at `~/.local/share/osu-tools/snapshots/` remains untouched. Never commit real `.db` files, snapshots, `.osr` replays, readable user indexes, `collections.json` or osu! API credentials. The new `.gitignore` helps but does not protect previously tracked files—inspect the staged diff.

To improve the original architecture rationale, the ZIP includes `ARCHITECTURE-philosophy.patch`. Apply it **only if** your `ARCHITECTURE.md` still starts with `## Why no tosu`:

```bash
if grep -q '^## Why no tosu' ARCHITECTURE.md; then
    git apply ARCHITECTURE-philosophy.patch
fi
```

See `PUBLISHING.md` for safe GitHub publishing steps. `osu library snapshot` only creates local archives; it is unrelated to `git push`.
