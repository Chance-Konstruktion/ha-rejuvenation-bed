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

Samsung dokumentiert IBI als Bestandteil des kontinuierlichen Heart-Rate-Trackers
des Health Sensor SDK. Das SDK wird als AAR importiert. Der Sensor-Service
unterstützt Galaxy Watch4 und spätere Wear-OS-Modelle; Emulatoren sind nicht
unterstützt. Für die Verteilung muss Samsung die Paketkennung und Signatur der
Partner-App freischalten. Der Developer-Modus ist nur für Entwicklung/Debugging
vorgesehen.

Voraussetzung für die nächste Integrationsstufe:
1. Samsung-AAR und dazugehörige Dokumentation von Samsung beziehen.
2. Konkrete SDK-Version und minimale Health-Sensor-Service-Version festnageln.
3. Tracker-Fähigkeit und Berechtigung auf der Watch prüfen.
4. IBI-Messpunkte samt SDK-Signalstatus in `SamsungHealthSensorSdkBruecke`
   übersetzen; Start/Stopp müssen explizit und widerrufbar sein.
5. Auf echter Watch 4 testen. Der Emulator kann diesen Sensorpfad nicht belegen.

## Datengrenze

IBI, HRV und Bewegungsdaten verbleiben lokal auf der Uhr. Nach ausdrücklichem
Tastendruck darf die Watch ausschließlich abgeleitete Schlafphasenwerte
(Phase, Zeitstempel, Konfidenz, Abdeckung und Algorithmusversion) über den
Wear Data Layer an das gekoppelte Smartphone senden. IBI-/BPM-/Schritt-Rohwerte
werden nicht übertragen. Health-Connect-Referenzdaten verbleiben lokal auf dem
Smartphone; es gibt keinen Upload und keine HA-Strecke in M2.

Keine Rohdaten, echten Nächte, Gerätekennungen oder Hausdaten gehören in Git.
Tests verwenden nur synthetische Werte. Eine Wellness-Schätzung ist keine
medizinische Messung.
