# Architektur – Rejuvenation Bed

## Systemübersicht

```mermaid
graph TB
    subgraph "Home Assistant"
        HA[HA Core] --> CF[Config Flow]
        HA --> OF[Options Flow]
        CF --> COORD[Coordinator<br/>60s Update Loop]
        OF --> COORD
    end

    subgraph "Sensoren & Hardware"
        HW_HEAT[Heizung<br/>Switch/Relais]
        HW_TEMP[Wasser-Temp<br/>DS18B20]
        HW_AIR[Luft-Temp<br/>SHT41]
        HW_POW[Leistung<br/>Smart Plug]
        HW_MOIST[Feuchtigkeit<br/>SHT41]
        HW_PRES[Präsenz<br/>mmWave/Matte]
    end

    subgraph "Core Engine"
        COORD --> TC[Temperature<br/>Calculator]
        COORD --> PD[Presence<br/>Detector]
        COORD --> SM[Safety<br/>Manager]
        COORD --> HSM[Heating<br/>State Machine]
        COORD --> BI[Bed<br/>Intelligence]
        COORD --> DM[Diagnostics<br/>Manager]

        TC --> BIO[Biorhythmus<br/>Curve]
        TC --> WTR[Wake Time<br/>Resolver]
        TC --> SSR[Sleep Stage<br/>Resolver]
        TC --> ESR[Energy State<br/>Resolver]

        HSM --> RC[Ramp<br/>Controller]
        HSM --> ASC[Anti Short<br/>Cycle]

        BI --> CAL[Auto-<br/>Kalibrierung]
        BI --> BTL[Bedtime<br/>Learning]
        BI --> ISO[Isolations-<br/>Check]

        COORD --> SSC[Sleep Score<br/>Calculator]
    end

    subgraph "HA Entities"
        ENT_CLIM[Climate Entity<br/>Thermostat UI]
        ENT_SENS[Sensoren<br/>Temp, Score, Energie]
        ENT_BIN[Binary Sensors<br/>Präsenz, Isolation]
        ENT_SW[Switches<br/>Boost, Krank, Urlaub]
    end

    HW_TEMP --> COORD
    HW_AIR --> COORD
    HW_POW --> COORD
    HW_MOIST --> COORD
    HW_PRES --> PD

    COORD --> ENT_CLIM
    COORD --> ENT_SENS
    COORD --> ENT_BIN
    COORD --> ENT_SW
    ENT_CLIM --> HW_HEAT

    style COORD fill:#4a9eff,color:#fff
    style TC fill:#ff9f43,color:#fff
    style BIO fill:#ff6b6b,color:#fff
    style HSM fill:#2ed573,color:#fff
    style BI fill:#a55eea,color:#fff
```

## Datenfluss (60s Update Loop)

```mermaid
sequenceDiagram
    participant HW as Hardware
    participant CO as Coordinator
    participant PD as Presence
    participant TC as TempCalc
    participant SM as Safety
    participant HSM as HeatingFSM
    participant HE as Heater

    CO->>HW: Sensor-Werte lesen
    HW-->>CO: temp, power, humidity
    CO->>PD: detect_presence()
    PD-->>CO: is_present, confidence
    CO->>TC: async_calculate_target()
    TC-->>CO: target_temp
    CO->>SM: check_safety()
    SM-->>CO: vetoes / overrides
    CO->>HSM: evaluate()
    HSM-->>CO: should_heat, setpoint
    CO->>HE: turn_on/turn_off
    CO->>CO: update entities
```

## Bett-Typ Entscheidungsbaum

```mermaid
graph TD
    A[Bett-Typ?] --> B{Wasserbett}
    A --> C{Heizmatte}

    B --> B1[Min 24°C<br/>Kondensationsschutz]
    B --> B2[Rampe max 1°C/h<br/>Vinyl-Schutz]
    B --> B3[Thermische Batterie<br/>Solar-Boost]
    B --> B4[Vorheizen 3-5h<br/>Hohe Trägheit]
    B --> B5[Leckage-Erkennung]

    C --> C1[Kann AUS sein<br/>Kein Risiko]
    C --> C2[Keine Rampe<br/>Sofort-Reaktion]
    C --> C3[Kein Speicher<br/>Kein Solar-Nutzen]
    C --> C4[Vorheizen 15min<br/>Schnelle Reaktion]

    style B fill:#4a9eff,color:#fff
    style C fill:#ff9f43,color:#fff
```

## Entity-Übersicht

| Device | Entity | Typ | Beschreibung |
|--------|--------|-----|-------------|
| Hauptgerät | `climate.rejuvenation_bed_zone_*` | Climate | Thermostat-UI |
| Hauptgerät | `binary_sensor.bett_praesenz_*` | Binary | Belegung |
| Hauptgerät | `binary_sensor.bett_degraded_mode` | Binary | Fehlermodus |
| Hauptgerät | `switch.bett_boost_*` | Switch | Schnellheizen |
| Hauptgerät | `switch.bett_krank_modus_*` | Switch | Genesungsmodus |
| Hauptgerät | `switch.bett_urlaub_modus_*` | Switch | Frostschutz |
| Energie | `sensor.bett_verbrauch_heute` | Sensor | kWh/Tag |
| Energie | `sensor.bett_thermische_batterie` | Sensor | Wärme-% |
| Energie | `sensor.bett_solar_anteil` | Sensor | Solar-kWh |
| Energie | `sensor.bett_ersparnis` | Sensor | % vs. Legacy |
| Schlaf | `sensor.bett_schlaf_score_*` | Sensor | 0-100 Punkte |
| Schlaf | `sensor.bett_einschlafzeit_vorhersage` | Sensor | Gelernte Zeit |

## Module & LOC

| Modul | Zeilen | Beschreibung |
|-------|--------|-------------|
| `coordinator.py` | ~900 | Hauptschleife, orchestriert alles |
| `bed_intelligence.py` | ~1400 | Auto-Kalibrierung, Bedtime-Learning |
| `temperature_calculator.py` | ~650 | Zieltemperatur-Berechnung |
| `presence_detector.py` | ~550 | Varianz-basierte Belegung |
| `biorhythmus_curve.py` | ~460 | Physiologische Schlafkurve |
| `sleep_score_calculator.py` | ~640 | Schlafqualitäts-Metrik |
| `heating_state_machine.py` | ~200 | Vereinte Heiz-Logik |
| `ramp_controller.py` | ~370 | Vinyl-Schutz Rampen |
| `anti_short_cycle_manager.py` | ~320 | Relais-Schutz |
| `safety_manager.py` | ~550 | Überhitzungsschutz |
