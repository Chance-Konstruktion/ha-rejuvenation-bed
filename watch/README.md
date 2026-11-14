# Rejuvenation Bed Watch

Eigenständige Wear-OS-Begleit-App für die Samsung Galaxy Watch 4 (Wear OS 3) und kompatible Wear-OS-Geräte.

## Status: M2-Vorbereitung – lokaler Puls-/Schrittkanal, Feature-Fenster und Plattform-Schlafstatus

Enthalten:
- Kotlin-App mit Jetpack Compose für Wear OS
- Oberfläche in der **Chance-Gestalt** (Vorbild: das Designbuch von ADL, `co-work/android-device-lab` → `DESIGN.md`):
  AMOLED-Schwarz, EIN Bernstein-Akzent `#D99130`, Zifferblatt mit 60 Minuten-Strichen, Status-Punkt mit Wort,
  ein Los-Knopf, Raum im 4er-Takt, Typo-Skala UHR 11/14/20 (+ Bühnenzahl 30). Die Gesetze stehen JVM-pur in
  `ui/GestaltRegel.kt` und sind in `GestaltRegelTest` geprüft.
- drei Blätter: **THERMO ‹ SCHLAF › DEBUG** (SCHLAF ist START; hoch/runter auf SCHLAF = Info-Ebene mit den
  30-Minuten-Fenstern und dem Plattform-Verlauf; die Krone scrollt)
- **Debug-Blatt** für die Sensor-Kette: Kanäle (passiv/live), Rechte, Registrierung, letzte Lieferung mit Verzug,
  Plattform-Schlafstatus, Live-Pulstest über den MeasureClient, Hardware-Sensorliste, Protokoll
- **Now Bar**: Während die Hintergrundmessung läuft, hält ein kleiner Vordergrunddienst eine laufende Aktivität
  (Ongoing Activity). One UI Watch zeigt sie in der Now Bar – bei „Now Bar-Stil: Nur Symbole“ als Bettkontur, bei
  „Symbole mit Text“ zusätzlich mit Kurztext (`misst` bzw. `62 bpm`, höchstens 10 Zeichen). Ein Tipp öffnet SCHLAF.
- Laufzeit-Capability-Check für passiven Puls-, Schritt- und optionalen Plattform-Schlafstatus
- Nutzerstart mit den erforderlichen Health-Services-Berechtigungen
- passiver Hintergrunddienst empfängt gebündelte Herzfrequenz- und Schritt-Deltas
- lokale, private Speicherung (Puls: 10 Stunden / max. 2.500 Werte; Schritte: 10 Stunden / max. 4.000 Intervalle; Plattformstatus: max. 18 Stunden / max. 100 Statuswechsel)
- Stop-Funktion beendet die Registrierung und löscht beide lokalen Datenpuffer
- lokale 30-Minuten-Merkmalsfenster mit Pulsstatistik, Sample-Bucket-Verteilung und Schritt-Deltas
- optionaler Health-Services-Plattformstatus `ASLEEP` / `PASSIVE` mit echtem Zustandswechsel-Zeitpunkt
- Unit-Tests für Zeitfenster, unvollständige Daten und Mindestdatenqualität

Noch **nicht** enthalten:
- rohe Beschleunigungssensor- oder IBI/PPG-Erfassung
- vierstufige Schlafphasen-Klassifikation oder eine validierte Schlafanalyse
- Pairing / Verbindung mit Home Assistant
- Live-Temperaturanzeige und Live-Steuerung

Die Schlafphase bleibt bewusst `unknown`. Der Plattformstatus ist nur ein grober Hinweis „schläft / wach“ und keine REM-/Tief-/Leichtschlaf-Erkennung. Er wird nur angezeigt, wenn das konkrete Gerät ihn unterstützt. Schritt-Deltas sind nur ein grober Bewegungsindikator, keine Rohdaten der Actigraphie. Herzfrequenz allein reicht ebenfalls nicht für eine belastbare Schlafphasenanalyse. Die lokale Feature-Extraktion weist daher nur Datenfenster aus und erzeugt ausdrücklich keine Schlafphase.

