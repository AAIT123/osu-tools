# Publishing osu-tools to your GitHub repo

**Publishing can happen now.** This is a development release, not a claim that every feature is complete. The 44 automated synthetic tests pass, and the user has already confirmed that the prior 36-test build ran, produced a conservative sync preview and completed a real readable snapshot on Artix/Wine. The latest native-standard-only convert restriction has not yet been run against their own real library.

## 1. Review the existing checkout

In the checkout of `https://github.com/AAIT123/osu-tools`, run:

```bash
git status --short
git remote -v
```

Do not discard other work or use `git reset --hard` to start clean.

## 2. Install the consolidated overlay

```bash
unzip -o ~/Downloads/osu-tools-publish-ready.zip
# Only if the original ARCHITECTURE.md still uses the old 'Why no tosu' heading:
if grep -q '^## Why no tosu' ARCHITECTURE.md; then
    git apply ARCHITECTURE-philosophy.patch
fi
python3 -m unittest discover -s tests -v
./install.sh
osu doctor
osu collections policy-show
osu collections sync --timings  # preview; do not apply during publishing
```

Use `git diff` to review changes. Especially verify `std hdhr` does **not** appear as a propagation source, and no non-standard difficulty is being propagated as a convert. Your personal `collections.json` is outside the repo and will keep the legacy `std converts` entry until you edit it.

## 3. Stage source only, then push

```bash
git add -- .gitignore .github/workflows/tests.yml   README.md ARCHITECTURE.md COLLECTIONS.md CORE.md CACHE.md LIBRARY.md   INTEGRATION.md PATCH_NOTES.md ROADMAP.md PUBLISHING.md   collections.policy.example.json install.sh   osu-collections osu-library osu-profile osu-compare osu-doctor   osu_tools/ tests/
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Check that **no** `.db`, replay, snapshot, personal API credential or cache export is staged. If everything is appropriate:

```bash
git commit -m "Centralize osu-tools with policy-based collection sync and readable snapshots"
git push origin HEAD
```

That pushes the **current local branch** to its configured upstream if one exists. If it doesn't, prefer explicitly pushing to a chosen branch, e.g. `git push -u origin HEAD:main`, after confirming `main` is really the desired branch and you have permission. Never force-push to resolve a conflict. A pull request is preferable if you want a review before merging.

The file `ARCHITECTURE-philosophy.patch` is a local patch helper and is **not** in the staging list. It can be removed after applying. This ZIP does not contain Git credentials and does not push on its own.

## 4. Possible follow-up before tagging a release

- Verify the new convert constraints against real taiko/catch/mania-tagged standard maps.
- Verify at least one authenticated profile and leaderboard query.
- Decide on a project license and add an appropriate `LICENSE` file if you want reuse and contributions.
- Keep testing performance: initial `osu!.db` parse took ~34.7 s in one large Artix library; repeat syncs should reuse the readable cache when the source database has not changed.
