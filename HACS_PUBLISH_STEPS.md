# HACS Default Store Veröffentlichung — Schritt-für-Schritt

## Voraussetzungen
- `gh` CLI installiert (`brew install gh` / `sudo apt install gh`)
- `gh auth login` ausgeführt

---

## Schritt 1: Branch mergen

```bash
cd ha-rejuvenation-bed
git checkout main
git merge claude/add-hacs-marketplace-QELT1
git push origin main
```

## Schritt 2: GitHub Release erstellen

```bash
gh release create v0.5.4 \
  --title "v0.5.4" \
  --notes "$(cat <<'EOF'
## Rejuvenation Bed v0.5.4

Biorhythm-basierte Wasserbett- & Heizmatten-Steuerung für Home Assistant.

### Highlights
- Thermische Batterie — Sensor zeigt Ladezustand des Wärmespeichers
- Bett-Volumen konfigurierbar (100–1200 L)
- Bedtime Learning — System lernt Einschlafzeiten
- Solar-Schwelle konfigurierbar (100–2000 W)
- Strompreis einstellbar mit dynamischem Sensor-Override
- Brand-Assets für HACS Store

### Platforms
- Climate (Thermostat)
- Sensor (Daten)
- Binary Sensor (Status)
- Switch (Modi)

### Vollständiger Changelog
Siehe [CHANGELOG.md](https://github.com/Chance-Konstruktion/ha-rejuvenation-bed/blob/main/CHANGELOG.md)
EOF
)"
```

## Schritt 3: Repository Description & Topics setzen

```bash
gh repo edit Chance-Konstruktion/ha-rejuvenation-bed \
  --description "Biorhythm-based waterbed & heating pad control for Home Assistant" \
  --add-topic "home-assistant,hacs,custom-integration,waterbed,climate,homeassistant-integration,smart-home"
```

## Schritt 4: PR an hacs/default einreichen

```bash
# 1. Fork erstellen
gh repo fork hacs/default --clone

# 2. Branch erstellen
cd default
git checkout -b add-rejuvenation-bed

# 3. Repo zur integration-Liste hinzufügen (alphabetisch!)
#    Öffne die Datei "integration" und füge hinzu:
#    "Chance-Konstruktion/ha-rejuvenation-bed"
#    WICHTIG: Alphabetisch einsortieren (nach dem C...)

# 4. PR erstellen
gh pr create \
  --repo hacs/default \
  --title "Add Chance-Konstruktion/ha-rejuvenation-bed" \
  --body "$(cat <<'EOF'
## New default repository

**Repository:** https://github.com/Chance-Konstruktion/ha-rejuvenation-bed
**Category:** Integration

### Description
Biorhythm-based waterbed and heating pad control for Home Assistant.
Supports dual-zone climate control, solar energy integration, sleep scoring,
presence detection, and auto-calibration.

### Checklist
- [x] I am the owner of the repository
- [x] The repository has a valid `hacs.json`
- [x] The repository has a valid `manifest.json`
- [x] The repository has brand assets (`icon.png`)
- [x] The repository has at least one release
- [x] The repository is not archived
- [x] The integration does not override a core integration
EOF
)"
```

## Schritt 5: Warten

- Automatische Checks laufen auf dem PR
- Falls Checks fehlschlagen: Probleme beheben und erneut pushen
- Review dauert aktuell **mehrere Monate**
- Bis dahin können Nutzer das Repo als **Custom Repository** in HACS hinzufügen

---

## Sofort nutzbar (ohne HACS Default Store)

Nutzer können dein Repo jetzt schon verwenden:
1. HACS öffnen → 3-Punkt-Menü → "Custom repositories"
2. URL eingeben: `https://github.com/Chance-Konstruktion/ha-rejuvenation-bed`
3. Kategorie: "Integration"
4. "ADD" klicken → dann in HACS nach "Rejuvenation Bed" suchen
