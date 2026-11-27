#!/usr/bin/env bash
# The API VM's first boot, and every boot after (plan/2026-11-27 §2): safe to run again. Installs Docker with the
# Compose plugin, adds swap, turns on automatic security updates and makes the folders the deploy writes into.
# The app itself arrives with scripts/deploy_api.ps1.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon -a

if ! docker compose version >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg unattended-upgrades
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
  > /etc/apt/apt.conf.d/20auto-upgrades

systemctl enable --now docker

# /opt/hiru: compose.yaml, Caddyfile and the env files (root only). /var/hiru/files: the API's disk cache,
# owned by the container's user (uid 10001, see the Dockerfile).
install -d -m 0700 /opt/hiru
install -d -m 0755 /var/hiru
install -d -m 0750 -o 10001 -g 10001 /var/hiru/files
