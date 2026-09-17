# post-range-diff-comment

Posts `git range-diff` of a force push to a pull request as a collapsed
comment: an aligned listing of the commit pairs, then one collapsible
interdiff per rewritten commit. GitHub's "Compare" link diffs the two trees;
this shows how the commits changed.

```yaml
on:
  pull_request_target:
    types: [synchronize]
permissions:
  contents: read
  pull-requests: write
jobs:
  range-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: fungi-protocol/post-range-diff-comment@main
```

Fast-forward pushes are skipped. Each side is diffed against its own merge
base with the base branch, so a rebase onto a newer base is not mistaken for
changes. Inputs and outputs are described in [action.yml](action.yml).

`pull_request_target` gives fork PRs a token that can comment. It is safe here
because nothing from the PR runs: the checkout is the base branch, the action
reads the PR's commits with git plumbing only, and escapes what it posts. This
repository's own workflow uses `pull_request` so that PRs changing the action
exercise their own code.

The old head stays fetchable on GitHub only until it is garbage collected.
