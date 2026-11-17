# Rejuvenation Bed Watch

Eigenständige Wear-OS-Begleit-App für die Samsung Galaxy Watch 4 (Wear OS 3) und kompatible Wear-OS-Geräte.

## Status: M2-Vorbereitung – lokaler Puls-/Schrittkanal, Feature-Fenster und Plattform-Schlafstatus

Enthalten:
- Kotlin-App mit Jetpack Compose für Wear OS
- Oberfläche in der **Chance-Gestalt** aus dem eingebauten `chance-framework` (`chance-konstruktion/chance-framework`,
  Quellkopie unter `app/src/main/java/net/schanz/chance/`, Stand in `CHANCE_FRAMEWORK.txt`; dort nicht ändern, im
  Framework ändern und mit `werkzeug/einbauen.py` neu einbauen). Zwei Gesichter:
  - **Bett** (21–7 Uhr oder wenn die Uhr Schlaf meldet): nur gedimmter Bernstein auf Schwarz, kein Weiß, dünne
    Ziffern, keine leuchtenden Flächen.
  - **Sofa** (am Tag): warmes Weiß, kräftiger Bernstein, schwere Ziffern.
  Auf dem Debug-Blatt lässt sich das Gesicht fest wählen (auto → bett → sofa). App-eigene Regeln stehen in
  `ui/UhrRegel.kt` und sind in `UhrRegelTest` geprüft.
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
- lokale, private Speicherung (Puls: 14 Stunden / max. 45.000 Werte; Schritte: 14 Stunden / max. 4.000 Intervalle; Plattformstatus: max. 18 Stunden / max. 100 Statuswechsel)
- Stop-Funktion beendet die Registrierung, die aufgezeichneten Daten bleiben (#7); Löschen nur über die eigene Aktion „DATEN LÖSCHEN“ in der Info-Ebene (mit Rückfrage)
- lokale 30-Minuten-Merkmalsfenster mit Pulsstatistik, Sample-Bucket-Verteilung und Schritt-Deltas
- optionaler Health-Services-Plattformstatus `ASLEEP` / `PASSIVE` mit echtem Zustandswechsel-Zeitpunkt
- Unit-Tests für Zeitfenster, unvollständige Daten und Mindestdatenqualität

Noch **nicht** enthalten:
- rohe Beschleunigungssensor- oder IBI/PPG-Erfassung
- vierstufige Schlafphasen-Klassifikation oder eine validierte Schlafanalyse
- sicheres Pairing mit Home Assistant (M3 — heute nur der lokale Webhook ohne Bearer-Token)
- Live-Temperaturanzeige und Live-Steuerung

Die Schlafphase bleibt bewusst `unknown`. Der Plattformstatus ist nur ein grober Hinweis „schläft / wach“ und keine REM-/Tief-/Leichtschlaf-Erkennung. Er wird nur angezeigt, wenn das konkrete Gerät ihn unterstützt. Schritt-Deltas sind nur ein grober Bewegungsindikator, keine Rohdaten der Actigraphie. Herzfrequenz allein reicht ebenfalls nicht für eine belastbare Schlafphasenanalyse. Die lokale Feature-Extraktion weist daher nur Datenfenster aus und erzeugt ausdrücklich keine Schlafphase.

## HA-Übertragung — der Schalter „Was geht an Home Assistant“

Im Schlaf-Blatt (Info-Ebene) steht die HA-Übertragung mit zwei Stellungen:

- **„Nur Schlafphase“ (Standard)** — die Rohdaten bleiben auf der Uhr; an HA
  geht das Ergebnis: die laufende Phase während der Messung, der Nachtbericht
  beim Stopp (Phasen-Zeitleiste mit Quelle je Segment, Puls min/Ø/max,
  HRV-Kennzahlen aus IBI oder benannter Grund, Schritte gesamt).
- **„Gesamtdaten“** — zusätzlich alle Messreihen der Nacht (Puls, IBI, falls
  eine Quelle vorhanden ist, Bewegungsfenster, Plattform-Schlafstatus) je
  5 Minuten als Paket. Beim Umschalten zeigt die App einmal deutlich, welche
  Werte übertragen werden — und was nicht: Atemfrequenz, SpO2 und
  Hauttemperatur, denn die Uhr stellt diese Kanäle nicht bereit; erfunden
  wird nichts.

Regeln, durchgezogen:

- Gesendet wird **nur** über den lokalen Webhook der eigenen
  Home-Assistant-Instanz (`local_only`, Pfad steht am Sensor „Bett
  Nachtbericht“ als Attribut `annahme_pfad`). Die Adresse wird einmalig im
  Schlaf-Blatt eingetragen, App-privat gespeichert — nie im Protokoll, nie in
  einer Nutzlast. Nie Cloud, nie ein fremder Dienst; die Uhr folgt keiner
  Umleitung (ein 3xx bricht die Sendung ab, statt die Nutzlast anderswohin zu
  schicken).
- **Gesundheitsdaten verlassen das Haus nie — im Sender erzwungen:** vor
  jedem Senden wird der Host der Adresse aufgelöst und gewogen; erlaubt sind
  nur private bzw. Link-Local-Adressen (RFC 1918, 169.254/16, 127/8,
  fc00::/7, fe80::/10) und Namen auf `.local`. Jede andere Adresse — Cloud-
  URL, öffentlicher Name, Tippfehler — wird abgewiesen, **bevor** irgendein
  Byte gesendet wird („Adresse liegt nicht im Heimnetz – nichts gesendet“);
  nichts bleibt dafür in der Warteschlange hängen. Schon beim Speichern
  zeigt das Schlaf-Blatt den Hinweis „nicht im Heimnetz“, wenn die gewogene
  Adresse nicht reicht.
- Messen bleibt völlig unberührt — der Schalter wirkt nur auf das, was
  gesendet wird; alle Sendungen laufen auf einem eigenen Hintergrund-Faden.
- HA nicht erreichbar? Die Sendungen bleiben in einer Warteschlange auf der
  Uhr (app-privat, begrenzt) und werden beim nächsten Anstoß wieder versucht.
  Doppelungen sind unmöglich: jeder Eintrag trägt einen Schlüssel aus
  Zeitstempeln bzw. der Nacht-Kennung, HA fasst Punkte zusätzlich über ihren
  Zeitstempel zusammen.
- „DATEN LÖSCHEN“ leert auch die Warteschlange — Rohdaten-Kopien der Pakete
  leben nicht länger auf der Uhr als die Daten selbst.
- Das Protokoll (Art `HA`) nennt Nacht-Datum, Anzahlen und Gründe — nie
  Messwerte, nie die Adresse.

Einrichtung: Attribut `annahme_pfad` am Sensor `sensor.bett_nachtbericht`
lesen, die eigene Home-Assistant-Adresse davor setzen, einmalig im Schlaf-Blatt
unter „HA-ÜBERTRAGUNG“ speichern. Die Adresse muss im Heimnetz liegen (private
IP wie eine 192.168.x.x, eine `…​.local`-mDNS-Adresse oder eine IPv6-ULA) —
öffentlich auflösbare Adressen werden abgewiesen. Details und Schema:
`docs/NACHTBERICHT.md`.

## Datenschutz und Berechtigungen

Puls- und Schrittwerte werden nur lokal gespeichert. Ein Netzweg existiert
nur in Richtung des eigenen Home-Assistant-Webhooks und nur in der Stellung,
die der Schalter beschreibt (siehe oben). Das Debug-Protokoll hält je Lieferung von Health Services eine Zusammenfassung fest (Anzahl, Puls-Spanne min–max, Zeitspanne, Verzug) – nur auf der Uhr, App-privat in `files/debug/protokoll.txt` (höchstens ~96 kB) und im Logcat unter dem Tag `RBW`. Leeren über „LEEREN“ auf dem Debug-Blatt. Die App fordert Berechtigungen erst nach Nutzeraktion an:
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

Die Debug-Fassung ist mit einem festen Schlüssel signiert (`watch/debug.keystore`, Android-Standardwerte). Eine neue
CI-Fassung geht deshalb mit `adb install -r` über die alte, ohne Deinstallieren; Messdaten und Rechte bleiben.

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
