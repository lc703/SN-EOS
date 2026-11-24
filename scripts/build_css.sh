#!/usr/bin/env sh
# Compile Tailwind into static/css/app.css (committed, so deploys need no Node or CDN).
# Downloads the standalone Tailwind v3 CLI into bin/ on first run.
set -e
cd "$(dirname "$0")/.."
if [ ! -x bin/tailwindcss ]; then
  mkdir -p bin
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) asset=tailwindcss-linux-x64 ;;
    Linux-aarch64) asset=tailwindcss-linux-arm64 ;;
    Darwin-arm64) asset=tailwindcss-macos-arm64 ;;
    Darwin-x86_64) asset=tailwindcss-macos-x64 ;;
    *) echo "Unsupported platform; download the Tailwind v3 standalone CLI to bin/tailwindcss" >&2; exit 1 ;;
  esac
  curl -sSL -o bin/tailwindcss "https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/$asset"
  chmod +x bin/tailwindcss
fi
bin/tailwindcss -c tailwind.config.js -i static/src/input.css -o static/css/app.css --minify
