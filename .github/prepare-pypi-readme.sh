#!/usr/bin/env bash
set -euo pipefail

# GitHub resolves relative chart paths. PyPI needs the raw images at the
# packaged commit, even before the release workflow creates the version tag.
raw_url="https://raw.githubusercontent.com/$GITHUB_REPOSITORY/$GITHUB_SHA"
sed -Ei "s@(src|srcset)=\"benchmarks/@\1=\"$raw_url/benchmarks/@g" README.md
