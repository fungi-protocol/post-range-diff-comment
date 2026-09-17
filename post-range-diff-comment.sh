#!/usr/bin/env bash
# Post `git range-diff` of a force push to a pull request as a collapsed comment.
#
# Expects to run inside a checkout of the repository (any depth, any ref) with
# these environment variables set by action.yml:
#   BEFORE, AFTER      head commit before and after the push
#   BASE_REF           the pull request's base branch
#   PR_NUMBER          the pull request number
#   GH_TOKEN           token with pull-requests: write
#   CREATION_FACTOR    optional, passed to --creation-factor
#   MAX_COMMENT_BYTES  cap on the comment body
#   POST_COMMENT       "false" to render without posting
set -euo pipefail

: "${BEFORE:?}" "${AFTER:?}" "${BASE_REF:?}" "${PR_NUMBER:?}"
REPO="${GITHUB_REPOSITORY:?}"
SERVER="${GITHUB_SERVER_URL:-https://github.com}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${GITHUB_OUTPUT:-/dev/null}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/null}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# actions/checkout leaves a shallow clone of the merge ref.  range-diff needs
# the base branch plus both heads; the old head is usually unreachable from any
# ref after a force push, but GitHub still serves it by hash for a while.
fetch_args=(--quiet --no-tags)
if [[ "$(git rev-parse --is-shallow-repository)" == true ]]; then
  fetch_args+=(--unshallow)
fi
git fetch "${fetch_args[@]}" origin \
  "+refs/heads/$BASE_REF:refs/remotes/origin/$BASE_REF" "$AFTER"
if ! git fetch --quiet --no-tags origin "$BEFORE"; then
  echo "::error::old head $BEFORE is no longer fetchable; cannot range-diff"
  exit 1
fi

if git merge-base --is-ancestor "$BEFORE" "$AFTER"; then
  echo "::notice::$BEFORE..$AFTER is a fast-forward push; no range-diff to post"
  echo "forced=false" >>"$OUT"
  exit 0
fi
echo "forced=true" >>"$OUT"

# Diff each side against where it forked from the base branch, so a rebase
# onto a newer base does not drag the base's new commits into the comparison.
# Fall back to the symmetric difference if either side is unrelated to base.
if old_base="$(git merge-base "origin/$BASE_REF" "$BEFORE")" &&
  new_base="$(git merge-base "origin/$BASE_REF" "$AFTER")"; then
  old_range="$old_base..$BEFORE"
  new_range="$new_base..$AFTER"
else
  echo "::warning::no merge base with $BASE_REF; using $BEFORE...$AFTER"
  old_range="$AFTER..$BEFORE"
  new_range="$BEFORE..$AFTER"
fi

args=(--no-color)
if [[ -n ${CREATION_FACTOR:-} ]]; then
  args+=("--creation-factor=$CREATION_FACTOR")
fi
git -c core.abbrev=40 range-diff "${args[@]}" "$old_range" "$new_range" >"$WORK/range-diff.txt"

PUSHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
short() { git rev-parse --short "$1"; }
pretty_old="$(short "${old_range%%..*}")..$(short "$BEFORE")"
pretty_new="$(short "${new_range%%..*}")..$(short "$AFTER")"

render() {
  python3 "$HERE/render.py" \
    --repo-url "$SERVER/$REPO" --before "$BEFORE" --after "$AFTER" \
    --old-range "$pretty_old" --new-range "$pretty_new" \
    --pushed-at "$PUSHED_AT" --max-bytes "$1" <"$WORK/range-diff.txt"
}
render "${MAX_COMMENT_BYTES:-65000}" >"$WORK/comment.md"
# Job summaries allow 1 MiB, so the summary usually holds the untruncated text.
render 1000000 >>"$SUMMARY"

if [[ ${POST_COMMENT:-true} == false ]]; then
  cat "$WORK/comment.md"
  exit 0
fi

: "${GH_TOKEN:?}"
if ! url="$(gh api "repos/$REPO/issues/$PR_NUMBER/comments" \
  -F body=@"$WORK/comment.md" --jq .html_url)"; then
  echo "::error::could not post the comment; the token needs pull-requests: write" \
    "(pull_request events from forks only get a read-only token)"
  exit 1
fi
echo "comment-url=$url" >>"$OUT"
echo "posted $url"
