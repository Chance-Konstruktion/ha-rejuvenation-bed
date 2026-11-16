# Uhr M2 – lokale Schlafphasen-Schätzung

## Status und Sicherheitsgrenze

Der M2-Schätzer ist ein **experimenteller, regelbasierter Kandidat**, kein medizinisches Modell. Die Nutzereinstellung ist standardmäßig AUS. Bei fehlenden, veralteten oder qualitativ unzureichenden IBI-/Bewegungsdaten bleibt die Ausgabe `unknown`. Eine Schätzung wird nicht an Home Assistant übertragen und verändert keine Temperaturregel.

Echte Schlafnächte und IBI-Rohdaten bleiben auf der Uhr. Nur abgeleitete Phasen, Zeitstempel, Konfidenz, Abdeckung und Algorithmusversion werden nach ausdrücklichem Tastendruck über die lokale Wear Data Layer-Verbindung zum gekoppelten Smartphone gesendet. Dort liest die separate Phone-App die Health-Connect-Referenz; weder Referenzdaten noch Rohsensorwerte gehen zurück auf die Watch oder in ein Netzwerk. Im Repository liegen ausschließlich synthetische Testdaten.

**Plattformgrenze:** Health Connect wird von Wear OS nicht unterstützt. Samsung Health synchronisiert Schlafdaten von der Watch zunächst zur Samsung-Health-App auf dem Smartphone und von dort zu Health Connect. Darum liegt der Health-Connect-Leser und die Berechtigungsoberfläche in `watch/phone`, nicht im Wear-Modul.

## IBI und Merkmale

- `IbiQuelle` ist die austauschbare Provider-Grenze.
- `FakeIbiQuelle` liefert deterministische Unit-Test-Eingaben.
- `SamsungHealthSensorSdkIbiQuelle` verweigert fail-closed, solange die optionale AAR-Brücke nicht vorhanden ist.
- `IbiMesspunktSpeicher` verwendet eine private, begrenzte SQLite-Datenbank (maximal zehn Stunden / 40.000 Werte).
- `SleepHrvExtractor` prüft physiologische IBI-Grenzen, optionale Provider-Signalqualität und lokale Artefakte. Er berechnet RMSSD, SDNN, ungefähre IBI-Zeitabdeckung sowie Bewegungsvarianz aus vorhandenen Schrittintervallen. `rawIbiCount` zählt alle zeitlich im Fenster liegenden Eingaben; `acceptedIbiCount + rejectedIbiCount == rawIbiCount`. Fehlende Bewegungs-Buckets werden nicht als Nullbewegung erfunden.

## Regelmodell v0

Die feste Regelversion ist `m2-rules-0.1`. Ihre Schwellen sind ausdrücklich Hypothesen für reproduzierbare Vergleiche. Die Regeln verwenden mittleres IBI, RMSSD, SDNN und Bewegungsvarianz. Sie liefern nur dann eine Kandidatenphase, wenn die Mindestzahl an IBI-Werten, die Signalqualität, Abdeckung, Bewegungsabdeckung und Konfidenz ausreichen. Andernfalls lautet das Ergebnis `unknown`.

