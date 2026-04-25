"""Tests for PresenceDetector v4 - variance + trend consistency based presence detection."""

import pytest
import math
from datetime import datetime, timedelta

from custom_components.rejuvenation_bed.presence_detector import (
    PresenceDetector,
    PresenceThresholds,
)


@pytest.fixture
def detector():
    return PresenceDetector()


@pytest.fixture
def fast_detector():
    """Detector with no debounce and low min_samples for testing."""
    thresholds = PresenceThresholds(
        debounce_minutes=0,
        history_window_minutes=10,
        min_samples=5,
        presence_enter_minutes=0,
        presence_leave_minutes=0,
    )
    return PresenceDetector(thresholds=thresholds)


# ═══════════════════════════════════════════════════════════════════════════════
# GRUNDLEGENDE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPresenceDetectorInit:
    def test_default_thresholds(self, detector):
        assert detector.thresholds.variance_low == 0.02
        assert detector.thresholds.variance_high == 0.08
        assert detector.thresholds.trend_threshold == 0.85
        assert detector.thresholds.trend_chaotic == 0.6
        assert detector.thresholds.debounce_minutes == 15
        assert detector.thresholds.history_window_minutes == 30
        assert detector.thresholds.min_samples == 20

    def test_custom_thresholds(self):
        custom = PresenceThresholds(variance_low=0.01, variance_high=0.05)
        det = PresenceDetector(thresholds=custom)
        assert det.thresholds.variance_low == 0.01
        assert det.thresholds.variance_high == 0.05

    def test_legacy_water_variance_threshold_exists(self, detector):
        """BedIntelligence sets this for calibration compatibility."""
        assert hasattr(detector.thresholds, "water_variance_threshold")
        assert detector.thresholds.water_variance_threshold == 0.040


# ═══════════════════════════════════════════════════════════════════════════════
# DEDIZIERTER SENSOR OVERRIDE
# ═══════════════════════════════════════════════════════════════════════════════


