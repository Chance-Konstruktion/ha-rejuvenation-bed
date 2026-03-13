# Review: Weitere Verbesserungen (neben Config-Flow-Check)

## 1) Entity-Erzeugung konsistent mit `options`
- Einige optionale Sensor-/Switch-Entitäten werden nur anhand `config_entry.data["global"]` erzeugt.
- Empfehlung: überall auch `config_entry.options` berücksichtigen, damit nachträgliche Änderungen im Options-Flow sofort konsistent sind.

## 2) Service-Lifecycle bei mehreren Config-Entries
- Services werden pro Entry registriert/entfernt.
- Empfehlung: Registrierung einmal pro Domain oder Refcount-basiert, damit Multi-Entry robust bleibt.

## 3) Toter Code in Device-Info-Helfern entfernen
- In mehreren Plattform-Dateien existieren unerreichbare Blöcke nach `return`.
- Empfehlung: bereinigen, um Fehlinterpretationen zu vermeiden.

## 4) Lint-/Qualitätsrunde (ruff)
- Unused imports/Variablen, einzelne Stilfehler und ein bare `except`.
- Empfehlung: saubere `ruff`-Runde inkl. kleiner Safe-Fixes.

## 5) Optionale Dashboard-Strategie standardisieren
- Für die UI-Vorlage sollten „optionale“ Karten möglichst über `conditional` abgebildet werden.
- Empfehlung: zusätzlich eine zweite Datei mit nur Kern-Entitäten (ultrastabil) und eine „erweiterte“ Datei (alle optionalen Features).
