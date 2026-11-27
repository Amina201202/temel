#!/usr/bin/env bash
# Yeni Ubuntu 24.04 serverde bir defe: Docker + kod
# istifade: ssh root@IP 'bash -s' < deploy/server_setup.sh
set -e
apt-get update -y
apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
# 2 GB RAM azdir, swap elave edirik ki docker build zamani yaddas bitmesin
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cd /root
[ -d radix ] || git clone https://github.com/Amina201202/temel.git radix
echo "HAZIRDIR: indi .env faylini kocur (scp), sonra bazani."
