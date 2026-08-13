#!/usr/bin/env sh
set -eu
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
[ -f config.yml ] || cp config.example.yml config.yml
exec od-rclone
