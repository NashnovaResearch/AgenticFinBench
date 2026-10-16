#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  echo 'Full v3 pipeline requires Linux x86_64 (a Linux VM/WSL2 also works).' >&2
  exit 1
fi
if ! command -v python3 >/dev/null || ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo 'Install Python >=3.11 (including venv), Node.js >=22, npm and curl first.' >&2; exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python >=3.11 required"'
node -e 'if (+process.versions.node.split(".")[0]<22) process.exit(1)'
# Setup lock avoids two simultaneous initial installs.
mkdir -p .runtime
exec 9>.runtime/setup.lock
flock 9
if [[ ! -x .venv/bin/python ]]; then python3 -m venv .venv; fi
if [[ ! -f .runtime/requirements.sha256 ]] || ! sha256sum -c .runtime/requirements.sha256 >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
  sha256sum requirements.txt > .runtime/requirements.sha256
fi
if [[ ! -x .runtime/node_modules/.bin/dsh ]]; then
  cp package.json package-lock.json .runtime/
  (cd .runtime && npm ci --no-audit --no-fund)
fi
if [[ ! -x .runtime/proot ]]; then
  curl -fL --retry 2 https://github.com/proot-me/proot/releases/download/v5.5.0/proot -o .runtime/proot.download
  echo 'db185300a9daabbce86aca7632d8c7fdc4249f6f153171954013b70c5f491ec0  .runtime/proot.download' | sha256sum -c -
  chmod 755 .runtime/proot.download
  mv .runtime/proot.download .runtime/proot
fi
flock -u 9
exec .venv/bin/python -m benchmark "$@"
