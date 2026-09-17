#!/usr/bin/env bash
# Rendert beide Plakate nach PDF.
#
#   ./build.sh            beide
#   ./build.sh projekt    nur Plakat 1
#   ./build.sh valley     nur Plakat 2
#
# Gesetzt ist DIN A1 hoch (594 × 841 mm) über @page in poster.css. Weil die
# A-Reihe durchgehend 1:√2 hat, skaliert dasselbe PDF verlustfrei auf A0 oder
# A2; beim Druck "auf Seitengröße skalieren" wählen.
#
# Gerendert wird mit Chrome/Brave im Headless-Modus, weil das die einzige
# Engine auf diesem Rechner ist, die das Layout exakt so setzt wie die
# Installation selbst. Die Schriften stecken als Base64 in fonts.css, es wird
# also nichts aus dem Netz nachgeladen.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHROME=""
for c in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
         "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
         "/Applications/Chromium.app/Contents/MacOS/Chromium" \
         "$(command -v chromium || true)" "$(command -v google-chrome || true)"; do
  [ -n "$c" ] && [ -x "$c" ] && { CHROME="$c"; break; }
done
[ -n "$CHROME" ] || { echo "Kein Chrome/Brave/Chromium gefunden." >&2; exit 1; }

render() {
  local name="$1" src="$DIR/$2" out="$DIR/$3"
  [ -f "$src" ] || { echo "fehlt: $src" >&2; exit 1; }
  echo "==> $name"
  "$CHROME" --headless --disable-gpu --no-sandbox \
    --no-pdf-header-footer --run-all-compositor-stages-before-draw \
    --virtual-time-budget=10000 \
    --print-to-pdf="$out" "file://$src" 2>/dev/null
  echo "    $(basename "$out")  ·  $(du -h "$out" | cut -f1)"
}

case "${1:-alle}" in
  projekt) render "Plakat 1 · Das Projekt"       poster-1-projekt.html        Plakat-1-Projekt.pdf ;;
  valley)  render "Plakat 2 · Das Uncanny Valley" poster-2-uncanny-valley.html Plakat-2-Uncanny-Valley.pdf ;;
  alle)    render "Plakat 1 · Das Projekt"       poster-1-projekt.html        Plakat-1-Projekt.pdf
           render "Plakat 2 · Das Uncanny Valley" poster-2-uncanny-valley.html Plakat-2-Uncanny-Valley.pdf ;;
  *)       echo "Unbekannt: $1  (projekt | valley | alle)" >&2; exit 1 ;;
esac
