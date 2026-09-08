#!/usr/bin/env bash
# Builds a .deb from the checkout. Output: dist/cc-cockpit_<version>_all.deb
#
# Plain dpkg-deb rather than debhelper: the package is pure Python with no
# compiled parts, so the whole job is dropping the module into dist-packages
# and declaring the GTK dependencies that pip cannot provide.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(python3 -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('$ROOT/cockpit/__init__.py').read_text()).group(1))")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/DEBIAN" \
           "$STAGE/usr/lib/python3/dist-packages/cockpit" \
           "$STAGE/usr/bin" \
           "$STAGE/usr/share/doc/cc-cockpit" \
           "$STAGE/usr/share/applications"

cp -r "$ROOT/cockpit/." "$STAGE/usr/lib/python3/dist-packages/cockpit/"
find "$STAGE/usr/lib/python3/dist-packages/cockpit" -name '__pycache__' -type d -exec rm -rf {} +

cat > "$STAGE/usr/bin/cc-cockpit" <<'PY'
#!/usr/bin/python3
import sys

from cockpit.cli import main

sys.exit(main())
PY
chmod 755 "$STAGE/usr/bin/cc-cockpit"

cp "$ROOT/README.md" "$STAGE/usr/share/doc/cc-cockpit/"
cp "$ROOT/LICENSE" "$STAGE/usr/share/doc/cc-cockpit/copyright"

cat > "$STAGE/usr/share/applications/cc-cockpit.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=cc-cockpit
Comment=Claude Code usage in the tray
Exec=/usr/bin/cc-cockpit tray
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;
DESKTOP

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: cc-cockpit
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-gi, python3-cairo, gir1.2-ayatanaappindicator3-0.1
Suggests: gnome-shell-extension-appindicator, xfce4-statusnotifier-plugin
Maintainer: Wallace Martins da Silva <wallacemartinss@gmail.com>
Homepage: https://github.com/wallacemartinss/cc-cockpit
Description: Claude Code usage panel for Linux desktops
 Tray indicator with a live rate-limit ring, a local dashboard and a terminal
 summary for Claude Code usage. Reads the official limits from the statusline
 payload, so it needs no credentials and makes no network calls.
 .
 The indicator is a StatusNotifierItem, so it works on any panel that hosts one:
 GNOME with the AppIndicator extension, XFCE 4.16+ with Status Tray Items, KDE
 Plasma out of the box. The Suggests cover the two that need a package.
CONTROL

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/cc-cockpit_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT" >/dev/null
echo "$OUT"
