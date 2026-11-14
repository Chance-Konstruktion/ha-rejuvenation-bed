# Uhr M2 – lokale Schlafphasen-Schätzung

## Status und Sicherheitsgrenze

Der M2-Schätzer ist ein **experimenteller, regelbasierter Kandidat**, kein medizinisches Modell. Die Nutzereinstellung ist standardmäßig AUS. Bei fehlenden, veralteten oder qualitativ unzureichenden IBI-/Bewegungsdaten bleibt die Ausgabe `unknown`. Eine Schätzung wird nicht an Home Assistant übertragen und verändert keine Temperaturregel.

Echte Schlafnächte, Sensor-Rohdaten und Gerätekennungen bleiben lokal auf der Uhr. Im Repository liegen ausschließlich synthetische Testdaten.

## IBI und Merkmale

- `IbiQuelle` ist die austauschbare Provider-Grenze.
- `FakeIbiQuelle` liefert deterministische Unit-Test-Eingaben.
- `SamsungHealthSensorSdkIbiQuelle` verweigert fail-closed, solange die optionale AAR-Brücke nicht vorhanden ist.
- `IbiMesspunktSpeicher` verwendet eine private, begrenzte SQLite-Datenbank (maximal zehn Stunden / 40.000 Werte).
- `SleepHrvExtractor` prüft physiologische IBI-Grenzen, optionale Provider-Signalqualität und lokale Artefakte. Er berechnet RMSSD, SDNN, ungefähre IBI-Zeitabdeckung sowie Bewegungsvarianz aus vorhandenen Schrittintervallen. Fehlende Bewegungs-Buckets werden nicht als Nullbewegung erfunden.

## Regelmodell v0

Die feste Regelversion ist `m2-rules-0.1`. Ihre Schwellen sind ausdrücklich Hypothesen für reproduzierbare Vergleiche. Die Regeln verwenden mittleres IBI, RMSSD, SDNN und Bewegungsvarianz. Sie liefern nur dann eine Kandidatenphase, wenn die Mindestzahl an IBI-Werten, die Signalqualität, Abdeckung, Bewegungsabdeckung und Konfidenz ausreichen. Andernfalls lautet das Ergebnis `unknown`.

Der experimentelle Schalter ist in `SleepEstimatorSettings` persistent und standardmäßig AUS. `SleepStageEstimate.measuredAtEpochMillis` ist der Zeitpunkt der Schätzung, nicht der Mittelpunkt des 30-Minuten-Fensters.

## Health-Connect-Abgleich

`HealthConnectSleepQuelle` liest Schlafphasen-Segmente aus `SleepSessionRecord.stages` ausschließlich mit der Nutzerberechtigung `READ_SLEEP`. Es werden keine Daten zurückgeschrieben. Generische `SLEEPING`- und `UNKNOWN`-Segmente sind keine genaue Referenzklasse und werden vom Vergleich ausgeschlossen.

`SleepStageAgreement` richtet Schätzungen und Referenzsegmente auf einem 30-Sekunden- oder 5-Minuten-Raster aus und liefert Konfusionsmatrix, Accuracy und Cohen-Kappa. Die Unit-Tests benutzen ausschließlich synthetische Phasenfolgen. Der Vergleich muss nach dem Einwilligen auf dem Gerät lokal ausgeführt werden; reale Nächte werden nicht in CI oder Git hochgeladen.

## Was die Implementierung noch nicht beweist

1. Die Samsung-AAR-Brücke ist nicht enthalten. Die offizielle Samsung-Integration bleibt gesondert zu beziehen und auf der Watch 4 mit Capability- und Berechtigungsprüfung einzubauen.
2. Die Regeln sind noch nicht gegen eine echte Health-Connect-Referenznacht validiert.
3. Die Watch-4-Nacht mit eingeschaltetem Experiment-Schalter und lokalem Abgleich steht aus.
4. Erst nach dieser Prüfung darf eine andere Sitzung melden, dass die Schätzung „trägt“. Bis dahin bleibt die Standardausgabe `unknown`.

## Testdaten- und Datenschutzregel

Keine echte Schlafnacht, keine IBI-Rohreihe und keine personenbezogene Health-Connect-Aufzeichnung in Unit-Test-Fixtures, Logs, CI-Artefakten oder Git. Synthetische Reihen werden deterministisch erzeugt.
