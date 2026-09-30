#!/usr/bin/env bash
# Builds the linux/amd64 image on this machine and pushes it to the private Docker Hub repo with the
# tags from §13.3. CI never publishes (its push steps stay gated off), so this is the only publisher.
# The --platform matters: on Apple Silicon a plain `docker build` makes an arm64 image the Intel
# server cannot run.
# Usage: DOCKERHUB_REPO=<user>/fetcharr scripts/publish.sh <edge|vX.Y.Z> [--dry-run]
set -euo pipefail

fail() { echo "FAIL: $*" >&2; exit 1; }

REF="${1:-}"
DRY_RUN=""
case "${2:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  *) fail "unknown option '$2' (usage: scripts/publish.sh <edge|vX.Y.Z> [--dry-run])" ;;
esac

[ -n "$REF" ] || fail "no ref given (usage: scripts/publish.sh <edge|vX.Y.Z> [--dry-run])"
REPO="${DOCKERHUB_REPO:-}"
[ -n "$REPO" ] || fail "DOCKERHUB_REPO is unset, e.g. DOCKERHUB_REPO=<user>/fetcharr"

# A dirty tree would publish an image no commit describes, and VCS_REF would lie about it.
[ -z "$(git status --porcelain)" ] || fail "the working tree is dirty; commit or stash first"

SHA="$(git rev-parse HEAD)"
TAGS=()
case "$REF" in
  edge)
    VERSION="edge"
    TAGS=("edge" "sha-$(git rev-parse --short HEAD)")
    ;;
  v[0-9]*.[0-9]*.[0-9]*)
    VERSION="${REF#v}"
    [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "'$REF' is not vX.Y.Z"
    # Publishing a release from an untagged commit would make a rollback lie about what runs.
    HEAD_TAG="$(git describe --exact-match --tags HEAD 2>/dev/null || true)"
    [ "$HEAD_TAG" = "$REF" ] || fail "HEAD is not tagged $REF (run: git tag $REF)"
    TAGS=("$VERSION" "${VERSION%.*}" "${VERSION%%.*}" "latest")
    ;;
  *)
    fail "'$REF' is neither 'edge' nor 'vX.Y.Z'"
    ;;
esac

ARGV=(docker buildx build --platform linux/amd64)
for tag in "${TAGS[@]}"; do
  ARGV+=(--tag "docker.io/$REPO:$tag")
done
ARGV+=(--build-arg "APP_VERSION=$VERSION" --build-arg "VCS_REF=$SHA")
ARGV+=(--push "$(git rev-parse --show-toplevel)")

if [ -n "$DRY_RUN" ]; then
  printf '%s\n' "${ARGV[@]}"
  exit 0
fi

exec "${ARGV[@]}"
