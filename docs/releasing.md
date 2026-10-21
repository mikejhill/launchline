# Releasing

Releases run automatically after the owner merges trusted changes into `main`.
Conventional commit messages determine the next version. A push with no
releasable commits does not publish a version.

The workflow checks out the exact merge SHA, runs reusable read-only CI and
builds the package without publishing credentials. Separate jobs publish that
same run's immutable artifact ID to GitHub and PyPI. The PyPI job uses the
existing `pypi` environment and trusted publishing, with no package API token.

The GitHub publisher verifies that the merge remains on `main`, creates the
version tag atomically at that SHA and refuses a conflicting tag. Version-tag
update/deletion protection must be active before deploying this workflow.
Publisher jobs do not check out or execute repository code. Both the original
actor and any rerun initiator must be `mikejhill`.

For a deliberate patch release without a conventional fix/feature commit, run
**Actions → Release → Run workflow** on `main` as the owner and select
`force-patch`. This remains a publication action, not a dry run.

Before removing the existing production environment's reviewer, verify its
main-only branch restriction and the PyPI trusted-publisher identity:
repository `mikejhill/launchline`, workflow `release.yml`, environment `pypi`.
The workflow change does not itself remove that approval gate.

If publication partially fails, rerun its failed jobs on the original run.
PyPI publication skips an already uploaded distribution; existing tags must
still match the original commit. Do not move a published tag to retry a release.
