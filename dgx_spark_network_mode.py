#!/usr/bin/env python3
"""
DGX Spark network mode tray indicator for Ubuntu.

Modes:
  - Strict Confidential Mode: only localhost traffic is allowed.
  - Internet OFF: localhost and local/LAN ranges are allowed, internet is blocked.
  - Full Connectivity: removes the firewall rules created by this script.

The tray UI runs as the desktop user. Network mode changes are applied by
re-running this script through pkexec with --apply <mode>.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_ID = "dgx-spark-network-mode"
NFT_TABLE = "dgx_spark_privacy"
STATE_FILE = Path("/run/dgx-spark-network-mode")
SCRIPT_PATH = Path(__file__).resolve()

MODE_FULL = "full"
MODE_INTERNET_OFF = "internet_off"
MODE_STRICT = "strict"

MODE_LABELS = {
    MODE_STRICT: "Enable Strict Confidential Mode",
    MODE_INTERNET_OFF: "Enable Internet OFF",
    MODE_FULL: "Full Connectivity",
}


def run(command, *, check=True):
    return subprocess.run(command, check=check, text=True)


def require_root():
    if os.geteuid() != 0:
        raise SystemExit("This operation must run as root. Use the tray menu or pkexec.")


def require_command(name):
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command: {name}")


def nft_script_for_mode(mode):
    local_ipv4 = "{ 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 224.0.0.0/4, 255.255.255.255 }"
    local_ipv6 = "{ ::1, fe80::/10, fc00::/7, ff00::/8 }"

    base = f"""
add table inet {NFT_TABLE}
add chain inet {NFT_TABLE} output {{ type filter hook output priority -50; policy accept; }}
add chain inet {NFT_TABLE} input {{ type filter hook input priority -50; policy accept; }}
add chain inet {NFT_TABLE} forward {{ type filter hook forward priority -50; policy drop; }}
"""

    if mode == MODE_FULL:
        return ""

    if mode == MODE_STRICT:
        return base + f"""
add rule inet {NFT_TABLE} output oifname "lo" accept
add rule inet {NFT_TABLE} input iifname "lo" accept
add rule inet {NFT_TABLE} output reject
add rule inet {NFT_TABLE} input drop
"""

    if mode == MODE_INTERNET_OFF:
        return base + f"""
