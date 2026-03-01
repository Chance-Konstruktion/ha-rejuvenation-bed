# Changelog

Alle Änderungen am Rejuvenation Bed Projekt.

## [0.1.0-rc] - 2026-02-21

### Erstveröffentlichung (Release Candidate)

Erster öffentlicher Release nach intensiver Entwicklungs- und Testphase auf einem echten 2×2m Dual-Kern Wasserbett.

### Kern-Features
- **22 Module** mit ~9.500 Zeilen Python
- **Biorhythmus-Kurve** mit Chronotyp-Anpassung (Lerche/Normal/Eule)
- **Wecker-Integration** – Fest, Handy-Alarm oder Hybrid
- **Saisonale Anpassung** via Außentemperatur
- **Dual-Zone** – Zwei getrennte Heizzonen
- **Bilingual** – Deutsch und Englisch

### Energie-Management
- **Solar-Boost** – PV-Überschuss als thermische Batterie
- **Tarifmodus** – Dynamische Strompreise
- **Energie-Tracking** – kWh, Heizstunden, Ø-Verbrauch, Ersparnis vs. Klassisch

### Intelligenz
- **Präsenz-Erkennung v3** – Varianz-basiert (σ > 0.04°C), kalibriert auf 126.771 Datenpunkte
- **Auto-Kalibrierung** – Lernt Schwellwerte in 3–5 Tagen
- **Drift-Korrektur** – Passt sich nach Erstkalibierung saisonal an (EMA α=0.15)
- **Ausreißer-Filter** – ESP-Glitches und Sensor-Boot werden ignoriert
- **Isolations-Erkennung 2.0** – Kalibriert auf echte Messdaten (4.592 Datenpunkte)
  - Heizungs-Korrektur: −0.4°C wenn Heizung aktiv (verhindert Fehlalarme)
  - 30-Minuten-Mittelwert statt Einzelmessung
  - Schwellwerte: Δ < 0.15° = gut, Δ < 0.25° = mäßig, Δ > 0.40° = offen
- **Schwitz-Erkennung 2.0** – Kreuzkorrelation Temperatur × Feuchtigkeit
- **Schlaf-Score** – 0–100 mit optionaler CO₂-Gewichtung (25%)
- **CO₂-Sensor** – Im Setup und Options-Flow konfigurierbar

### Sicherheit
- **Überhitzungsschutz** – Max 36°C, Fail-Safe bei Sensor-Ausfall
- **Startup-Grace-Period** – 3 Minuten Geduld nach HA-Restart für ESP-Boot
- **Anti-Short-Cycle** – Relay-Schutz (umgangen bei Boost/Krank-Modus)
- **Kalibrierung überlebt HA-Neustarts** – Auto-Save alle 50 Samples
- **Persistente Energiezähler** – kWh und Heizstunden gehen nicht verloren

### Modi
- **Boost** – Schnellheizen 60 Min (umgeht Anti-Short-Cycle)
- **Krank-Modus** – Konstante Temperatur für konfigurierbare Tage
- **Urlaub** – Minimale 24°C Haltetemperatur
- **Eco** – Tarifbasiertes Heizen

### Bugfixes (aus Entwicklungsphase)
- Time-Parser: HH:MM:SS Format (HA TimeSelector) wird korrekt geparst
- Options-Flow: Zone-Settings werden als Flat-Keys korrekt gelesen
- CO₂-Sensor: Aus Options UND Config lesbar
- duty_cycle KeyError behoben (SafetyManager gibt Key nicht zurück)
- Sensor-Ausfall meldet nicht mehr sofort nach HA-Restart (Grace-Period)
- Boost/Krank-Modus schalten jetzt sofort (Anti-Short-Cycle umgangen)
- Kalibrierungsdaten (Rohdaten) überleben HA-Neustarts

### Bekannte Einschränkungen
- Isolations-Erkennung funktioniert am besten wenn der SHT41 OBEN auf dem Kern liegt
- Schlaf-Score benötigt mindestens Hardware-Level C für aussagekräftige Werte
- Wearable-Anbindung (Schlafphasen) ist vorbereitet aber noch nicht aktiv