class TestPresenceSensorOverride:
    def test_dedicated_sensor_overrides(self, detector):
        """Dedicated presence sensor always wins."""
        is_present, conf, reason = detector.detect_presence(
            zone_index=0,
            water_temp=28.0,
            presence_sensor_state=True,
        )
        assert is_present is True
        assert conf == 1.0
        assert "Sensor" in reason

    def test_dedicated_sensor_absent(self, detector):
        is_present, conf, reason = detector.detect_presence(
            zone_index=0,
            water_temp=28.0,
            presence_sensor_state=False,
        )
        assert is_present is False
        assert conf == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# KERN-TEST: HEIZUNG vs. PERSON (DAS HAUPTPROBLEM!)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeatingVsPresence:
    """
    DAS ist der zentrale Bug-Fix-Test!

    Bett heizt allein: +0.0625°C alle 6-10 Min → monoton, niedrige Varianz → OFF
    Person drin: chaotische Schwankungen → hohe Varianz, niedrige Konsistenz → ON
    """

    def test_monotonic_heating_no_presence(self, fast_detector):
        """
        Simuliert gleichmäßiges Heizen ohne Person.
        Temperatur steigt monoton um +0.0625°C alle ~8 Minuten.
        → MUSS OFF bleiben!
        """
        now = datetime.now()
        base_temp = 27.375

        # 30 Messwerte über 10 Minuten, monoton steigend
        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 20)
            # +0.0625°C alle ~8 Min = +0.0625 alle ~16 Samples (bei 30s)
            step = i // 5  # Alle 5 Samples ein Schritt
            temp = base_temp + step * 0.0625
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(zone_index=0, water_temp=base_temp + 0.375)
        assert is_present is False, f"Heizung allein darf NICHT als Präsenz erkannt werden! reason={reason}"
        assert conf < 0.3

    def test_chaotic_person_presence(self, fast_detector):
        """
        Simuliert chaotische Temperatur wenn Person im Bett liegt.
        Schwankungen hoch und runter, keine klare Richtung.
        → MUSS ON werden!
        """
        now = datetime.now()
        base_temp = 28.0

        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 20)
            # Chaotische Schwankungen: sin + random-artig
            temp = base_temp + 0.3 * math.sin(i * 0.8) + 0.1 * math.cos(i * 2.1)
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(zone_index=0, water_temp=28.1)
        assert is_present is True, f"Chaotische Schwankungen MÜSSEN als Präsenz erkannt werden! reason={reason}"
        assert conf > 0.5

    def test_real_data_heating_pattern(self, fast_detector):
        """
        Echte Daten aus dem Bug-Report: Bett heizt von 01:00-05:00.
        Konstant +0.0625°C Schritte. MUSS OFF bleiben.
        """
        now = datetime.now()
        # Echte Heizungsdaten (vereinfacht): 27.375 → 29.5 über Stunden
        # Hier 10 Minuten-Fenster mit typischem Muster
        heating_temps = [
            27.375,
            27.375,
            27.375,
            27.4375,
            27.4375,
            27.4375,
            27.5,
            27.5,
            27.5,
            27.5625,
            27.5625,
            27.5625,
            27.625,
            27.625,
            27.625,
            27.6875,
            27.6875,
            27.6875,
            27.75,
            27.75,
            27.75,
            27.8125,
            27.8125,
            27.8125,
            27.875,
            27.875,
            27.875,
            27.9375,
            27.9375,
            27.9375,
        ]
        for i, temp in enumerate(heating_temps):
            t = now - timedelta(seconds=(len(heating_temps) - i) * 20)
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(zone_index=0, water_temp=27.9375)
        assert is_present is False, f"Echtes Heizungsmuster darf NICHT als Präsenz erkannt werden! reason={reason}"

    def test_sudden_person_entry(self, fast_detector):
        """
        Simuliert den Moment wo Person ins Bett steigt.
        Erst monoton (Heizung), dann plötzlich chaotisch.
        """
        now = datetime.now()
        base_temp = 29.0

        # Erst 5 stabile Heiz-Werte
        for i in range(5):
            t = now - timedelta(seconds=(30 - i) * 20)
            temp = base_temp + i * 0.01
            fast_detector._store(0, temp, None, None, t)

        # Dann 25 stark chaotische Werte (Person steigt ein, Bewegung, Decke)
        for i in range(25):
            t = now - timedelta(seconds=(25 - i) * 20)
            temp = base_temp + 0.5 * math.sin(i * 1.5) + 0.2 * math.cos(i * 3.7)
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(zone_index=0, water_temp=29.2)
        assert is_present is True, f"Person-Einstieg muss erkannt werden! reason={reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# REGRESSIONS-TESTS: NUR EIN WASSER-SENSOR (v7-Fix)
# ═══════════════════════════════════════════════════════════════════════════════
# Die häufigste Hardware-Kombination: ein DS18B20 am Wasserbett, sonst nichts.
# v5/v6 hatten hier kritische False-Negatives durch zu aggressive Rauschfilter
# bzw. falsche σ²-Schwellen. Diese Tests sichern v7 ab.


def _quantize_ds18b20(t: float) -> float:
    """Simuliert die 0.0625°C Quantisierung eines echten DS18B20."""
    return round(t * 16) / 16


