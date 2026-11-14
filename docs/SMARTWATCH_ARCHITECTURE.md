# Galaxy Watch Companion – Architektur und Umsetzungsplan

**Stand: M2-Vorbereitung – lokaler Puls-/Schrittkanal plus deskriptive 30-Minuten-Merkmale.** Eine vierstufige Schlafphasen-Klassifikation und HA-Netzwerkbetrieb sind noch nicht produktiv implementiert.

## Ausgangslage im Rejuvenation-Bed-Repository

Die Integration besitzt bereits:
- `SleepStageResolver` mit den normalisierten Zuständen `awake`, `light`, `deep`, `rem`, `unknown`.
- ein vorhandenes Options-Flow-Feld `sleep_stage_entity`.
- einen `TemperatureCalculator`, der diesen Sensor bereits lesen und in die vorhandene Kurve einbeziehen kann.

Die Watch darf daher **keine zweite Heizungs- oder Sicherheitslogik** implementieren. Sie liefert Schlafinformationen und bedient die bestehende Home-Assistant-Climate-Entity.

## Zielarchitektur

```text
Galaxy Watch 4 / Wear OS
  ├─ Sensor capability check
  ├─ Sensor adapter (Health Services / Samsung Health Sensor SDK)
  ├─ lokale Feature-Extraktion + Schlafphasenmodell
  ├─ Watch UI: Schlaf | Thermostat
  └─ Pairing + authentisierte lokale Verbindung
                │
                ▼
Home Assistant – Rejuvenation Bed
  ├─ lokale Discovery / Pairing / Gerätewiderruf
  ├─ Sensor: sensor.rejuvenation_bed_watch_sleep_stage
  ├─ bestehender SleepStageResolver
  └─ bestehende Climate-Entity + Safety-Manager
```

## Galaxy-Watch-Sensorik