add rule inet {NFT_TABLE} output oifname "lo" accept
add rule inet {NFT_TABLE} input iifname "lo" accept
add rule inet {NFT_TABLE} output ip daddr {local_ipv4} accept
add rule inet {NFT_TABLE} input ip saddr {local_ipv4} accept
add rule inet {NFT_TABLE} output ip6 daddr {local_ipv6} accept
add rule inet {NFT_TABLE} input ip6 saddr {local_ipv6} accept
add rule inet {NFT_TABLE} output reject
add rule inet {NFT_TABLE} input drop
"""

    raise SystemExit(f"Unknown mode: {mode}")


def apply_mode(mode):
    require_root()
    require_command("nft")

    subprocess.run(["nft", "delete", "table", "inet", NFT_TABLE], check=False, stderr=subprocess.DEVNULL)

    if mode == MODE_FULL:
        STATE_FILE.unlink(missing_ok=True)
        return

    script = nft_script_for_mode(mode)
    result = subprocess.run(["nft", "-f", "-"], input=script, text=True)

    if result.returncode != 0:
        raise SystemExit(result.returncode)

    STATE_FILE.write_text(mode + "\n", encoding="utf-8")


def current_mode():
    try:
        value = STATE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return MODE_FULL
    return value if value in MODE_LABELS else MODE_FULL


class TrayApp:
    def __init__(self):
        self.gtk, self.indicator_api = self.load_gtk()
        self.indicator = self.indicator_api.Indicator.new(
            APP_ID,
            "network-wireless",
            self.indicator_api.IndicatorCategory.SYSTEM_SERVICES,
        )
        self.indicator.set_status(self.indicator_api.IndicatorStatus.ACTIVE)
        self.menu = self.gtk.Menu()
        self.mode_items = {}
        self.build_menu()
        self.indicator.set_menu(self.menu)
        self.refresh()

    @staticmethod
    def load_gtk():
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            try:
                gi.require_version("AyatanaAppIndicator3", "0.1")
                from gi.repository import AyatanaAppIndicator3 as IndicatorApi
            except (ImportError, ValueError):
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as IndicatorApi

            from gi.repository import Gtk
            return Gtk, IndicatorApi
        except (ImportError, ValueError) as exc:
            raise SystemExit(
                "Missing tray dependencies.\n"
                "Install them with:\n"
                "  sudo apt install python3-gi gir1.2-gtk-3.0 "
                "gir1.2-ayatanaappindicator3-0.1 policykit-1 nftables\n"
                "On older Ubuntu releases, use gir1.2-appindicator3-0.1 instead "
                "of gir1.2-ayatanaappindicator3-0.1."
            ) from exc

    def build_menu(self):
        for mode in (MODE_STRICT, MODE_INTERNET_OFF, MODE_FULL):
            item = self.gtk.CheckMenuItem(label=MODE_LABELS[mode])
            item.connect("activate", self.on_mode_selected, mode)
            self.mode_items[mode] = item
            self.menu.append(item)

        self.menu.append(self.gtk.SeparatorMenuItem())

        refresh = self.gtk.MenuItem(label="Refresh Status")
        refresh.connect("activate", lambda _item: self.refresh())
        self.menu.append(refresh)

        quit_item = self.gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _item: self.gtk.main_quit())
        self.menu.append(quit_item)

        self.menu.show_all()

    def on_mode_selected(self, _item, mode):
        if mode == current_mode():
            self.refresh()
            return

        command = ["pkexec", sys.executable, str(SCRIPT_PATH), "--apply", mode]
        completed = run(command, check=False)
        if completed.returncode != 0:
            self.show_error("Network mode was not changed.")
        self.refresh()

    def refresh(self):
        active = current_mode()
        for mode, item in self.mode_items.items():
            item.handler_block_by_func(self.on_mode_selected)
            item.set_active(mode == active)
            item.handler_unblock_by_func(self.on_mode_selected)

        self.indicator.set_label(self.short_label(active), APP_ID)
        if active == MODE_FULL:
            self.indicator.set_icon_full("network-wireless", MODE_LABELS[active])
        elif active == MODE_INTERNET_OFF:
            self.indicator.set_icon_full("network-offline", MODE_LABELS[active])
        else:
            self.indicator.set_icon_full("security-high", MODE_LABELS[active])

    @staticmethod
    def short_label(mode):
        if mode == MODE_STRICT:
            return "Strict"
        if mode == MODE_INTERNET_OFF:
            return "Net OFF"
        return "Full"

    def show_error(self, message):
        dialog = self.gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=self.gtk.MessageType.ERROR,
            buttons=self.gtk.ButtonsType.OK,
            text=message,
        )
        dialog.format_secondary_text("Check that pkexec and nftables are installed.")
        dialog.run()
        dialog.destroy()

    def run(self):
        self.gtk.main()


def install_autostart():
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop_file = autostart_dir / "dgx-spark-network-mode.desktop"
    desktop_file.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=DGX Spark Network Mode",
                f"Exec={sys.executable} {SCRIPT_PATH}",
                "Icon=network-wireless",
                "Terminal=false",
                "X-GNOME-Autostart-enabled=true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Installed autostart entry: {desktop_file}")


def parse_args():
    parser = argparse.ArgumentParser(description="DGX Spark Ubuntu tray network mode switcher")
    parser.add_argument("--apply", choices=(MODE_STRICT, MODE_INTERNET_OFF, MODE_FULL))
    parser.add_argument("--install-autostart", action="store_true")
    parser.add_argument("--status", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.apply:
        apply_mode(args.apply)
        return

    if args.install_autostart:
        install_autostart()
        return

    if args.status:
        print(current_mode())
        return

    TrayApp().run()


if __name__ == "__main__":
    main()
