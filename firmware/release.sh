#!/bin/sh
# Builds the release firmware and copies it into the config page, which flashes it from the
# browser: site/config/firmware/footswitch.uf2 plus firmware.json (version, size, commit).
# Bump `version` in Cargo.toml first; the page offers the update when the pedal reports an
# older version.
set -eu
cd "$(dirname "$0")"

cargo build --release
out=../site/config/firmware
mkdir -p "$out"
elf2uf2-rs target/thumbv6m-none-eabi/release/footswitch-firmware "$out/footswitch.uf2"

version=$(sed -n 's/^version *= *"\(.*\)"/\1/p' Cargo.toml | head -n 1)
commit=$(git rev-parse --short HEAD)
if ! git diff --quiet HEAD -- . ../core; then commit="$commit-dirty"; fi
size=$(wc -c < "$out/footswitch.uf2")
cat > "$out/firmware.json" <<EOF
{
  "version": "$version",
  "file": "footswitch.uf2",
  "size": $size,
  "commit": "$commit",
  "built": "$(date -u +%Y-%m-%d)"
}
EOF
echo "site/config/firmware: firmware $version ($commit), $size bytes"
