#!/usr/bin/env bash
# Creates the priority labels and the 7 week-1 issues from scripts/week1-issues/*.md.
# Usage (Git Bash, from the repository root, logged in with `gh auth login`):
#   bash scripts/create-week1-issues.sh                 # issues only
#   bash scripts/create-week1-issues.sh <project-number> # also adds them to that GitHub Project
# Adding to a Project needs the `project` scope: gh auth refresh -s project
set -euo pipefail

repo="brunoccalmeida/doc-intake-pipeline"
owner="brunoccalmeida"
project="${1:-}"
dir="$(dirname "$0")/week1-issues"

gh label create "priority: P0" --repo "$repo" --color B60205 --description "Blocks the next missions" --force
gh label create "priority: P1" --repo "$repo" --color D93F0B --description "Needed this cycle" --force
gh label create "priority: P2" --repo "$repo" --color FBCA04 --description "Can wait" --force

for file in "$dir"/0*.md; do
  title="$(sed -n 's/^Title: //p' "$file")"
  label="$(sed -n 's/^Labels: //p' "$file")"
  body="$(sed '1,2d' "$file")"
  url="$(gh issue create --repo "$repo" --title "$title" --label "$label" --body "$body")"
  echo "$url"
  if [[ -n "$project" ]]; then
    gh project item-add "$project" --owner "$owner" --url "$url" >/dev/null
  fi
done
