# IBI-Adapter der Uhr

## Vertrag

Die Uhr verwendet `IbiQuelle` als austauschbare Grenze. Alle Sensoranbieter liefern
`IbiMesspunkt` (Zeitstempel des endenden Herzschlags, Intervall in Millisekunden,
optionale Signalqualität). Der HRV-Schätzer kennt keine Samsung-Klassen. Der
`FakeIbiQuelle` liefert deterministische Daten für Unit-Tests.

## Samsung Health Sensor SDK – benannte Integrationslücke

Das Repository enthält derzeit **nicht** die Samsung-Bibliothek
`samsung-health-sensor-api.aar`. Darum ist
`SamsungHealthSensorSdkIbiQuelle` bereits als fail-closed Adapter vorhanden,
aber die konkrete `SamsungHealthSensorSdkBruecke` ist noch nicht eingebunden.
Ohne Brücke bleibt IBI nicht verfügbar; es werden keine Pulswerte als IBI
umgedeutet und keine Schlafphase daraus erfunden.

### Fund-Notiz (Recherche 16.11.2026, Kennung zc-1611s)

Was IBI auf der Galaxy Watch 4 liefern kann und was ohne Partner-Zugang geht:

1. **IBI kommt real-time nur aus dem Samsung Health Sensor SDK.** Der
   kontinuierliche Heart-Rate-Tracker des SDK liefert pro Datenpunkt neben der
   Herzfrequenz 0–4 IBI-Werte mit je einem Güte-Status
   (`ValueKey.HeartRateSet.HEART_RATE_LIST`, `IBI_LIST`, `IBI_STATUS_LIST`;
   Verbindung über `HealthTrackingService`, Tracker
   `HealthTrackerType.HEART_RATE_CONTINUOUS`). Wear OS Health Services (der
   bestehende Puls-Kanal der App) und die alte Android-Sensor-API liefern nur
   BPM, keine RR-Intervalle; Health Connect läuft nicht auf Wear OS.
2. **Die AAR wird nur an registrierte Partner verteilt.** `samsung-health-sensor-api.aar`
   ist nicht öffentlich herunterladbar; Zugang gibt es erst nach Samsung-Konto,
   Partner-Anfrage und Freischaltung. Ohne AAR kann die Brücke weder kompiliert
   noch getestet werden — darum bleibt sie in dieser Sitzung bewusst
   **ungeschrieben**; spekulativer SDK-Code, der nie kompiliert war, wäre eine
   Täuschung.
3. **Der Entwickler-Modus umgeht nur die Laufzeit-Politik, nicht den Download-Regelkreis.**
   Health Sensor Service zeigt unter Einstellungen → Apps → Health Sensor
   Service (Titelbereich ~10× antippen) einen Entwickler-Modus, der Messungen
   mit einer *anderen Signatur* als der registrierten Partner-App erlaubt —
   also Entwicklung/Debugging **ohne Partnerfreigabe**. Samsung verlangt für
   den Vertrieb weiterhin die Partner-Freischaltung (Paketkennung + SHA-256
   Signatur). Ohne Freischaltung oder Entwickler-Modus meldet der Service
   `SDK_POLICY_ERROR`.
4. **Hintergrund-Vorbehalt:** community-Berichte zeigen, dass IBI bei
   ausgeschaltetem Display unzuverlässig/geringwertig ausfallen kann; für eine
   ganze Nacht im Entwickler-Modus ist das **nicht belegt** und muss auf der
   echten Watch 4 geprüft werden. Der Brücken-Entwurf muss deshalb
   `IBI_STATUS` in `signalQuality` übersetzen und die vorhandenen
   Güte-Gates (Signalgüte ≥ 0,8) weiter rechnen lassen.
5. **Phasen ohne Partner-Zugang:** Samsung Health liefert vierstufige
   Schlafphasen aus seiner eigenen Messung; lesbar nur auf dem **Smartphone**
   (Health Connect `SleepSessionRecord.stages` bzw. Samsung Health Data SDK,
   `HealthConstants.SleepStage`) — genau dieser Weg ist bereits der
   Referenz-Abgleich in `watch/phone`. Auf der Uhr selbst ersetzt bis auf
   Weiteres der **grobe Puls+Bewegungs-Schätzer** (siehe unten) den IBI-Weg.

Schritte, um die Lücke zu schließen:
1. Mit Samsung-Konto (Chris) Partner-Anfrage für das Health Sensor SDK stellen
   und die `samsung-health-sensor-api.aar` beziehen (Lizenz verbietet das
   Einchecken der AAR — sie bleibt lokal unter `watch/app/libs/`).
2. Konkrete SDK-Version und minimale Health-Sensor-Service-Version festnageln.
3. `SamsungHealthSensorSdkBruecke` gegen die AAR kompilieren: Capability
   prüfen (`HEART_RATE_CONTINUOUS`), Tracker abonnieren, Start/Stopp explizit
   und widerrufbar, `IBI_STATUS` → `signalQuality` (0..1), IBI in
   Millisekunden → `IbiMesspunkt` → `ibi_sample`.
