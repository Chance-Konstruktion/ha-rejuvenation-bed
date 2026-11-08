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
