#!/usr/bin/env bash
# Post `git range-diff` of a force push to a pull request as a collapsed comment.
#
# Expects to run inside a checkout of the repository (any depth, any ref) with
# these environment variables set by action.yml:
#   AFTER              head commit after the push
#   BEFORE             head commit before the push; optional on
#                      ready_for_review, where the head of the last range-diff
#                      comment or draft marker is used instead
#   BASE_REF           the pull request's base branch
#   PR_NUMBER          the pull request number
#   GH_TOKEN           token with contents: read and pull-requests: write
#   CREATION_FACTOR    optional, passed to --creation-factor
#   MAX_COMMENT_BYTES  cap on the comment body
#   POST_COMMENT       "false" to render without posting
#   HIDE_AFTER_DAYS    hide earlier range-diff comments at least this old
#   WRAP_WIDTH         optional, hard wrap interdiff lines longer than this
#   DRAFT              "true" while the pull request is a draft; posts nothing
#                      except the marker on converted_to_draft
#   EVENT_ACTION       the pull request event action; ready_for_review posts
#                      from the last range-diff comment or draft marker,
#                      converted_to_draft posts a minimized marker at the
#                      current head
set -euo pipefail

: "${AFTER:?}" "${BASE_REF:?}" "${PR_NUMBER:?}"
REPO="${GITHUB_REPOSITORY:?}"
SERVER="${GITHUB_SERVER_URL:-https://github.com}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${GITHUB_OUTPUT:-/dev/null}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/null}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Post a comment body from a file, recording its node id and URL for the
# caller.  The error names what could not be posted.
post_comment() {
  local body=$1 what=$2
  if ! posted="$(gh api "repos/$REPO/issues/$PR_NUMBER/comments" \
    -F body=@"$body" --jq '"\(.node_id) \(.html_url)"')"; then
    echo "::error::could not post the $what; the token needs pull-requests: write" \
      "(pull_request events from forks only get a read-only token)"
    return 1
  fi
  read -r node_id url <<<"$posted"
  echo "comment-url=$url" >>"$OUT"
  echo "posted $url"
}

minimize() {
  # shellcheck disable=SC2016
  gh api graphql -f id="$1" -f query='
    mutation($id: ID!) {
      minimizeComment(input: {subjectId: $id, classifier: OUTDATED}) {
        clientMutationId
      }
    }' >/dev/null
}

# On conversion to draft, post a minimized marker at the current head.  The
# last range-diff comment may not exist yet, or may predate fast-forward pushes
# made while the draft was being written, so ready_for_review needs the exact
# head at conversion to range-diff from.
if [[ ${EVENT_ACTION:-} == converted_to_draft ]]; then
  printf '<!-- post-range-diff-comment after=%s -->\n' "$AFTER" >"$WORK/marker.md"
  if [[ ${POST_COMMENT:-true} == false ]]; then
    cat "$WORK/marker.md"
    echo "forced=false" >>"$OUT"
    exit 0
  fi
  : "${GH_TOKEN:?}"
  echo "forced=false" >>"$OUT"
  post_comment "$WORK/marker.md" "draft marker" || exit 1
  if ! minimize "$node_id"; then
    echo "::warning::could not minimize the draft marker"
  fi
  exit 0
fi

# A draft collects a range-diff per force push, which is noise while it is
# still being written.  Wait for ready_for_review, which posts the range-diff
# since the last comment instead.
if [[ ${DRAFT:-false} == true ]]; then
  echo "::notice::pull request is a draft; no range-diff comment"
  echo "forced=false" >>"$OUT"
  exit 0
fi

# shellcheck disable=SC2016
comments_query='
  query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
    repository(owner: $owner, name: $name) {
      pullRequest(number: $number) {
        comments(first: 100, after: $endCursor) {
          pageInfo { hasNextPage endCursor }
          nodes { id body createdAt isMinimized viewerDidAuthor }
        }
      }
    }
  }'

list_comments() {
  gh api graphql --paginate \
    -f owner="${REPO%/*}" -f name="${REPO#*/}" -F number="$PR_NUMBER" \
    -f query="$comments_query" \
    --jq '.data.repository.pullRequest.comments.nodes[]'
}

# The head of the most recent range-diff comment or draft marker is where the
# draft period started, since draft pushes post nothing.
last_range_diff_head() {
  list_comments | python3 "$HERE/last_comment.py"
}

if [[ ${EVENT_ACTION:-} == ready_for_review ]]; then
  if ! last="$(last_range_diff_head)"; then
    echo "::error::could not read the last range-diff comment or draft marker's head"
    exit 1
  fi
  if [[ -z $last ]]; then
    echo "::notice::no earlier range-diff comment or draft marker to compare with; nothing to post"
    echo "forced=false" >>"$OUT"
    exit 0
  fi
  if [[ $last == "$AFTER" ]]; then
    echo "::notice::the head has not moved since the last range-diff comment or draft marker; nothing to post"
    echo "forced=false" >>"$OUT"
    exit 0
  fi
  BEFORE="$last"