class TestSingleSensorPresence:
    def test_person_still_quantized_signal(self, fast_detector):
        """
        Ruhig liegende Person + DS18B20-Quantisierung.
        Rohe σ ≈ 0.05°C, aber einzelne Sample-Sprünge sind <0.07°C.
        v6 hat das fälschlich als Heizung gewertet — v7 muss ON sagen.
        """
        now = datetime.now()
        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 60)
            temp = _quantize_ds18b20(
                28.0 + 0.06 * math.sin(i * 0.4) + 0.03 * math.cos(i * 1.7)
            )
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0, water_temp=28.0
        )
        assert is_present is True, (
            f"Ruhig liegende Person mit Quantisierung muss erkannt werden! reason={reason}"
        )

    def test_person_plus_heating_simultaneously(self, fast_detector):
        """
        Person liegt im Bett WÄHREND das Bett heizt — typischer Nacht-Fall.
        Rohes σ ist hoch durch die Rampe, aber detrended σ zeigt die Person.
        """
        now = datetime.now()
        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 60)
            # Heizrampe + Person-Schwankungen
            temp = _quantize_ds18b20(
                28.0
                + (i / 30) * 0.3
                + 0.05 * math.sin(i * 0.4)
                + 0.02 * math.cos(i * 1.3)
            )
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0, water_temp=28.3
        )
        assert is_present is True, (
            f"Person + Heizung gleichzeitig muss erkannt werden! reason={reason}"
        )

    def test_pure_heating_ramp_stays_off(self, fast_detector):
        """
        Reine Heiz-Rampe (kein Mensch), egal wie steil.
        Detrended σ zieht die Rampe ab → fast 0 → OFF.
        """
        now = datetime.now()
        # Aggressive Rampe: 27.5 → 28.0 in 30 min
        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 60)
            temp = _quantize_ds18b20(27.5 + (i / 30) * 0.5)
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0, water_temp=28.0
        )
        assert is_present is False, (
            f"Reine Heiz-Rampe darf NICHT als Präsenz erkannt werden! reason={reason}"
        )

    def test_detrended_std_separates_heating_from_person(self, fast_detector):
        """
        Direkter Vergleich: gleiches rohes σ, aber unterschiedliche Ursache.
        Detrended σ muss klar zwischen Heizung (≈0) und Person (≈σ) trennen.
        """
        now = datetime.now()
        # Samples 20s auseinander damit alle ins 10-min-Fenster passen
        # Heizungs-Rampe (linearer Anstieg)
        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 20)
            fast_detector._store(0, 27.5 + (i / 30) * 0.5, None, None, t)
        heating_detrended = fast_detector._calculate_detrended_std(0)

        # Reset, Person ohne Heizung (Schwankungen um konstante Temperatur)
        det2 = type(fast_detector)(thresholds=fast_detector.thresholds)
        for i in range(30):
            t = now - timedelta(seconds=(30 - i) * 20)
            det2._store(0, 28.0 + 0.1 * math.sin(i * 0.5), None, None, t)
        person_detrended = det2._calculate_detrended_std(0)

        assert heating_detrended < 0.02, (
            f"Heizungs-Rampe sollte detrended σ < 0.02 haben, ist {heating_detrended}"
        )
        assert person_detrended > 0.04, (
            f"Person sollte detrended σ > 0.04 haben, ist {person_detrended}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# VARIANZ-BERECHNUNG
# ═══════════════════════════════════════════════════════════════════════════════


class TestVarianceCalculation:
    def test_zero_variance_constant_temp(self, fast_detector):
        """Konstante Temperatur → Varianz = 0."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            fast_detector._store(0, 28.0, None, None, t)

        variance = fast_detector._calculate_variance(0)
        assert variance == 0.0

    def test_low_variance_heating(self, fast_detector):
        """Monoton steigende Temp → niedrige Varianz (< VARIANCE_LOW)."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            temp = 27.5 + i * 0.0125  # Langsamer Anstieg
            fast_detector._store(0, temp, None, None, t)

        variance = fast_detector._calculate_variance(0)
        assert variance < 0.02, f"Heizungs-Varianz sollte < 0.02 sein, ist {variance}"

    def test_high_variance_person(self, fast_detector):
        """Chaotische Temp → hohe Varianz (> VARIANCE_HIGH)."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            temp = 28.0 + 0.5 * math.sin(i * 0.7)
            fast_detector._store(0, temp, None, None, t)

        variance = fast_detector._calculate_variance(0)
        assert variance > 0.08, f"Personen-Varianz sollte > 0.08 sein, ist {variance}"


# ═══════════════════════════════════════════════════════════════════════════════
# TREND-KONSISTENZ
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrendConsistency:
    def test_monotonic_rise_high_consistency(self, fast_detector):
        """Monoton steigend → Konsistenz nahe 1.0."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            fast_detector._store(0, 27.0 + i * 0.05, None, None, t)

        consistency = fast_detector._calculate_trend_consistency(0)
        assert consistency > 0.9, f"Monoton steigend sollte Konsistenz >0.9 haben, ist {consistency}"

    def test_chaotic_low_consistency(self, fast_detector):
        """Chaotisch → Konsistenz nahe 0.5."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            temp = 28.0 + 0.3 * math.sin(i * 1.5)
            fast_detector._store(0, temp, None, None, t)

        consistency = fast_detector._calculate_trend_consistency(0)
        assert consistency < 0.7, f"Chaotisch sollte Konsistenz <0.7 haben, ist {consistency}"

    def test_heating_with_sensor_noise(self, fast_detector):
        """
        Heizung mit DS18B20-Rauschen (±0.0625°C).
        Sollte trotzdem hohe Konsistenz zeigen.
        """
        now = datetime.now()
        base = 27.5
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            # Monotoner Anstieg mit minimalem Rauschen
            step = i // 4
            temp = base + step * 0.0625
            fast_detector._store(0, temp, None, None, t)

        consistency = fast_detector._calculate_trend_consistency(0)
        assert consistency >= 0.85, f"Heizung mit Rauschen sollte Konsistenz >=0.85 haben, ist {consistency}"


# ═══════════════════════════════════════════════════════════════════════════════
# DEBOUNCE
# ═══════════════════════════════════════════════════════════════════════════════


class TestDebounce:
    def test_asymmetric_hysteresis(self):
        """
        Asymmetrische Hysterese: schnell rein (5 min), langsam raus (20 min).
        Verhindert Flackern und verpasste Einstiege.
        """
        thresholds = PresenceThresholds(
            presence_enter_minutes=5,
            presence_leave_minutes=20,
            history_window_minutes=10,
            min_samples=5,
        )
        det = PresenceDetector(thresholds=thresholds)
        now = datetime.now()

        # Start: OFF, kein Wechselbedarf
        assert det._apply_debounce(0, False, now) is False

        # Erster "present" → Pending startet, Status bleibt OFF
        assert det._apply_debounce(0, True, now) is False

        # Nach 3 Minuten → zu früh für 5-min Einstieg
        assert det._apply_debounce(0, True, now + timedelta(minutes=3)) is False

        # Nach 5+ Minuten konstant "present" → Wechsel auf ON
        assert det._apply_debounce(0, True, now + timedelta(minutes=5)) is True

        # Kurzzeitiges "not present" → Pending OFF startet, bleibt ON
        t1 = now + timedelta(minutes=6)
        assert det._apply_debounce(0, False, t1) is True

        # Nach 10 min OFF-Pending → immer noch ON (braucht 20)
        assert det._apply_debounce(0, False, t1 + timedelta(minutes=10)) is True

        # Nach 20+ min konstant "not present" → Wechsel auf OFF
        assert det._apply_debounce(0, False, t1 + timedelta(minutes=20)) is False

    def test_pending_resets_on_flip(self):
        """Wechselt das Signal zurück vor Ablauf, wird Pending verworfen."""
        thresholds = PresenceThresholds(
            presence_enter_minutes=5,
            presence_leave_minutes=20,
            history_window_minutes=10,
            min_samples=5,
        )
        det = PresenceDetector(thresholds=thresholds)
        now = datetime.now()

        # OFF → Pending ON startet bei t=0
        assert det._apply_debounce(0, True, now) is False
        # Nach 3 min zurück auf False → Pending wird verworfen
        assert det._apply_debounce(0, False, now + timedelta(minutes=3)) is False
        # Nach 4 weiteren min wieder True → Timer startet NEU (nicht weiter)
        assert det._apply_debounce(0, True, now + timedelta(minutes=7)) is False
        # Erst 5 min später ist Einstieg bestätigt
        assert det._apply_debounce(0, True, now + timedelta(minutes=12)) is True

    def test_default_enter_leave_minutes(self, detector):
        """Standard-Hysterese: 5 min rein, 20 min raus."""
        assert detector.thresholds.presence_enter_minutes == 5
        assert detector.thresholds.presence_leave_minutes == 20


# ═══════════════════════════════════════════════════════════════════════════════
# HEIZMATTE (unverändert)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeatingPadPresence:
    def test_body_heat_detected(self, fast_detector):
        """Rising temp without heater = body heat = presence."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 30)
            temp = 25.0 + i * 0.05
            fast_detector._store(0, temp, None, None, t)

        is_present, conf, reason = fast_detector.detect_presence(
            zone_index=0,
            water_temp=26.0,
            heater_active=False,
            is_heating_pad=True,
        )
        assert conf > 0.3


# ═══════════════════════════════════════════════════════════════════════════════
# SCHWITZ-ERKENNUNG (unverändert)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSweatDetection:
    def test_no_sweat_normal_humidity(self, detector):
        """Normal humidity (50-70%) is not sweating."""
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(60):
            t = now + timedelta(seconds=i * 30)
            detector._store(0, 28.0, None, 60.0, t)

        assert detector.is_sweating(0) is False

    def test_sweat_high_humidity_with_rise(self, detector):
        """Very high humidity with significant rise = sweating."""
        now = datetime.now()
        for i in range(200):
            t = now - timedelta(seconds=(240 - i) * 30)
            detector._store(0, 28.0, None, 50.0, t)
        for i in range(40):
            t = now - timedelta(seconds=(40 - i) * 30)
            detector._store(0, 28.0, None, 95.0, t)

        assert detector.is_sweating(0) is True

    def test_humidity_levels(self, detector):
        now = datetime(2026, 3, 15, 23, 0)
        for i in range(10):
            t = now + timedelta(seconds=i * 30)
            detector._store(0, 28.0, None, 45.0, t)
        assert detector.get_humidity_level(0) == "trocken"


# ═══════════════════════════════════════════════════════════════════════════════
# LECKAGE-ERKENNUNG (unverändert)
# ═══════════════════════════════════════════════════════════════════════════════


class TestLeakDetection:
    def test_no_leak_normal(self, detector):
        """Normal conditions = no leak."""
        assert detector.is_potential_leak(0) is False

    def test_leak_sustained_high_humidity(self, detector):
        """3+ hours of >85% humidity = potential leak."""
        now = datetime.now()
        for i in range(400):
            t = now - timedelta(seconds=(400 - i) * 30)
            detector._store(0, 28.0, None, 90.0, t)

        assert detector.is_potential_leak(0) is True


# ═══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiagnostics:
    def test_diagnostics_structure(self, detector):
        diag = detector.get_diagnostics(0)
        assert "is_present" in diag
        assert "confidence" in diag
        assert "reason" in diag
        assert "water_variance" in diag
        assert "trend_consistency" in diag
        assert "water_temp_std" in diag
        assert "buffer_sizes" in diag
        assert "debounce_minutes" in diag
        assert "thresholds" in diag

    def test_diagnostics_after_detection(self, fast_detector):
        """After running detection, diagnostics should have real values."""
        now = datetime.now()
        for i in range(20):
            t = now - timedelta(seconds=(20 - i) * 20)
            fast_detector._store(0, 28.0 + i * 0.01, None, None, t)

        fast_detector.detect_presence(zone_index=0, water_temp=28.2)
        diag = fast_detector.get_diagnostics(0)

        assert diag["water_variance"] >= 0
        assert 0.0 <= diag["trend_consistency"] <= 1.0
        assert diag["buffer_sizes"]["water"] == 21  # 20 from _store + 1 from detect_presence


# ═══════════════════════════════════════════════════════════════════════════════
# DATEN SAMMELN (noch nicht genug Daten)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataCollection:
    def test_initial_collecting_data(self, detector):
        """First few readings should return 'collecting data'."""
        is_present, conf, reason = detector.detect_presence(zone_index=0, water_temp=28.0)
        assert conf == 0.0
        assert "Daten" in reason

    def test_not_enough_samples(self, detector):
        """Under min_samples should stay in collecting mode."""
        now = datetime.now()
        for i in range(5):  # default min_samples=20, so 5 is not enough
            t = now - timedelta(seconds=(5 - i) * 30)
            detector._store(0, 28.0, None, None, t)

        is_present, conf, reason = detector.detect_presence(zone_index=0, water_temp=28.0)
        assert conf == 0.0
        assert "Daten" in reason
