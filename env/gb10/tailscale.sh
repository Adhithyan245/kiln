#!/usr/bin/env bash
# Start (or check) Tailscale on the GB10 without sudo, so the team can reach it from anywhere.
# Userspace networking: no TUN device, no system service, everything under ~/tailscale (rule 6).
#
#   bash env/gb10/tailscale.sh           # after a reboot, or to check it is up
# First time only, sign in: ~/tailscale/tailscale --socket=$HOME/tailscale/tailscaled.sock up --hostname=kiln-gb10
# Then from any machine on the tailnet: ssh dell@kiln-gb10
set -euo pipefail

TS_DIR="${TS_DIR:-$HOME/tailscale}"
SOCK="$TS_DIR/tailscaled.sock"

if ! pgrep -u "$USER" -f "$TS_DIR/tailscaled" >/dev/null; then
  setsid nohup "$TS_DIR/tailscaled" --tun=userspace-networking --state="$TS_DIR/tailscaled.state" \
    --socket="$SOCK" --socks5-server=127.0.0.1:1055 >>"$TS_DIR/tailscaled.log" 2>&1 < /dev/null &
  sleep 3
  echo "started tailscaled; log at $TS_DIR/tailscaled.log"
fi
"$TS_DIR/tailscale" --socket="$SOCK" status
