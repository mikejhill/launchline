# Reviewed releases

Python and Rust follow VerdiClip's release-please pattern: conventional commits
update a release pull request, people review the proposed version and changelog,
and merging that PR creates an immutable version tag and draft GitHub release.
The workflow validates the exact merge, builds once, attests and publishes those
artifacts. Only then does it verify assets and make the release public.
Python keeps its universal wheel/sdist and PyPI trusted publishing; Rust keeps its
language-specific packages. GitHub notes and assets are required parts of a release.

## Version and changelog review

`release-please-config.json` pins the Python strategy and
`.release-please-manifest.json` records the reviewed package version. Bootstrap
starts at the published 0.4.1 source, `c76182b`, so installing this process does
not create another version. CI, test, build and documentation changes are hidden
from release notes and do not independently request a release. The changelog
separates shipped 0.4.1 performance and 0.4.0 menu changes from Unreleased.

Dynamic hatch-vcs versioning remains unchanged. Release-please's Python updater
leaves `dynamic = ["version"]` alone; the manifest is the reviewed version record
and immutable tags determine distribution versions. The build sets that version.
`scripts/release_artifacts.py` rejects manifest, changelog, wheel and sdist version
mismatches, then emits the source SHA and package hashes.

Owner pushes to main and a manual `Release` workflow refresh use the same pinned
release-please action as VerdiClip. There is no force-patch publication switch.
Release PRs use `chore: release X.Y.Z` titles and need normal review and CI.
No workflow approves or merges them automatically.

## CI for bot-created PRs

`GITHUB_TOKEN` changes do not trigger ordinary `pull_request` workflow runs.
VerdiClip checks for held runs and dispatches CI as a fallback. LaunchLine uses
that dispatch path directly, without approving a PR or a held workflow run. The
release job verifies the returned PR's repository, branch, open state and main
target, then dispatches `ci.yml` with its head SHA. Every matrix checkout verifies
that SHA before running the full format/lint/type/test/build/package/mutation
checks. If the branch moves before checkout, the check fails; the next
release-please update dispatches the new head.

The approved repository Actions PR-creation setting is enabled. Default token
permissions stay read-only; only release-please receives scoped contents, PR,
issues and actions permissions. No PAT or publisher credential is needed. That
setting does not authorize automation to approve reviews or bypass rules. Verify
an actual dispatched release-PR run before relying on automated checks.

## Build and publish boundaries

Both original actor and rerun initiator must be `mikejhill`, and publication runs
only from main. The created tag must resolve to that exact merge. Read-only
matrix/build jobs check out its SHA with credential persistence disabled.
Publisher jobs consume the same immutable artifact ID, and never check out or
execute repository code. Third-party actions remain pinned to full SHAs.

The build retains wheel, sdist, reviewed notes, `release-manifest.json` and
`SHA256SUMS`. The manifest records the source SHA, version and package hashes.
Provenance covers distributions, manifest and checksums. The GitHub release keeps
release-please's changelog notes and receives the tested distributions, manifest
and checksums. PyPI consumes only `dist/` after build/provenance verification, using
the existing `pypi` reviewer gate and OIDC trusted publisher. Environment, branch
and immutable-tag protections remain in place.

The shared Python/Rust contract stages a draft during the build and registry
publication. Asset byte readback and a final tag check precede making it public.
A failed/pending publish run leaves the draft incomplete. Require the complete
successful workflow and matching registry bytes as the completion signal.

## Failure and retry

Rerun **failed jobs of the original release run**. Completed version/build outputs
preserve its version, SHA and immutable artifact ID. Do not rerun all jobs as a
recovery shortcut: release-please can correctly report no new release after
creating the tag. Investigate failed version/tag jobs before retrying. Never
manufacture a patch bump, move a tag or rebuild different source under that
version to repair publication.

A source or build-tooling defect requires a reviewed fix and a new version.
Preserve the failed immutable tag/draft rather than publishing changed source
under it. This differs from a transport retry of the original tested bytes.

GitHub publication accepts a tag only at the expected commit. It checks all
existing asset hashes before uploading missing files, downloads legacy assets
whose API digest is absent, and rejects different bytes. It never uses
`--clobber`. PyPI preflight accepts a missing version or matching existing hashes,
rejects unknown/different distributions, and fails closed on network/server
errors. Trusted publishing may then skip identical files. Concurrent creation
fails rather than overwriting another upload.

For a package already published to PyPI, run **Repair GitHub release assets** with
its version and original release run ID. `verify-only` defaults to true. The
read-only job downloads `trusted-release` from that run and requires its full
matrix/build/attestation success, matching source tag and main ancestry, package
metadata, PyPI hashes and original signed provenance. It emits a verified repair
artifact. With verification-only disabled, a separate GitHub-only publisher
reuses those bytes, compares existing assets, and completes the draft. It has no
package publishing identity, builds nothing, and never creates or moves tags.
Missing/expired original artifacts or unverifiable provenance are blockers;
do not substitute rebuilt packages. Existing notes are preserved.

## Validation and existing releases

Run `uv run poe check-fast`, then `uv run poe check` and the existing release gate.
CI also runs `scripts/release_artifacts.py --check-build` on the real uv output.
Only the wheel, sdist and uv's known `*`-only `.gitignore` sidecar are accepted;
the sidecar is excluded from release hashes. Unknown files, malformed markers,
directories, symlinks and mismatched package metadata still fail closed.
Offline tests execute the actual publisher shell with intercepted GitHub calls
and real jq queries: ancestry/tag conflicts, complete/partial retry, asset hash
conflicts and legacy download failures. Other tests cover reviewed versions,
changelog sections, archive metadata, source SHA, checksums and PyPI HTTP errors.

The October 25 audit found GitHub distributions for every Python release v0.1.0
through v0.4.1. No backfill, retagging or republication is needed. v0.4.1 matches
PyPI bytes and `c76182b`, has verified attestations, and passed 17 installed-wheel
terminal workflows. Older releases are preserved, including v0.1.0's extra asset.

Old go-semantic-release fixture scripts remain historical tools; production no
longer calls them.

References: [token event behavior](https://github.com/googleapis/release-please-action#other-actions-on-release-please-prs),
[manifest bootstrap](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md#bootstrapping),
[dynamic Python updater](https://github.com/googleapis/release-please/blob/main/src/updaters/python/pyproject-toml.ts).
