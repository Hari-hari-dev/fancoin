#!/usr/bin/env bash

# Usage:
#   ./toggle_anchor.sh 0.28
#   ./toggle_anchor.sh 0.30
#
# This script deletes ~/.cargo/bin/anchor and replaces it with a symlink
# to the desired Anchor CLI in ~/.avm/bin/.

# Paths to your specific avm anchor binaries:
ANCHOR_028="/home/devuan/.avm/bin/anchor-0.28.0"
ANCHOR_030="/home/devuan/.avm/bin/anchor-0.30.1-e6d7dafe12da661a36ad1b4f3b5970e8986e5321"
CARGO_ANCHOR="/usr/local/bin/anchor"
CARGO_ANCHOR_2="/home/devuan/.cargo/bin/anchor"

if [ -z "$1" ]; then
  echo "Usage: $0 [0.28 | 0.30]"
  exit 1
fi

case "$1" in

  "0.28" | "0.28.0")
    # Remove old link/file if it exists
    rm -f "${CARGO_ANCHOR}"
    rm -f "${CARGO_ANCHOR_2}"
    # Create new symlink
    ln -sf ${ANCHOR_029} "${CARGO_ANCHOR}"
    ln -sf ${ANCHOR_029} "${CARGO_ANCHOR_2}"

    echo "Symlinked ~/.cargo/bin/anchor to Anchor v0.28.0"
    ;;

  "0.30" | "0.30.1")
    rm -f "${CARGO_ANCHOR}"
    rm -f "${CARGO_ANCHOR_2}"
    ln -sf ${ANCHOR_030} "${CARGO_ANCHOR}"
    ln -sf ${ANCHOR_030} "${CARGO_ANCHOR_2}"

    echo "Symlinked ~/.cargo/bin/anchor to Anchor v0.30.1"
    ;;

  *)
    echo "Unrecognized version: $1"
    echo "Valid options are 0.28 or 0.30"
    exit 1
    ;;
esac

# Optional: clear any shell hash caching
hash -r 2>/dev/null

# Show which anchor is active now
echo "Now 'which anchor' = $(which anchor)"
