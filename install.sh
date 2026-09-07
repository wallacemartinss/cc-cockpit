#!/usr/bin/env bash
# Installs cc-cockpit from this checkout, for development or a quick try.
# For a packaged install use pipx, the .deb or the AUR package - see README.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"

mkdir -p "$BIN"
cat > "$BIN/cc-cockpit" <<EOF
#!/usr/bin/env bash
cd "$ROOT" && exec python3 -m cockpit "\$@"
EOF
chmod +x "$BIN/cc-cockpit"
echo "==> $BIN/cc-cockpit"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "!! $BIN is not on PATH - add it to your shell profile" ;;
esac

# autostart, statusline capture, dependency check and first collection
"$BIN/cc-cockpit" setup

echo
echo "ready:"
echo "  cc-cockpit          tray (also starts the dashboard)"
echo "  cc-cockpit serve --open   dashboard only"
echo "  cc-cockpit report   terminal summary"