Health Services liefert passive Hintergrunddaten gebündelt und in geräteabhängigen Abständen. Die Anwendung darf keine feste Abtastrate unterstellen. Der aktive `MeasureClient` ist für kurzzeitige Live-Messungen bei sichtbarer App gedacht, nicht als unbegrenzte Hintergrundaufnahme. Für längere Hintergrundphasen wird `PassiveMonitoringClient` verwendet und die Qualität anhand tatsächlicher Zeitstempel bewertet. (Quelle: [Android Health Services – background monitoring](https://developer.android.com/health-and-fitness/health-services/monitor-background) und [Wear OS compatibility](https://developer.android.com/health-and-fitness/health-services/compatibility).)

Erfasst werden passive Herzfrequenz-Samples und – sofern vom Gerät unterstützt und vom Nutzer freigegeben – Schritt-Deltas. Schritt-Deltas sind nur ein grober Bewegungsindikator; sie ersetzen keine rohen Beschleunigungsdaten/Actigraphie. Health Services kann auf unterstützten Geräten außerdem einen groben Plattformstatus `ASLEEP` oder `PASSIVE` (wach, nicht trainierend) liefern. Dieser ist ausdrücklich keine REM-/Tief-/Leichtschlaf-Erkennung. Interbeat-Intervalle (IBI), Bewegungsdaten und optionale PPG-/Temperaturmerkmale bleiben zusätzliche Sensoradapter. Die App prüft zur Laufzeit sowohl `supportedDataTypesPassiveMonitoring` als auch `supportedUserActivityStates` des konkreten Geräts. Der passive Aktivitätsstatus wird nur angefordert, wenn `USER_ACTIVITY_ASLEEP` tatsächlich unterstützt wird und der Nutzer `ACTIVITY_RECOGNITION` freigibt. Keine Messrate darf angenommen werden, die die Plattform nicht garantiert.

**Bereits implementiert:** Die App fragt zur Laufzeit die passiven Health-Services-Capabilities für `HEART_RATE_BPM`, `STEPS` und `USER_ACTIVITY_ASLEEP` ab. Messung und Statusereignisse beginnen erst nach Berechtigungsfreigabe und Nutzerstart. Die Plattform liefert dabei nur einen groben Schlaf-/Wach-Status.

Die lokale Feature-Extraktion verarbeitet vollständige 30-Minuten-Fenster mit 5-Minuten-Buckets und erstellt zunächst nur deskriptive Merkmale. Zusätzlich speichert die App optionale `UserActivityInfo`-Ereignisse mit `stateChangeTime`; die Plattform kann die Meldung verzögert liefern, deshalb wird der tatsächliche Wechselzeitpunkt verwendet:
- Plattformstatus `ASLEEP` wird als `schlafend` abgebildet.
- `PASSIVE` und `EXERCISE` werden als `wach` abgebildet.
- `UNKNOWN`, unbekannte Werte oder veraltete Ereignisse werden als `unbekannt` behandelt.
- Die Anzeige bleibt vom vierstufigen Schlafphasen-State getrennt.
- Herzfrequenzverlauf: Mittelwert, Median, Minimum, Maximum und Standardabweichung
- Verteilung der eingetroffenen Puls-Samples über 5-Minuten-Buckets (keine Behauptung kontinuierlicher Sensorabdeckung)
- Schritt-Deltas nach Ende des Health-Services-Intervalls (die App verteilt gebündelte Schritte nicht künstlich auf einzelne Minuten)
- IBI-/HRV-Merkmale, wenn Werte und Signalqualität genügen
- Bewegungsintensität und Bewegungsvarianz
- optionale Sensor-/Tragezustandsinformationen

Ein echtes Schlafphasenmodell wird erst nach Validierung gegen eine geeignete Referenz aktiviert. Bis dahin ist `unknown` der einzig korrekte Ausgabewert. Jede Schätzung muss Zeitstempel, Algorithmusversion, Datenabdeckung und Konfidenz enthalten. Veraltete oder schwache Daten dürfen die Temperaturkurve nicht überschreiben.

Das ist Wellness-Tracking, keine medizinische Diagnostik. Eine Smartwatch ersetzt kein EEG.

### Samsung SDK

Das Samsung Health Sensor SDK unterstützt Galaxy Watch4 und spätere Modelle. Der Zugriff auf bestimmte Sensorfunktionen setzt Partnerfreigabe bzw. aktivierten Developer Mode voraus. Der Developer Mode ist nur für Entwicklung/Debugging gedacht, nicht für die Verteilung. Daher bekommt die App einen austauschbaren Sensor-Adapter; die Integration darf nicht vom Samsung-SDK abhängen.

## Verbindung ohne langlebigen Bearer-Token

Ein vierstelliger Code ist kein sicheres dauerhaftes Passwort. Er dient ausschließlich als Short Authentication String (SAS) für die erstmalige gegenseitige Bestätigung.

Vorgesehener Ablauf:
1. Home Assistant kündigt einen lokalen Pairing-Endpunkt per mDNS/DNS-SD an.
2. Watch und HA erzeugen frische ephemere ECDH-Schlüsselpaare und Nonces.
3. Beide Seiten berechnen den SAS aus dem vollständigen Handshake-Transcript. Beide Geräte zeigen denselben vierstelligen Wert.
4. Der Nutzer bestätigt den Wert auf beiden Seiten. Unterschiedliche Codes, Zeitüberschreitung und zu viele Versuche brechen den Vorgang ab.
5. Die Watch erstellt ein Geräteschlüsselpaar im Android Keystore; der private Schlüssel ist nicht exportierbar. Home Assistant speichert nur den öffentlichen Schlüssel und Metadaten des Geräts.
6. Folgeaufrufe werden mit dem Geräteschlüssel signiert; Nonces, Zeitfenster und Request-Hashes schützen vor Replay.
7. Der Nutzer kann ein Gerät in Home Assistant jederzeit widerrufen.

Die kurze PIN darf nie als wiederverwendbarer Zugangsschlüssel oder alleiniger API-Schutz dienen. Die konkrete Protokollversion muss mit negativen Tests (MITM/SAS mismatch, Replay, Expiry, Brute Force, Revocation) geprüft werden. Lokales Netz bedeutet nicht automatisch vertrauenswürdiges Netz.



### M1 – lokaler Herzfrequenzkanal

Die App registriert nach expliziter Nutzeraktion `DataType.HEART_RATE_BPM` über `PassiveMonitoringClient.setPassiveListenerServiceAsync`. Health Services liefert im Hintergrund gebündelte `SampleDataPoint<Double>`-Werte. Für die zeitliche Reihenfolge wird der Messzeitpunkt aus `timeDurationFromBoot` und dem System-Boot-Zeitpunkt berechnet – nicht der Empfangszeitpunkt verwendet.

Der `PassiveHeartRateService` schreibt die Werte in einen privaten SharedPreferences-Ringpuffer auf der Uhr (maximal 10 Stunden / 2.500 Messpunkte). Es findet kein Upload statt. Die App bietet eine Stop-Funktion, die die Health-Services-Registrierung entfernt und den lokalen Puffer löscht. Bei Berechtigungsverlust wird der Status als `permission_lost` markiert.

Die App fordert Berechtigungen erst nach Nutzeraktion an. Unter API 33–35 sind `BODY_SENSORS` und `BODY_SENSORS_BACKGROUND` zwei getrennte Berechtigungen; unter API 36+ `READ_HEART_RATE` und `READ_HEALTH_DATA_IN_BACKGROUND`. Die Registrierung ist nicht reboot-persistent – M1 verlangt nach einem Neustart eine erneute Aktivierung.

**Grenze:** Das ist ein Sensorkanal plus deskriptive Feature-Extraktion, keine Schlafphasenanalyse. Schritt-Deltas sind keine Roh-Actigraphie. Es gibt weiterhin keine vierstufige Klassifikation, keine IBI-/PPG-Merkmale und keinen HA-Transport. Der Schlafphasen-State bleibt `unknown`.

## Home-Assistant-Vertrag

Ziel-Entity: `sensor.rejuvenation_bed_watch_sleep_stage`

Erlaubte Zustände (kompatibel mit dem bestehenden Resolver):

| State | Bedeutung |
|---|---|
| `awake` | Wach |
| `light` | Leichtschlaf |
| `deep` | Tiefschlaf |
| `rem` | REM |
| `unknown` | Keine belastbare aktuelle Schätzung |

Optionale Attribute: `confidence`, `measured_at`, `algorithm_version`, `sample_coverage`, `sensor_status`.

Der Sensor muss bei Verbindungsverlust, leerem Akku, nicht getragenem Gerät oder veralteten Messwerten auf `unknown` fallen. Der Nutzer verbindet ihn danach über das bereits vorhandene `sleep_stage_entity`-Feld.

### Thermostat

- Ist-Temperatur, Solltemperatur und Betriebsmodus kommen aus dem ausgewählten HA-Climate-Entity.
- Änderungen werden als Climate-Service-Aufruf an Home Assistant gesendet.
- Watch-Code spricht niemals ein Heizungsrelais direkt an.
- Temperaturgrenzen, Rampen, Anti-Short-Cycle und Not-Aus bleiben vollständig in Rejuvenation Bed.

## Watch UX

- dunkler AMOLED-Hintergrund, bernsteinfarbene Bettkontur, keine bunten Vollflächen.
- zwei horizontal wischbare Seiten: Schlafanalyse und Thermostat.
- große Touch-Ziele, wenige Informationen, hoher Kontrast und kurze Labels.
- Ist-Temperatur, Solltemperatur und Modus auf einer Seite.
- Offline-/Sensorstatus jederzeit sichtbar.
- Ein Temperaturbefehl gilt erst nach HA-Bestätigung als erfolgreich.

## Lieferplan

### M0 – Grundgerüst
Wear-OS-Projekt, Amber-UI, zwei Seiten, normierte Datenmodelle, Tests und Health-Services-Capability-Check für passiven Puls.

### M1 – Sensorzugriff (erster Teil umgesetzt)
Passiver Health-Services-Listener für Herzfrequenz und optionale Schritt-Deltas, expliziter Berechtigungsfluss, lokale begrenzte Puffer und Stop-/Löschfunktion sind angelegt. Deskriptive Puls-/Schritt-Merkmalsfenster sind implementiert. Offen bleiben rohe Beschleunigungsdaten, IBI/PPG, Trage-/Batteriestatus und Laufzeitvalidierung auf echter Watch-Hardware.

### M2 – Lokale Analyse (Vorbereitung umgesetzt)
Deskriptive 30-Minuten-Feature-Fenster für Puls und Schritt-Deltas sind vorhanden. Auf unterstützten Geräten wird zusätzlich der grobe Health-Services-Status schlafend/wach gespeichert. Es fehlt weiterhin ein validiertes REM-/Leicht-/Tiefschlaf-Modell. Der UNKNOWN-Fallback bleibt aktiv, bis Referenzdaten und ein reproduzierbares Validierungsverfahren vorliegen.

### M3 – Sichere HA-Verbindung
mDNS, ECDH/SAS, Android-Keystore-Geräteschlüssel, Replay-Schutz, Rate-Limits und Widerruf.

### M4 – HA-Integration
Watch-Sensor registrieren, `sleep_stage_entity` verbinden, Climate-Daten lesen und Solltemperatur kontrolliert setzen.

### M5 – Validierung
Tests auf echter Galaxy Watch 4, Akkulaufzeit, Messdatenqualität, Verbindungsabbrüche, Pairing-Sicherheit und komplette HA-CI.

## M0/M1/M2-Akzeptanzkriterien

- Eigenständiges Wear-OS-App-Modul liegt unter `watch/`.
- Schlaf- und Thermostatseite lassen sich durch Wischen wechseln.
- Amber-Bettkontur wird als App-Icon und in der Oberfläche verwendet.
- Unbekannte Werte werden auf `unknown` normalisiert.
- Schätzungen mit unzureichender Konfidenz gelten als nicht verwendbar.
- Platzhalter-Regler senden keine Befehle und sind eindeutig als Vorschau markiert.
- Passives Herzfrequenztracking startet erst nach Nutzerfreigabe und erforderlichen Berechtigungen.\n- Die Messpunkte werden nur lokal und begrenzt gespeichert; Stoppen beendet die Registrierung und löscht den Puffer.\n- Nach einem Geräte-Neustart wird keine alte passive Registrierung als aktiv angezeigt.\n- Schritt-Deltas werden als grober Aktivitätsindikator bezeichnet, nicht als Roh-Beschleunigungsdaten.
- Der optionale Plattformstatus wird als grober Schlaf-/Wach-Hinweis getrennt von `awake/light/deep/rem` dargestellt.
- Unvollständige Zeitfenster werden nicht ausgewertet; unbekannte oder unzureichende Daten erzeugen weiterhin kein Schlafstadium.
- Noch nicht implementierte Schlafphasen-/Netzwerkfunktionen werden in der UI nicht als verbunden dargestellt.
