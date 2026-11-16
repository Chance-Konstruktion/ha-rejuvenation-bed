"""Tests für die Nachtbericht-Karte.

Wie bei der Nachttisch-Karte gelten Quelltext-Prüfungen: Sie klemmen die
Hausregeln fest, die eine Karte nicht verlieren darf — HA-Bausteine statt
REST mit Token, Tabs oben (mobil unten), Hypnogramm und Pulskurve statt
Zahlenwüste, und Ehrlichkeit über fehlende Quellen.
"""

from pathlib import Path

KARTE = "custom_components/rejuvenation_bed/frontend/rejuvenation-night-report-card.js"


def _karte() -> str:
    return Path(KARTE).read_text(encoding="utf-8")


def test_karte_liegt_im_paket_und_registriert_sich():
    inhalt = _karte()
    assert 'customElements.define("rejuvenation-night-report"' in inhalt
    assert 'customElements.define("rejuvenation-night-report-editor"' in inhalt


def test_karte_bringt_grafischen_editor_mit():
    inhalt = _karte()
    assert "static getConfigElement()" in inhalt
    assert "config-changed" in inhalt


def test_karte_findet_den_berichtsensor_selbst():
    """Der Bericht-Sensor trägt sich als Attribut bei sich — die Karte liest das."""
    inhalt = _karte()
    assert 'MARKER = "rejuvenation_nachtbericht"' in inhalt
    assert "attrs[MARKER]" in inhalt


def test_karte_spricht_dienste_an_keine_rest_endpunkte():
    """Eine Karte in HA-Optik braucht keine Adresse und kein Token."""
    inhalt = _karte()
    assert "Authorization" not in inhalt
    assert "Bearer" not in inhalt
    assert "fetch(" not in inhalt


def test_tabs_oben_mobil_unten():
    inhalt = _karte()
    assert 'TABS = ["uebersicht", "verlauf"]' in inhalt
    assert "aria-selected" in inhalt
    # Hausregel: auf kleinen Schirmen wandern die Tabs unter den Inhalt.
    assert "@media (max-width: 480px)" in inhalt
    assert ".tabs { order: 10" in inhalt


def test_hypnogramm_als_svg():
    inhalt = _karte()
    assert "Hypnogramm" in inhalt
    assert "<rect" in inhalt
    assert 'aria-label="Hypnogramm' in inhalt or "aria-label='Hypnogramm" in inhalt
    # Wach, REM, leicht, tief — und die Lücke als eigenes Band.
    for phase in ("Wach", "REM", "Leicht", "Tief", "Lücke"):
        assert phase in inhalt


def test_pulskurve_als_svg():
    inhalt = _karte()
    assert "Pulsverlauf" in inhalt
    assert "<path" in inhalt
    assert "bpm" in inhalt


def test_vergleich_ueber_sieben_naechte():
    inhalt = _karte()
    assert "die letzten Nächte" in inhalt
    assert "vergleich" in inhalt
    assert "diese Nacht" in inhalt


def test_schaetzung_bleibt_sichtbar():
    """Grobe Schätzung muss man auf der Karte sehen können, nicht nur wissen."""
    inhalt = _karte()
    assert "grobe Schätzung" in inhalt
    assert "schaetzungshinweis" in inhalt.lower() or "_schaetzungshinweis" in inhalt
    assert "ist_schaetzung" in inhalt


def test_fehlende_quellen_werden_benannt():
    inhalt = _karte()
    assert "fehlend" in inhalt
    assert "nie ersetzt" in inhalt
    assert "hrv_grund" in inhalt


def test_leerzustand_zeigt_den_annahmeweg():
    inhalt = _karte()
    assert "Noch keine Nacht übermittelt" in inhalt
    assert "annahme_pfad" in inhalt


def test_kommt_das_skript_zu_spaet_wird_neu_gebaut():
    inhalt = _karte()
    assert "ll-rebuild" in inhalt
    assert "hui-error-card" in inhalt


def test_ha_optik_aus_den_hausbausteinen():
    """ha-card und die CSS-Variablen des Themes — kein eigenes Farbsystem."""
    inhalt = _karte()
    assert "ha-card" in inhalt
    assert "--primary-text-color" in inhalt
    assert "--secondary-text-color" in inhalt
    assert "--divider-color" in inhalt


def test_karte_flieht_nicht_vor_html():
    """Fremde Texte dürfen nichts einschleusen."""
    inhalt = _karte()
    assert "_escape(text)" in inhalt
    assert "&amp;" in inhalt
