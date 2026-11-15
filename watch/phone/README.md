# Smartphone-Begleiter – lokaler Schlafphasen-Abgleich

Diese Android-App läuft auf dem gekoppelten Smartphone, nicht auf Wear OS.

## Ablauf

1. Health Connect auf dem Smartphone verfügbar machen und `READ_SLEEP` freigeben.
2. Auf der Watch den M2-Versuch ausdrücklich einschalten.
3. Auf der Watch im Schlaf-Blatt „ABGLEICH AM SMARTPHONE SENDEN“ antippen.
4. Auf dem Smartphone „Empfangene Schätzung lokal abgleichen“ ausführen.

Die Watch überträgt ausschließlich abgeleitete Schlafphasenwerte (Phase, Zeitstempel, Konfidenz, Abdeckung und Algorithmusversion) über die lokale Wear Data Layer-Verbindung. IBI, Puls und Bewegungsrohdaten verbleiben auf der Uhr. Health-Connect-Referenzdaten verbleiben auf dem Smartphone.

Der Vergleich verwendet Fünf-Minuten-Fenster und zeigt Konfusionsmatrix, Accuracy und Cohen-Kappa. Es gibt keinen Upload und keine Übertragung an Home Assistant.

## Grenzen

- Die Samsung-Health-Sensor-SDK-AAR-Brücke fehlt noch; echte IBI-Live-Daten von der Watch 4 sind nicht belegt.
- Die App zeigt die vom Nutzer erteilte `READ_SLEEP`-Berechtigung an und liest die synchronisierten Health-Connect-Schlafphasen.
- Samsung Health synchronisiert Watch-Schlafdaten zunächst mit der Smartphone-App. Die Verfügbarkeit und Aktualität hängt davon ab, dass die Watch mit Samsung Health synchronisiert wurde.