Der experimentelle Schalter ist in `SleepEstimatorSettings` persistent und standardmäßig AUS. In der Info-Ebene des Schlaf-Blatts wird er über die deutlich beschriftete Touch-Aktion „EXPERIMENT EINSCHALTEN/AUSSCHALTEN“ bedient; auf dem Hauptblatt bleibt die Anzeige ohne aktivierten Schalter oder bei einem fehlgeschlagenen Qualitäts-Gate „unbekannt“ — seit Ziel C (#8) mit benanntem Grund: das Gesicht zeigt „unbekannt · <Grund>“ (Versuch ausgeschaltet (Schalter AUS) / keine IBI vorhanden / zu wenige IBI (X < 120) / Abdeckung / Güte / Bewegung), die Info-Ebene sagt „keine Phasen, weil: <Grund>“. `SleepStageEstimate.grund` trägt den Grund bzw. die Kennung der getroffenen Regel. `SleepStageEstimate.measuredAtEpochMillis` ist der Zeitpunkt der Schätzung, nicht der Mittelpunkt des 30-Minuten-Fensters.

## Grobe Ersatz-Schätzung ohne IBI

Solange die Samsung-AAR-Brücke fehlt (Fund-Notiz: `docs/IBI_ADAPTER.md`), schätzt `PulsBewegungsEstimator` (Version `puls-bewegung-grob-0.1`) aus dem letzten vollständigen 30-Minuten-Fenster: Herzfrequenz-Mittel und Streuung plus Schritt-Deltas. Die Regeln sind ausdrücklich grobe Hypothesen, nicht validiert. Die Schätzer-Kette wählt automatisch: mit verlässlicher IBI der `m2-rules-0.1`-Schätzer, ohne IBI die grobe Puls+Bewegungs-Schätzung; beide nur hinter dem Versuchs-Schalter (Standard AUS), beide `unknown` bei unzureichenden Daten. Die UI beschriftet die grobe Variante als „grobe Schätzung“, die Info-Ebene zeigt die Algorithmusversion. Beim Messstart benennt das Protokoll (Art `IBI`) den Zustand der echten IBI-Quelle — kein stiller Leerlauf.

## Health-Connect-Abgleich

`watch/phone` enthält die Smartphone-Begleit-App. Sie fordert dort die Nutzerberechtigung `READ_SLEEP` an und liest Schlafphasen-Segmente aus `SleepSessionRecord.stages`. Es werden keine Daten zurückgeschrieben. Generische `SLEEPING`- und `UNKNOWN`-Segmente sind keine genaue Referenzklasse und werden vom Vergleich ausgeschlossen. Der Watch-Leser wurde entfernt, weil Health Connect nicht auf Wear OS verfügbar ist.

`SleepLocalValidation` erstellt Schätzungen aus rollierenden vollständigen 30-Minuten-Fenstern im 5-Minuten-Schritt. Der Aufruf verlangt ein explizites `enabled=true`. Auf ausdrücklichen Tastendruck sendet die Watch ausschließlich diese abgeleiteten Schätzungen über `WearSleepPredictionSender` an das gekoppelte Smartphone. Die Phone-App validiert Schema, Zeitbereich und Modellversion, liest die Health-Connect-Referenz lokal und lässt `SleepStageAgreement` Konfusionsmatrix, Accuracy und Cohen-Kappa auf einem 5-Minuten-Raster berechnen. Die Unit-Tests benutzen ausschließlich synthetische IBI-, Bewegungs- und Phasenfolgen. Reale Nächte werden nicht in CI oder Git hochgeladen.

## Was die Implementierung noch nicht beweist

1. Die Samsung-AAR-Brücke ist nicht enthalten. Echte IBI-Live-Erfassung auf der Watch 4 ist daher noch nicht belegt. Der Weg ohne Partnerfreigabe wurde am 16.11.2026 recherchiert: AAR nur an registrierte Partner, Entwickler-Modus umgeht nur die Laufzeit-Politik; Details und Quellen in `docs/IBI_ADAPTER.md`.
2. Die Regeln (sowohl `m2-rules-0.1` als auch die grobe `puls-bewegung-grob-0.1`) sind noch nicht gegen eine echte, von Samsung Health nach Health Connect synchronisierte Referenznacht validiert. Die grobe Schätzung nutzt keine IBI/HRV-Merkmale und ist damit noch unschärfer als der M2-Kandidat.
3. Wear-Data-Layer-Übertragung und Smartphone-Abgleich müssen auf tatsächlich gekoppelten Geräten erprobt werden.
4. Claude muss auf der Watch 4 eine Nacht mit eingeschaltetem Experiment beobachten und den lokalen Vergleich auf dem Smartphone prüfen. Erst danach darf eine andere Sitzung melden, dass die Schätzung „trägt“. Bis dahin bleibt die Standardausgabe `unknown`.

## Testdaten- und Datenschutzregel

Keine echte Schlafnacht, keine IBI-Rohreihe und keine personenbezogene Health-Connect-Aufzeichnung in Unit-Test-Fixtures, Logs, CI-Artefakten oder Git. Synthetische Reihen werden deterministisch erzeugt.
