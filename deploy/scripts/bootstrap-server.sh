#!/usr/bin/env bash
# Preparación inicial de un servidor Ubuntu 24.04 (ejecutar una vez como root).
set -euo pipefail
apt-get update
apt-get install -y ca-certificates curl ufw unattended-upgrades fail2ban rclone
# Docker Engine + Compose (repositorio oficial)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# Firewall: solo SSH y HTTP/HTTPS
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
dpkg-reconfigure -f noninteractive unattended-upgrades
mkdir -p /opt/eventos /var/backups/eventos
chmod 700 /var/backups/eventos
echo "Listo. Copia deploy/ a /opt/eventos/deploy y crea env/stack.env y env/backend.env (chmod 600)."
