#!/usr/bin/env bash
set -euo pipefail

CONNECTION_NAME="Mobile@FSMA"
WIFI_INTERFACE="wlP9s9"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "Erreur: nmcli n'est pas installe ou introuvable." >&2
  exit 1
fi

if ! nmcli connection show "$CONNECTION_NAME" >/dev/null 2>&1; then
  echo "Erreur: la connexion NetworkManager '$CONNECTION_NAME' est introuvable." >&2
  exit 1
fi

echo "Activation du Wi-Fi..."
nmcli radio wifi on

echo "Configuration de l'auto-reconnexion pour '$CONNECTION_NAME'..."
nmcli connection modify "$CONNECTION_NAME" \
  connection.interface-name "$WIFI_INTERFACE" \
  connection.autoconnect yes \
  connection.autoconnect-priority 100 \
  connection.autoconnect-retries 0 \
  connection.auth-retries 0 \
  802-11-wireless.powersave 2

if ! nmcli -t -f DEVICE,STATE device status | grep -q "^${WIFI_INTERFACE}:connected$"; then
  echo "Reconnexion de '$CONNECTION_NAME' sur $WIFI_INTERFACE..."
  nmcli connection up "$CONNECTION_NAME"
fi

echo "Etat final:"
nmcli -f connection.autoconnect,connection.autoconnect-priority,connection.autoconnect-retries,connection.auth-retries,802-11-wireless.powersave connection show "$CONNECTION_NAME"
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
