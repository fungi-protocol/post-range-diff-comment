# post-range-diff-comment

A GitHub Action that reacts to a force push on a pull request by posting
`git range-diff` of the old and new series as a collapsed comment.

GitHub's "force-pushed, Compare" link diffs the two trees, which says nothing
about how the *commits* changed. `git range-diff` compares the two series
patch by patch: which commits are unchanged, which were reworded or amended
(and how), which were dropped or added. This action puts that output where
review happens, one collapsible section per rewritten commit, with every hash
linked to its commit page. Each force push gets its own comment, so the
history of a series' revisions stays with the PR.

## Usage

```yaml
name: range-diff
on:
  pull_request:
    types: [synchronize]
permissions:
  contents: read
  pull-requests: write
jobs:
  range-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: fungi-protocol/post-range-diff-comment@main
```

Fast-forward pushes are detected and skipped, so the workflow can run on
every `synchronize` event. The checkout can be shallow; the action fetches
what it needs.

Each side is diffed against its own merge base with the base branch, so a
rebase onto a newer base does not drag the base's new commits into the
comparison. The comment shows the exact `git range-diff` command to reproduce
it locally.

### Inputs

| input               | default                              | purpose                                                     |
| ------------------- | ------------------------------------ | ----------------------------------------------------------- |
| `token`             | `github.token`                       | needs `pull-requests: write`                                |
| `before`, `after`   | `github.event.before` / `.after`     | the two head commits                                        |
| `base-ref`          | the PR's base branch                 | merge bases are computed against this                       |
| `pr-number`         | the PR                               | where to comment                                            |
| `creation-factor`   | git's default                        | `git range-diff --creation-factor`                          |
| `max-comment-bytes` | `65000`                              | interdiffs are truncated to fit; GitHub's limit is 65536    |
| `post-comment`      | `true`                               | `false` renders to the log and job summary without posting |

Outputs: `forced` (`true`/`false`) and `comment-url`.

The full, untruncated comment is always written to the job summary.

### Caveats

- `pull_request` events from forks get a read-only token, so the comment
  cannot be posted for fork PRs.
- The old head is unreachable from any ref after the force push. GitHub keeps
  serving it by hash for a while, but not forever; the action fails loudly if
  it is gone.

## Development

`nix flake check` runs the renderer's unit tests, actionlint, and formatting.
`nix fmt` formats. `nix run . ` runs the action script locally given the same
environment variables `action.yml` sets.

This is the minimal version: bash for the git and GitHub plumbing, a
dependency-free Python script for parsing and rendering, both preinstalled on
hosted runners. Should the Python ever need dependencies, they go through
[uv2nix](https://github.com/pyproject-nix/uv2nix). Syntax-highlighted, delta-style interdiffs are the intended
next step, and would likely motivate a Rust rewrite.

## License

MIT, see [LICENSE](LICENSE).
