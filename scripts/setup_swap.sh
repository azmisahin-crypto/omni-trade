#!/usr/bin/env bash
# e2-micro (1GB RAM) gibi düşük bellekli VM'lerde Docker + Python botu OOM'a
# çok yaklaşabiliyor. Bu script 2GB'lık bir swap dosyası oluşturup kalıcı
# hale getirir (fstab'a ekler) — RAM tükendiğinde sistem sert şekilde
# kilitlenmek yerine swap'a taşar.
#
# Kullanım:
#   sudo bash scripts/setup_swap.sh
set -euo pipefail

SWAP_FILE="/swapfile"
SWAP_SIZE_GB=2

if [ "$(id -u)" -ne 0 ]; then
  echo "Bu script root ile çalıştırılmalı (sudo bash scripts/setup_swap.sh)" >&2
  exit 1
fi

if swapon --show | grep -q "$SWAP_FILE"; then
  echo "Swap zaten aktif: $SWAP_FILE — bir şey yapılmadı."
  exit 0
fi

if [ -f "$SWAP_FILE" ]; then
  echo "$SWAP_FILE zaten var ama aktif değil, tekrar kullanılacak."
else
  echo "Oluşturuluyor: ${SWAP_SIZE_GB}GB $SWAP_FILE"
  fallocate -l "${SWAP_SIZE_GB}G" "$SWAP_FILE" || dd if=/dev/zero of="$SWAP_FILE" bs=1M count=$((SWAP_SIZE_GB * 1024))
  chmod 600 "$SWAP_FILE"
  mkswap "$SWAP_FILE"
fi

swapon "$SWAP_FILE"

if ! grep -q "^$SWAP_FILE " /etc/fstab; then
  echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
  echo "/etc/fstab güncellendi — reboot sonrası da kalıcı."
fi

# swappiness'i düşük tut: swap'ı sadece gerçekten gerektiğinde kullansın,
# sürekli diske yazıp SSD/HDD'yi yormasın.
if ! grep -q "^vm.swappiness" /etc/sysctl.conf 2>/dev/null; then
  echo "vm.swappiness=10" >> /etc/sysctl.conf
  sysctl -p >/dev/null || true
fi

echo "Tamamlandı:"
swapon --show
free -h