## Datenschutz und Berechtigungen

Puls- und Schrittwerte werden nur lokal gespeichert. Es gibt keinen Netzwerk-Upload. Das Debug-Protokoll hält je Lieferung von Health Services eine Zusammenfassung fest (Anzahl, Puls-Spanne min–max, Zeitspanne, Verzug) – nur auf der Uhr, App-privat in `files/debug/protokoll.txt` (höchstens ~96 kB) und im Logcat unter dem Tag `RBW`. Leeren über „LEEREN“ auf dem Debug-Blatt. Die App fordert Berechtigungen erst nach Nutzeraktion an:
- Herzfrequenz: `BODY_SENSORS` oder auf API 36+ `READ_HEART_RATE`
- Hintergrundmessung: `BODY_SENSORS_BACKGROUND` (API 33–35) oder `READ_HEALTH_DATA_IN_BACKGROUND` (API 36+)
- Schrittkanal und Plattform-Schlafstatus: `ACTIVITY_RECOGNITION`
- Now Bar: `FOREGROUND_SERVICE_HEALTH` (Manifest) und `POST_NOTIFICATIONS`; der Dienst startet nur mit erteiltem Pulsrecht

## Debuggen am PC

```bash
adb shell am start -n net.schanz.rejuvenationbed.watch/.MainActivity --es rbw.blatt DEBUG
adb shell run-as net.schanz.rejuvenationbed.watch cat files/debug/protokoll.txt
adb logcat -s RBW
```

`rbw.blatt` öffnet THERMO, SCHLAF oder DEBUG direkt (Vorschau-Tür wie bei ADL). Protokoll-Arten: `APP`, `FAEHIG`,
`KANAL`, `RECHT`, `REG` (Registrierung), `DATEN` (Lieferung, auch verworfene mit Grund), `PLATT` (Plattform-Schlafstatus
roh → gemappt), `LIVE`, `SENSOR`, `NOWBAR`.

Health Services liefert passive Messungen in geräteabhängig gebündelten Abständen. Die App setzt keine feste Sample-Frequenz voraus. Die 5-Minuten-Bucket-Belegung zeigt nur die Verteilung eingetroffener Samples, keine kontinuierliche Sensorabdeckung.

Passive Registrierungen überleben einen Geräte-Neustart nicht automatisch. Nach einem Neustart muss die Messung erneut in der App aktiviert werden.

## Build-Voraussetzungen

- JDK 17
- Android 17 SDK Platform 37.0 (Canary-Vorschau; Paketkennung `platforms;android-37.0`)
- Android Gradle Plugin 9.1.1
- Gradle 9.3.1
- Kotlin 2.4.21

Für den CI-Build wird API 37.0 über den SDK-Canary-Kanal installiert. Ein Kompatibilitäts-Symlink von `platforms/android-37` auf `platforms/android-37.0` gleicht den SDK-Verzeichnisnamen an die von AGP erwartete Compile-SDK-Kennung an. `targetSdk` bleibt bis zur gesonderten Android-17-Verhaltensprüfung auf API 36.
- echte Galaxy Watch 4 für Geräte- und Sensorprüfungen

Aus diesem Verzeichnis:

```bash
gradle :app:assembleDebug
gradle :app:testDebugUnitTest
```

## Architektur

Siehe [SMARTWATCH_ARCHITECTURE.md](../docs/SMARTWATCH_ARCHITECTURE.md).

## Sensor-SDK-Hinweis

Health Services stellt aggregierte Schritt-Deltas, keine rohen Beschleunigungskurven bereit. Für echte Actigraphie, IBI und PPG wird später ein zusätzlicher Sensoradapter benötigt. Samsung Health Sensor SDK kann dafür relevant sein, setzt für bestimmte Funktionen aber eine Samsung-Partnerfreigabe voraus.

## Versionsstand

M1/M2-Vorbereitung / 0.3.0 – lokale Feature-Extraktion, kein veröffentlichtes Schlaftracking.
