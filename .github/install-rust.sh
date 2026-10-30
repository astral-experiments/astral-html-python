#!/usr/bin/env bash
set -euo pipefail

version=$1
case "$version" in
  1.97.0) sha256=1cf17e4905b841d4c8e3f76467ac148d55fb3f54bf213c86f0d287a36471d904 ;;
  1.99.1) sha256=231fcae47ee950621374725b5fc3b5441d2fbda2955ac45dd7dc816d8876cfe7 ;;
  *) echo "No pinned Rust distribution for $version" >&2; exit 1 ;;
esac

# The standalone distribution includes cargo, clippy and rustfmt under one digest.
target=x86_64-unknown-linux-gnu
dist="rust-$version-$target"
cd "$RUNNER_TEMP"
curl --fail --silent --show-error --location --retry 3 "https://static.rust-lang.org/dist/$dist.tar.xz" -o "$dist.tar.xz"
echo "$sha256  $dist.tar.xz" | sha256sum --check
tar -xf "$dist.tar.xz"
"$dist/install.sh" --prefix="$RUNNER_TEMP/rust" --disable-ldconfig \
  --components="rustc,cargo,rust-std-$target,rustfmt-preview,clippy-preview"
echo "$RUNNER_TEMP/rust/bin" >> "$GITHUB_PATH"
