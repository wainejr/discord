#!/bin/bash

set -e

FOLDER="${HOME}/.config/systemd/user"
mkdir -p $FOLDER
cp scripts/acelerado.service $FOLDER

systemctl --user daemon-reload
# systemctl --user enable acelerado
# systemctl --user start acelerado
