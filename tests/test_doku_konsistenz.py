"""Konsistenz von Anzeige-Texten, Übersetzungen und README gegen den Code.

Die Durchsicht (#2) hat mehrfach Doc-/UI-Texte gefunden, die dem Code
widersprechen. Jede Heilung pinnt hier ihre Stelle fest, damit der alte
Text nicht zurückrutscht.
"""

import io
import json

import pytest

STRINGS = "custom_components/rejuvenation_bed/strings.json"
EN = "custom_components/rejuvenation_bed/translations/en.json"
DE = "custom_components/rejuvenation_bed/translations/de.json"


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_strings(value)


class TestK6StrompreisLabel:
    """K6: Der Config-Flow-Preis ist ct/kWh, nicht €/kWh.

    Der Options-Flow zeigt die Einheit ct/kWh, der Resolver teilt den Wert
    durch 100 (ct/kWh → EUR/kWh). Die Labels des Config-Flows sagten
    €/kWh mit Ø 0.30-0.35 — wer dem folgte, flog zusätzlich auf den
    Range-Minimum-Fehler (5-80).
    """

    @pytest.mark.parametrize("path", [STRINGS, EN, DE])
    def test_kein_eur_pro_kwh_mehr(self, path):
        data = json.load(io.open(path, encoding="utf-8"))
        uebrig = [s for s in _iter_strings(data) if "€/kWh" in s]
        assert uebrig == []

    def test_de_beschreibung_nennt_ct_kwh_mit_aktuellen_zahlen(self):
        data = json.load(io.open(DE, encoding="utf-8"))
        texte = list(_iter_strings(data))
        assert any("30-35 ct/kWh" in s for s in texte)


class TestK1ClearEmergencyUebersetzt:
    """K1: clear_emergency ist in strings.json und beiden Übersetzungen
    vertreten (englische Nutzer sahen sonst den deutschen Text aus
    services.yaml) und steht in der Services-Tabelle der README_DE."""

    @pytest.mark.parametrize("path", [STRINGS, EN, DE])
    def test_dienst_uebersetzt(self, path):
        data = json.load(io.open(path, encoding="utf-8"))
        entry = data["services"]["clear_emergency"]
        assert entry["name"] and entry["description"]
        assert "zone" in entry["fields"]

    def test_readme_de_listet_dienst(self):
        text = io.open("README_DE.md", encoding="utf-8").read()
        assert "rejuvenation_bed.clear_emergency" in text


class TestK2BoostDoku:
    """K2: Boost ist seit #11 eine feste Zieltemperatur (boost_target_temp,
    Standard 34), kein Offset mehr auf die Zieltemperatur. Der 60-Min-Wert
    gilt fuer den Switch; der Dienst set_boost defaultet auf 30 Min."""

    def test_en_readme_beschreibt_feste_zieltemperatur(self):
        text = io.open("README.md", encoding="utf-8").read()
        assert "target + offset" not in text
        assert "fixed boost target" in text

    def test_de_readme_beschreibt_feste_zieltemperatur(self):
        text = io.open("README_DE.md", encoding="utf-8").read()
        assert "Zieltemperatur + Offset" not in text
        assert "feste Zieltemperatur" in text

    def test_toter_offset_const_ist_weg(self):
        code = io.open(
            "custom_components/rejuvenation_bed/const.py", encoding="utf-8"
        ).read()
        assert "DEFAULT_BOOST_OFFSET" not in code


class TestK9Einliegezeit:
    """K9: Die Praesenz-Erkennung braucht PRESENCE_MIN_SAMPLES = 20 Werte
    im 60-Sekunden-Loop — rund 20 Minuten, nicht ~3 Minuten."""

    def test_en_readme_nennt_zwanzig_minuten(self):
        text = io.open("README.md", encoding="utf-8").read()
        assert "~3-minute settling" not in text
        assert "~20-minute settling" in text

    def test_de_readme_nennt_zwanzig_minuten(self):
        text = io.open("README_DE.md", encoding="utf-8").read()
        assert "~3 Min" not in text
        assert "~20 Min" in text


class TestK12PytestHaIniKommentar:
    """K12: Der pythonpath-Kommentar in pytest-ha.ini erklaerte ein
    Nachbarsprojekt (custom_components.spatial_hub, hilfen.py) — beides
    existiert hier nicht; der Helfer heisst tests_ha/conftest.py."""

    def test_kommentar_beschreibt_diese_suite(self):
        ini = io.open("pytest-ha.ini", encoding="utf-8").read()
        assert "spatial_hub" not in ini
        assert "hilfen.py" not in ini
        assert "rejuvenation_bed" in ini
        assert "conftest.py" in ini


class TestK14VersionsBadge:
    """K14: Die Versions-Badges beider READMEs zeigen die Version aus der
    manifest.json — sie hinkten mit v260728 hinter manifest 260804 her."""

    @pytest.mark.parametrize("path", ["README.md", "README_DE.md"])
    def test_badge_entspricht_manifest(self, path):
        manifest = json.load(
            io.open("custom_components/rejuvenation_bed/manifest.json", encoding="utf-8")
        )
        text = io.open(path, encoding="utf-8").read()
        assert f"version-v{manifest['version']}" in text
        assert "version-v260728" not in text
