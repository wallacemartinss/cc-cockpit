#!/usr/bin/env bash
# Instala o cc-cockpit para o usuario atual (sem tocar em /usr).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
AUTOSTART="$HOME/.config/autostart"

echo "==> cc-cockpit em $ROOT"

missing=()
python3 -c "import gi" 2>/dev/null || missing+=(python3-gi)
python3 -c "import cairo" 2>/dev/null || missing+=(python3-cairo)
python3 - <<'PY' 2>/dev/null || missing+=(gir1.2-ayatanaappindicator3-0.1)
import gi
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
except ValueError:
    gi.require_version("AppIndicator3", "0.1")
PY

if [ ${#missing[@]} -gt 0 ]; then
  echo "!! Faltam pacotes do sistema. Rode:"
  echo "   sudo apt install ${missing[*]}"
  echo "   (o dashboard e o 'report' funcionam sem eles; so a bandeja precisa)"
fi

mkdir -p "$BIN"
cat > "$BIN/cc-cockpit" <<EOF
#!/usr/bin/env bash
cd "$ROOT" && exec python3 -m cockpit "\$@"
EOF
chmod +x "$BIN/cc-cockpit"
echo "==> $BIN/cc-cockpit"

mkdir -p "$AUTOSTART"
cat > "$AUTOSTART/cc-cockpit.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=cc-cockpit
Comment=Uso do Claude Code na bandeja
Exec=$BIN/cc-cockpit tray
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=8
EOF
echo "==> autostart em $AUTOSTART/cc-cockpit.desktop"

echo "==> primeira coleta"
(cd "$ROOT" && python3 -m cockpit collect)

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "!! $BIN nao esta no PATH - adicione ao ~/.zshrc" ;;
esac

echo
echo "pronto:"
echo "  cc-cockpit          bandeja (tambem sobe o dashboard)"
echo "  cc-cockpit serve --open   so o dashboard"
echo "  cc-cockpit report   resumo no terminal"
