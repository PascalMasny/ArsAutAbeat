# Plakate

Zwei Ausstellungsplakate im Design der Installation. Erstfassung für die
Lange Kunstnacht Landsberg, 19. September 2026.

| Datei | Inhalt |
|---|---|
| `poster-1-projekt.html` | Was das Projekt ist: die Frage, der Ablauf für Besucher, ARS/ABEAT |
| `poster-2-uncanny-valley.html` | Das Uncanny Valley, wie wir es erzeugen, und was wir mit den Daten vorhaben |

## Bauen

```bash
./build.sh            # beide
./build.sh projekt    # nur Plakat 1
./build.sh valley     # nur Plakat 2
```

Gerendert wird mit Chrome oder Brave im Headless-Modus. Das Ergebnis liegt als
`Plakat-1-Projekt.pdf` und `Plakat-2-Uncanny-Valley.pdf` daneben und ist auch
eingecheckt — für den Druck reicht die PDF, das Bauen braucht man nur nach
Änderungen.

## Format

Gesetzt ist **DIN A1 hoch (594 × 841 mm)** über `@page` in `poster.css`. Weil
die A-Reihe durchgehend im Verhältnis 1:√2 steht, skaliert dieselbe Datei
verlustfrei auf A0 oder A2 — im Druckdialog „auf Seitengröße skalieren" wählen.
Alle Maße im Stylesheet sind in Millimetern, damit das aufgeht.

## Gestaltung

Farben und Schriften sind aus `ars_aut_abeat/frontend/src/index.css`
übernommen, damit Plakat und Bildschirm dieselbe Sprache sprechen: Tinte
`#1C1410`, Pergament `#F4E8D0`, Gold `#C9A961`, Burgunder `#6B2C2C`, dazu
Cinzel für Versalien und Cormorant Garamond für den Fließtext.

Zwei Eigenheiten, die beim Druck sonst wieder hochkommen:

- **Schriften stecken als Base64 in `fonts.css`.** Nichts wird aus dem Netz
  nachgeladen, das PDF ist überall identisch. Die Datei stammt aus
  `docs/pdf-theme/` und enthält nur Cinzel und Cormorant Garamond.
- **Keine exotischen Glyphen.** Die Zierlinie war ursprünglich `❧` (U+2767) —
  das Zeichen fehlt in beiden Schriften. Am Bildschirm springt ein Systemfont
  ein, im PDF mit ausschließlich eingebetteten Schriften nicht: dort standen
  Tofu-Kästchen. Das Ornament ist deshalb in CSS gezeichnet. Aus demselben
  Grund trägt `.title` keinen `text-shadow` mehr — Chrome rastert den
  Weichzeichner beim PDF-Export in eine Kachel mit sichtbarer Bounding-Box.

## Bilder

`assets/` enthält Ausschnitte aus tatsächlich erzeugten Sequenzen, nicht aus
Platzhaltern — Johannes Vermeer, *Schlafendes Mädchen* (1657), Met-Objekt
437878. Plakat 1 zeigt das ganze Gemälde in den Stufen 0, 5 und 10, Plakat 2
denselben Kopf im Ausschnitt über fünf Stufen.

Die Zahlen auf Plakat 2 sind echt: 68 Besucher der ersten Ausstellung, für die
ein Bruchpunkt gemessen wurde. Bei einem neuen Datenstand die Balken in
`poster-2-uncanny-valley.html` nachziehen — Abfrage:

```bash
sqlite3 ars_aut_abeat/data/gallery.db \
  "select breaking_index, count(*) from viewings
   where breaking_index is not null group by breaking_index order by 1;"
```