4. Entwickler-Modus auf der Watch 4 einschalten und License bestätigen; dann
   auf der echten Uhr testen (Emulator kann diesen Sensorpfad nicht belegen).
5. Eine Nacht mit Schalter an und Abgleich gegen die Health-Connect-Referenz
   auf dem Smartphone (lokal, keine Rohdaten ins Repo).

Quellen (abgerufen 16.11.2026):
- [Samsung Health Sensor SDK – Introduction](https://developer.samsung.com/health/sensor/guide/introduction.html) (IBI im kontinuierlichen Heart-Rate-Tracker, Watch 4+, kein Emulator)
- [Samsung Health Sensor SDK – Getting Started](https://developer.samsung.com/health/sensor/guide/getting-started.html) (AAR-Einbindung)
- [Samsung Health Sensor SDK – Developer Mode](https://developer.samsung.com/health/sensor/guide/developer-mode.html) (Test mit anderer Signatur, nicht für Endnutzer)
- [Samsung Health Sensor SDK – Process/App verification](https://developer.samsung.com/health/sensor/process.html) (Partner-Freischaltung, `SDK_POLICY_ERROR`)
- [Heart Rate Data Transfer Code Lab](https://developer.samsung.com/codelab/health/heart-rate-data-transfer.html) (API-Form: `HealthTrackingService`, `HEART_RATE_CONTINUOUS`, `IBI_LIST`/`IBI_STATUS_LIST`)
- [Stack Overflow – IBI im Hintergrund](https://stackoverflow.com/questions/79462951/samsung-health-sensor-api-collecting-ibi-data-in-background-on-galaxy-watch) (Güte-Vorbehalt bei ausgeschaltetem Display)
- [Samsung Health Data SDK – `HealthConstants.SleepStage`](https://developer.samsung.com/health/android/data/api-reference/com/samsung/android/sdk/healthdata/HealthConstants.SleepStage.html) (Phasen der Samsung-Health-Referenz, Smartphone-Seite)

## Grobe Ersatz-Schätzung aus Puls + Bewegung

Solange die Brücke fehlt, erzeugt `PulsBewegungsEstimator` (Version
`puls-bewegung-grob-0.1`) eine **grobe Schätzung** nur aus Herzfrequenz-Mittel,
Streuung und Schritt-Deltas des letzten vollständigen 30-Minuten-Fensters. Sie
ist hinter demselben Versuchs-Schalter ab Werk AUS, liefert `unknown` bei
unzureichender Puls-Abdeckung oder fehlenden Bewegungsdaten und wird in der UI
als „grobe Schätzung“ beschriftet. Sie ersetzt keine IBI/HRV-Analyse und ist
nicht validiert; beim Start der Messung benennt das Protokoll (Art `IBI`)
jederzeit den Zustand der echten IBI-Quelle, damit kein stiller Leerlauf
entsteht.

## Datengrenze

**Standard bleibt lokal.** IBI, HRV und Bewegungsdaten verbleiben auf der Uhr,
bis der Nutzer sie ausdrücklich freigibt. Zwei Sende-Wege existieren, getrennt
und je mit eigener Regel:

1. **Wear Data Layer an das gekoppelte Smartphone** (M2-Abgleich): nach
   ausdrücklichem Tastendruck ausschließlich abgeleitete Schlafphasenwerte
   (Phase, Zeitstempel, Konfidenz, Abdeckung und Algorithmusversion).
   IBI-/BPM-/Schritt-Rohwerte werden über diesen Weg weiterhin **nie**
   übertragen. Health-Connect-Referenzdaten verbleiben lokal auf dem
   Smartphone.
2. **Lokaler Home-Assistant-Webhook** (seit dem Schalter „Was geht an Home
   Assistant“): die Stellung „Nur Schlafphase“ sendet nur das Ergebnis —
   Phase, Zeitleiste und Zusammenfassungen. Die Stellung „Gesamtdaten“ sendet
   zusätzlich die Messreihen (Puls, IBI, Bewegungsfenster, Plattform-Status)
   je 5 Minuten als Paket — aber **nur** über den lokalen Webhook der einmalig
   in der App gespeicherten Adresse, nur im Heimnetz, nie Cloud, nie ein
   fremder Dienst; die Uhr folgt keiner Umleitung. Beim Umschalten zeigt die
   App einmal deutlich, welche Werte übertragen werden. Kanäle, die die Uhr
   nicht liefert (Atemfrequenz, SpO2, Hauttemperatur), werden nie erfunden.

Keine Rohdaten, echten Nächte, Gerätekennungen oder Hausdaten gehören in Git.
Tests verwenden nur synthetische Werte; das Debug-Protokoll der Uhr nennt
Anzahlen und Gründe, keine Messwerte und keine Adresse. Eine Wellness-Schätzung
ist keine medizinische Messung.
