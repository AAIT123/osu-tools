# Collection sync: personal rules, not folders

osu!stable stores **flat** collections. The folder-like tree here describes **your personal inclusion policy**, not an in-game hierarchy. A collection name is **not** automatically a rule; many collections are large search results, manual archives, or intentionally overlapping tags.

## Safe default

`osu collections sync` makes a dry-run plan (no writes). These rules are active by default:

- Existing native aggregates `std all`, `taiko all`, `mania all`, and `ctb` contribute only difficulties **native** to that mode to root `all`.
- Explicitly named `taiko converts`, `mania converts`, and `ctb converts` contribute to **their target mode's aggregate AND root `all`** when named under `root_sources` and `convert_into_mode_all` is true (the default). **Only installed native osu!standard (mode 0) difficulties qualify.** They are user-declared playable-mode classifications, not proof that the converted chart is suitable. Native taiko/catch/mania difficulties and unknown checksums are not propagated as converts. `std converts` is obsolete and ignored.
- `all loved` is filled from installed Loved difficulties; `all played` from exact difficulty hashes with saved local scores in `scores.db` (not unsaved failed/quitted attempts).
- **No variant automatically propagates by prefix.** `std hdhr` does not propagate to `std all` or `all` unless you add an **explicit** policy entry.
- Existing collections are preserved in order. Unknown hashes are not guessed, manual tags are not removed, and conversions are not implicitly classified into native mode aggregates.
- `--from-root`/`sync-modes` is a separate, explicitly requested reverse classification; `--prune-mismatches` is a separate explicit cleanup. Both can be disruptive; preview first.

The installer does not edit your personal `collection.db` unless you use `--apply` with osu! closed. Bulk-change safety limits still apply.

## Configure exact variant sources

```bash
osu collections policy-init
osu collections policy-show
```

`policy-init` creates `~/.config/osu-tools/collections.json` **only if it does not already exist**. It intentionally contains no variant entries. Edit the JSON file to opt in the exact personal tags that should propagate. Example:

```json
{
  "version": 1,
  "variant_sources": {
    "taiko hr": "taiko all",
    "taiko dt": "taiko all",
    "mania ln": "mania all",
    "taiko converts dt": "taiko converts"
  },
  "root_sources": [
    "std all", "taiko all", "mania all", "ctb",
    "taiko converts", "mania converts", "ctb converts"
  ],
  "sync_loved": true,
  "sync_played": true,
  "convert_into_mode_all": true
}
```

`std hdhr` is **absent on purpose**. If it's a broad HDHR search bucket, it remains a separate archive rather than forcing tens of thousands of maps into your curated parent collections. Names not explicitly listed under `variant_sources` are ignored as **sources**, even when they start with `taiko`, `mania`, or `std`.

You can see another sample based on the names in your own dry-run output in [`collections.policy.example.json`](collections.policy.example.json), but it is **not installed or activated automatically**.

### Exact convert behavior

- A **native standard (mode 0)** difficulty under `taiko converts dt` can flow to `taiko converts` (only if that exact source is configured), then to `taiko all` and root `all`. This also works for `ctb converts` → `ctb` and `mania converts` → `mania all`.
- A native taiko difficulty under `taiko hr` can flow to `taiko all`, then `all`. A **native taiko/catch/mania map cannot enter any converts collection via sync**, even when mistakenly tagged there. Existing manual entries are not deleted; they are reported and excluded from propagation.
- A standard difficulty under `taiko hr` stays in that manual tag; sync reports it as non-native and will not guess whether it's a valid taiko convert.
- `--prune-mismatches` **preserves** a native-standard difficulty in `taiko all` when its checksum is intentionally listed in the enabled `taiko converts` aggregate. Other non-native entries can still be removed only after explicit review.
- To keep converts out of target mode aggregates, set `"convert_into_mode_all": false`. Explicit converts still flow to root `all` when included in `root_sources`.
- You can keep a convert in multiple manual tags. The program never deletes or reclassifies them on a normal sync.

## Commands

```bash
osu collections policy-show          # Verify active rules
osu collections sync --timings       # Preview only
osu collections sync --apply         # Only after reviewing, with osu! CLOSED
osu collections sync-all             # Explicit aggregate -> all preview
osu collections sync-variants        # Configured variant propagation preview
osu collections sync-modes           # Explicit reverse classification, not routine
```

You can use `--policy /path/to/collections.json` for testing alternative rules without replacing your defaults. Invalid policy entries cause a clear error instead of silently matching similar names.

**Important:** A correctly cached database does not guarantee the *policy* is what you want. Always review `from configured variant` and `from configured native group` counts before applying.

### Legacy policy migration

The previous generated `~/.config/osu-tools/collections.json` included `"std converts"` under `root_sources`. You do **not** need to recreate your configuration: the reader accepts that old entry but ignores it, reporting a warning. Remove that single string manually when convenient. New policies and `collections.policy.example.json` no longer include it. Do not add `std converts` as a `variant_sources` destination.


## Editing explicit variant rules from the CLI

```bash
osu collections policy-add 'mania ln' 'mania all'
osu collections policy-add 'taiko dr' 'taiko all'
osu collections policy-remove 'mania ln'
osu collections policy-show
```

Rules match **exact collection names**, never prefixes. The commands update
only your private `~/.config/osu-tools/collections.json` atomically; they do not
write to `collection.db`. Preview a sync before enabling automatic applies.
For opt-in pre-launch checks, see [PRELAUNCH.md](PRELAUNCH.md).