fi
: "${BEFORE:?}"

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

# A fast-forward push has no rewritten commits to compare.  On
# ready_for_review the head may have moved on by ordinary commits during the
# draft, and those are exactly what the catch-up comment should show.
catch_up=()
if git merge-base --is-ancestor "$BEFORE" "$AFTER"; then
  if [[ ${EVENT_ACTION:-} != ready_for_review ]]; then
    echo "::notice::$BEFORE..$AFTER is a fast-forward push; no range-diff to post"
    echo "forced=false" >>"$OUT"
    exit 0
  fi
  catch_up=(--fast-forward)
fi
echo "forced=true" >>"$OUT"

# When the base branch was itself rewritten, as a parent in a stack, its old
# tips are unreachable from it, and a series left on one would seem to fork
# from further back.  GitHub's activity log stands in for the reflog that
# `git merge-base --fork-point` reads.
base_tips=("origin/$BASE_REF")
if rewound="$(gh api --paginate --method GET --jq '.[].before' "repos/$REPO/activity" \
  -f ref="refs/heads/$BASE_REF" -f activity_type=force_push -F per_page=100)"; then
  for tip in $rewound; do
    if git fetch --quiet --no-tags origin "$tip" 2>/dev/null; then
      base_tips+=("$tip")
    fi
  done
else
  echo "::warning::could not list force pushes of $BASE_REF; if it was rewritten, its old commits will be counted in the series"
fi

# Diff each side against where it forked from the base branch, so a rebase
# onto a newer base does not drag the base's new commits into the comparison.
# Fall back to the symmetric difference if either side is unrelated to base,
# or if a tip of the base contains it: its range would be empty, which
# range-diff rejects.
if old_base="$(git merge-base "$BEFORE" "${base_tips[@]}")" &&
  new_base="$(git merge-base "$AFTER" "${base_tips[@]}")" &&
  [[ $old_base != "$(git rev-parse "$BEFORE^{commit}")" ]] &&
  [[ $new_base != "$(git rev-parse "$AFTER^{commit}")" ]]; then
  old_range="$old_base..$BEFORE"
  new_range="$new_base..$AFTER"
  read -r base_behind base_ahead < <(git rev-list --left-right --count "$old_base...$new_base")
else
  echo "::warning::no fork point from $BASE_REF; using $BEFORE...$AFTER"
  old_range="$AFTER..$BEFORE"
  new_range="$BEFORE..$AFTER"
  old_base="" new_base="" base_behind=0 base_ahead=0
fi

args=(--no-color)
if [[ -n ${CREATION_FACTOR:-} ]]; then
  args+=("--creation-factor=$CREATION_FACTOR")
fi
git -c core.abbrev=40 range-diff "${args[@]}" "$old_range" "$new_range" >"$WORK/range-diff.txt"
for range in "$old_range" "$new_range"; do
  git log --format=%H --numstat "$range"
done >"$WORK/stats.txt"

PUSHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
short() { git rev-parse --short "$1"; }
pretty_old="$(short "${old_range%%..*}")..$(short "$BEFORE")"
pretty_new="$(short "${new_range%%..*}")..$(short "$AFTER")"

render() {
  python3 "$HERE/render.py" \
    --repo-url "$SERVER/$REPO" --before "$BEFORE" --after "$AFTER" \
    --old-range "$pretty_old" --new-range "$pretty_new" \
    --old-base "$old_base" --new-base "$new_base" \
    --base-behind "$base_behind" --base-ahead "$base_ahead" \
    --stats "$WORK/stats.txt" \
    --pushed-at "$PUSHED_AT" --max-bytes "$1" \
    ${catch_up[@]+"${catch_up[@]}"} \
    ${WRAP_WIDTH:+--wrap-width "$WRAP_WIDTH"} <"$WORK/range-diff.txt"
}
render "${MAX_COMMENT_BYTES:-65000}" >"$WORK/comment.md"
# Job summaries allow 1 MiB, so the summary usually holds the full text.
# Wrapping is left out there because it lengthens the text it would hold.
WRAP_WIDTH='' render 1000000 >>"$SUMMARY"

if [[ ${POST_COMMENT:-true} == false ]]; then
  cat "$WORK/comment.md"
  exit 0
fi

: "${GH_TOKEN:?}"
hide_outdated() {
  local ids id
  ids="$(list_comments | python3 "$HERE/outdated.py" "$HIDE_AFTER_DAYS")" || return
  for id in $ids; do
    [[ $id == "$1" ]] && continue
    minimize "$id" || return
  done
}

post_comment "$WORK/comment.md" "comment" || exit 1

# After posting, so a failed post never leaves the old ones hidden.  A
# ready_for_review catch-up is not a force push, so it leaves the earlier
# range-diff comments alone; hide-after-days is documented for force pushes.
if [[ -n ${HIDE_AFTER_DAYS:-} && ${EVENT_ACTION:-} != ready_for_review ]] &&
  ! hide_outdated "$node_id"; then
  echo "::warning::could not hide the outdated range-diff comments"
fi
