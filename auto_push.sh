#!/bin/bash
cd /opt/bourse-bot || exit

if [[ -n $(git status --porcelain) ]]; then
    git add .
    TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
    git commit -m "Auto update: ${TIMESTAMP}"
    git push origin main
fi
