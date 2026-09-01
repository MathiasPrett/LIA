#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-mathias@192.168.100.251}"
PI_PATH="${PI_PATH:-~/Docker/LIA}"

echo "→ Desplegando a $PI_HOST:$PI_PATH ..."

ssh "$PI_HOST" "cd $PI_PATH && \
  echo '→ git pull' && git pull && \
  echo '→ build (sin buildx, la Pi tiene una versión vieja)' && DOCKER_BUILDKIT=0 docker-compose build && \
  echo '→ restart' && docker-compose up -d"

echo "→ Listo. Últimas líneas de log:"
ssh "$PI_HOST" "cd $PI_PATH && docker-compose logs --tail=30"
