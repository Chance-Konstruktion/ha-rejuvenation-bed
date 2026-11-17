"""
Webhook-Annahme für den Nachtbericht — der lokale Weg der Aufzeichnung in HA.

Die Integration registriert einen Home-Assistant-Webhook (nur lokal erreichbar,
`local_only=True`). Was dort ankommt, ist der Vertrag aus `nachtbericht.py`:
eine komplette Nacht (`type: "night_report"`) oder die laufende Phase
(`type: "phase_update"`).

Bewusst kein Dauer-Bearer-Token und keine Cloud-Route: Der Webhook hängt im
eigenen Netz und wird von Home Assistant verwaltet. Die spätere Pairing-
Strecke (M3, siehe docs/SMARTWATCH_ARCHITECTURE.md) kann diesen Endpunkt
übernehmen, ohne dass sich hier etwas ändert — nur die Transportstrecke davor.

Hausregeln: Keine IP, kein Hostname, keine Adresse im Code oder in Meldungen —
der Pfad wird relativ ausgegeben (`/api/webhook/…`). Fehler antworten dem
Absender mit Grund; es wird nichts stillschweigend angenommen.
"""

import logging

from homeassistant.components import webhook

from .const import DOMAIN
from .nachtbericht import TYPE_DATEN, NachtberichtFehler, NachtberichtSpeicher

_LOGGER = logging.getLogger(__name__)

WEBHOOK_NAME = "Nachtbericht"

TYPE_NACHT = "night_report"
TYPE_PHASE = "phase_update"


async def richte_webhook_ein(hass, speicher: NachtberichtSpeicher) -> str:
    """Webhook registrieren — die ID bleibt über Neustarts dieselbe.

    Die ID wird einmal erzeugt und im Nachtbericht-Speicher behalten, damit
    der Absender seine Zieladresse nicht nach jedem Neustart neu erfragen
    muss.
    """
    webhook_id = speicher.webhook_id
    if not webhook_id:
        webhook_id = webhook.async_generate_id()
        speicher.webhook_id = webhook_id
        await speicher.async_speichern()
    webhook.async_register(hass, DOMAIN, WEBHOOK_NAME, webhook_id, _handler(speicher), local_only=True)
    return webhook_id


def richte_webhook_ab(hass, webhook_id) -> None:
    """Webhook abmelden — beim Entladen der Integration."""
    if webhook_id:
        webhook.async_unregister(hass, webhook_id)


def webhook_pfad(webhook_id: str) -> str:
    """Relativer Pfad des Endpunkts — ohne Host, ohne Adresse.

    Selbst gebaut statt aus dem Webhook-Modul: Der Pfad ist Teil des
    Verschmelzungsvertrags (Sensor-Attribut, Doku), und die Hausregel „keine
    Adresse, kein Hostname“ liegt hier sichtbar in einer Hand.
    """
    return f"/api/webhook/{webhook_id}"


def _handler(speicher: NachtberichtSpeicher):
    """Handler-Bau: der Speicher gehört zum Config-Entry, der Handler zu ihm."""

    async def handle(hass, webhook_id, request):
        return await verarbeite(request, speicher)

    return handle


async def verarbeite(request, speicher: NachtberichtSpeicher):
    """Anfragekörper lesen und an den Nachtbericht-Speicher weiterreichen.

    Fehler gehen als begründete Antwort zurück — der Home-Assistant-Webhook
    schluckt sonst jede Ausnahme still, und der Absender wüsste nie, warum
    seine Nacht nie ankam.

    aiohttp kommt mit Home Assistant mit und wird erst hier geholt: das
    Attrappen-Testlauf-Umfeld (tests/) installiert es nicht, und das Modul
    soll dort trotzdem importierbar bleiben.
    """
    from aiohttp import web

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Anfragekörper ist kein lesbares JSON"}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "Erwartet ein JSON-Objekt, erhalten etwas anderes"}, status=400)

    art = payload.get("type", TYPE_NACHT)
    try:
        if art == TYPE_NACHT:
            await speicher.async_nacht_annehmen(payload)
        elif art == TYPE_PHASE:
            await speicher.async_phase_annehmen(payload)
        elif art == TYPE_DATEN:
            # Messreihen-Pakete der Stellung „Gesamtdaten“ — je 5 Minuten,
            # über den Zeitstempel zusammengeführt, Wiederholungen doppeln nicht.
            await speicher.async_daten_annehmen(payload)
        else:
            return web.json_response(
                {
                    "ok": False,
                    "error": f"Unbekannter Typ {art!r} — erlaubt sind '{TYPE_NACHT}', '{TYPE_PHASE}' und '{TYPE_DATEN}'",
                },
                status=400,
            )
    except NachtberichtFehler as err:
        return web.json_response({"ok": False, "error": str(err)}, status=400)
    except Exception as err:  # noqa: BLE001 — der Absender soll den Grund sehen
        _LOGGER.exception("Nachtbericht-Annahme unerwartet gescheitert")
        return web.json_response(
            {"ok": False, "error": f"Annahme gescheitert: {err.__class__.__name__} — Details im HA-Protokoll"},
            status=500,
        )

    return web.json_response({"ok": True, "type": art})
