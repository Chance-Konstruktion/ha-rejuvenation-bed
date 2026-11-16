/*
 * Rejuvenation Bed — Nachtbericht
 *
 * Lovelace-Karte mit dem vollen Schlafbericht je Nacht: Hypnogramm,
 * Pulskurve, Kennzahlen und Vergleich zu den letzten 7 Nächten. Die Daten
 * liest sie aus der Integration (Sensor „Bett Nachtbericht“) — kein Token,
 * keine Adresse, keine zweite Anmeldung. Die Karte wird von der Integration
 * selbst registriert.
 *
 * Beispiel (am besten in einer Ansicht mit "Panel (1 Karte)"):
 *
 *   type: custom:rejuvenation-night-report
 *   entity: sensor.bett_nachtbericht
 *
 * Ohne `entity` findet die Karte den Bericht-Sensor von selbst — er trägt
 * ihn als Attribut `rejuvenation_nachtbericht` bei sich.
 *
 * Ehrlichkeit: Fehlt eine Quelle (keine IBI → keine HRV, keine Phasen),
 * steht das im Bericht und in der Karte. Phasen aus der groben Schätzung
 * (Puls + Bewegung) werden sichtbar als „grobe Schätzung“ beschriftet.
 */

const MARKER = "rejuvenation_nachtbericht";

/* Hypnogramm von oben nach unten: wach, REM, leicht, tief. Was keine Phase
   abdeckt, ist Lücke — dunkles Band ganz unten, nie als Schlaf ausgegeben. */
const PHASEN = [
  { key: "awake", label: "Wach", farbe: "#9e9e9e" },
  { key: "rem", label: "REM", farbe: "#ab47bc" },
  { key: "light", label: "Leicht", farbe: "#42a5f5" },
  { key: "deep", label: "Tief", farbe: "#5c6bc0" },
];
const PHASE_FARBE = {};
PHASEN.forEach((p) => {
  PHASE_FARBE[p.key] = p.farbe;
});
const LUECKE_FARBE = "#4a4a4a";

const TABS = ["uebersicht", "verlauf"];
const TAB_NAMES = { uebersicht: "Übersicht", verlauf: "Verlauf" };

/* Puls-Kurve: etwas Spielraum über min und unter max. */
const PULS_SPIELRAUM = 5;

const pad = (n) => String(n).padStart(2, "0");

/* ISO-Zeitstempel (mit oder ohne Offset) → HH:MM in der Zonenzeit,
   die im Stempel steckt. Naive Stempel bleiben, wie sie sind. */
function uhrzeit(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "–";
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function dauer_text(minuten) {
  if (minuten == null) return "–";
  const h = Math.floor(minuten / 60);
  const m = Math.round(minuten % 60);
  return `${h} h ${pad(m)} min`;
}

function zahl(x, nachkommastellen = 0) {
  if (x == null || isNaN(Number(x))) return "–";
  return Number(x).toFixed(nachkommastellen);
}

function guete_farbe(guete) {
  if (guete == null) return "var(--secondary-text-color)";
  if (guete >= 80) return "#43a047";
  if (guete >= 50) return "#ffa726";
  return "#e57373";
}

class RejuvenationNightReportCard extends HTMLElement {
  setConfig(config) {
    if (!config || typeof config !== "object") {
      throw new Error("Konfiguration fehlt");
    }
    this._config = { ...config, entity: config.entity || null, title: config.title || "Nachtbericht" };
    this._tab = "uebersicht";
    if (this._built) this._render();
  }

  static getConfigElement() {
    return document.createElement("rejuvenation-night-report-editor");
  }

  static getStubConfig() {
    return { entity: null };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._render();
  }

  getCardSize() {
    return 6;
  }

  /* ── Bericht beschaffen ─────────────────────────────────────────
     Was in der Karte steht, gilt. Ohne `entity` findet die Karte den
     Bericht-Sensor von selbst: er trägt ihn als Attribut bei sich. */
  _bericht() {
    if (!this._hass) return null;
    const id = this._config.entity || this._entdeckt();
    if (!id) return null;
    const state = this._hass.states[id];
    if (!state) return null;
    if (state.state === "unknown" || state.state === "unavailable") return null;
    return state.attributes || null;
  }

  _entdeckt() {
    if (!this._hass) return null;
    for (const id of Object.keys(this._hass.states)) {
      const attrs = this._hass.states[id] && this._hass.states[id].attributes;
      if (attrs && attrs[MARKER] === true) return id;
    }
    return null;
  }

  /* ── Bau und Grundgerüst ────────────────────────────────────── */

  _build() {
    this._built = true;
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      :host {
        display: block;
      }
      ha-card {
        padding: 14px 16px 16px;
        color: var(--primary-text-color);
        font-family: var(--paper-font-body1_-_font-family, inherit);
        font-size: 14px;
      }
      .kopf {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
      }
      .kopf h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
      }
      .kopf .unterzeile {
        color: var(--secondary-text-color);
        font-size: 12px;
      }
      .badge {
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 600;
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
      }

      /* Tabs oben (Hausregel). Auf dem Handy wandern sie nach unten —
         der Daumen ist unten, der Blick oben. */
      .tabs {
        display: flex;
        gap: 4px;
        margin: 10px 0 12px;
        border-bottom: 1px solid var(--divider-color);
      }
      .tabs button {
        flex: 0 0 auto;
        border: none;
        background: none;
        color: var(--secondary-text-color);
        font: inherit;
        font-weight: 500;
        padding: 8px 14px;
        cursor: pointer;
        border-bottom: 2px solid transparent;
      }
      .tabs button[aria-selected="true"] {
        color: var(--primary-color);
        border-bottom-color: var(--primary-color);
      }
      @media (max-width: 480px) {
        .root { display: flex; flex-direction: column; }
        .tabs { order: 10; margin-top: 14px; border-bottom: none; border-top: 1px solid var(--divider-color); }
        .tabs button[aria-selected="true"] { border-bottom-color: transparent; border-top-color: var(--primary-color); }
        .inhalt { order: 0; }
        .kopf { order: -1; }
      }

      .kennzahlen {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 10px;
        margin-bottom: 14px;
      }
      .kennzahl {
        background: var(--secondary-background-color);
        border-radius: 8px;
        padding: 8px 10px;
      }
      .kennzahl .wert {
        font-size: 16px;
        font-weight: 600;
      }
      .kennzahl .titel {
        font-size: 11px;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }
      .kennzahl .zusatz {
        font-size: 11px;
        color: var(--secondary-text-color);
      }
      .fehlt {
        color: var(--secondary-text-color);
        font-style: italic;
      }

      .anteile {
        display: flex;
        height: 14px;
        border-radius: 7px;
        overflow: hidden;
        margin: 6px 0 4px;
        background: var(--divider-color);
      }
      .legende {
        display: flex;
        flex-wrap: wrap;
        gap: 4px 14px;
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-bottom: 12px;
      }
      .legende .punkt {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 3px;
        margin-right: 5px;
        vertical-align: -1px;
      }
      .abschnittstitel {
        font-size: 12px;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin: 14px 0 6px;
      }
      svg.graph {
        width: 100%;
        height: auto;
        display: block;
        background: var(--secondary-background-color);
        border-radius: 8px;
      }

      .hinweis {
        border-radius: 8px;
        padding: 8px 10px;
        margin-top: 10px;
        font-size: 13px;
        background: var(--secondary-background-color);
        color: var(--secondary-text-color);
      }
      .hinweis.schaetzung {
        background: rgba(255, 167, 38, 0.14);
        color: var(--primary-text-color);
      }
      .hinweis ul { margin: 4px 0 0 18px; padding: 0; }

      .leer {
        text-align: center;
        color: var(--secondary-text-color);
        padding: 24px 8px;
      }

      .verlauf-zeile {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 5px 0;
        border-bottom: 1px solid var(--divider-color);
        font-size: 13px;
      }
      .verlauf-zeile:last-child { border-bottom: none; }
      .verlauf-zeile .datum { flex: 0 0 96px; color: var(--secondary-text-color); }
      .verlauf-zeile .balken-wrap { flex: 1 1 auto; background: var(--divider-color); border-radius: 4px; height: 10px; overflow: hidden; }
      .verlauf-zeile .balken { display: block; height: 100%; }
      .verlauf-zeile .wert { flex: 0 0 76px; text-align: right; }
      .verlauf-zeile .etikett {
        flex: 0 0 auto;
        font-size: 10px;
        padding: 2px 6px;
        border-radius: 8px;
        background: rgba(255, 167, 38, 0.18);
        color: var(--primary-text-color);
      }
      .verlauf-tabellenhinweis {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-top: 8px;
      }
    `;
    const card = document.createElement("ha-card");
    const root = document.createElement("div");
    root.className = "root";
    card.appendChild(root);
    this.shadowRoot.append(style, card);
    this._root = root;
    this._render();
  }

  _render() {
    if (!this._root) return;
    const bericht = this._bericht();
    if (!bericht || !bericht.nacht) {
      const pfad = bericht && bericht.annahme_pfad;
      this._root.innerHTML = `
        <div class="kopf"><h2>${this._escape(this._config.title)}</h2></div>
        <div class="leer">
          Noch keine Nacht übermittelt.<br>
          Die Uhr meldet sich über den lokalen Annahme-Pfad der Integration${
            pfad ? `: <code>${this._escape(pfad)}</code>` : " (im Sensor „Bett Nachtbericht“ unter annahme_pfad)"
          }.
        </div>`;
      return;
    }

    const tabs = TABS.map(
      (t) => `<button data-tab="${t}" aria-selected="${t === this._tab}">${TAB_NAMES[t]}</button>`
    ).join("");
    const inhalt = this._tab === "uebersicht" ? this._uebersicht(bericht) : this._verlauf(bericht);
    this._root.innerHTML = `
      <div class="kopf">
        <h2>${this._escape(this._config.title)}</h2>
        <span class="badge" style="color:${guete_farbe(bericht.guete)}">Güte ${zahl(bericht.guete)} %</span>
      </div>
      <div class="kopf unterzeile">
        Nacht ${this._escape(bericht.nacht)} · ${dauer_text(bericht.dauer_minuten)} · ${this._escape(bericht.geraet || "Uhr")}
      </div>
      <div class="tabs">${tabs}</div>
      <div class="inhalt">${inhalt}</div>`;

    this._root.querySelectorAll(".tabs button").forEach((knopf) => {
      knopf.addEventListener("click", () => {
        this._tab = knopf.dataset.tab;
        this._render();
      });
    });
  }

  /* ── Tab Übersicht ──────────────────────────────────────────── */

  _uebersicht(b) {
    const anteile = b.phasen_anteile || {};
    const anteile_balken = PHASEN.map(
      (p) => `<div title="${p.label}: ${zahl(anteile[p.key], 1)} %" style="width:${anteile[p.key] || 0}%;background:${p.farbe}"></div>`
    ).join("");
    const legende = PHASEN.map(
      (p) =>
        `<span><span class="punkt" style="background:${p.farbe}"></span>${p.label} ${zahl(anteile[p.key], 1)} %</span>`
    ).join("");

    const puls = b.puls;
    const hrv = b.hrv;
    const kennzahlen = `
      <div class="kennzahl"><div class="titel">Schlafbeginn</div><div class="wert">${uhrzeit(b.start)}</div></div>
      <div class="kennzahl"><div class="titel">Schlafende</div><div class="wert">${uhrzeit(b.end)}</div></div>
      <div class="kennzahl"><div class="titel">Dauer</div><div class="wert">${dauer_text(b.dauer_minuten)}</div></div>
      <div class="kennzahl"><div class="titel">Puls min / Ø / max</div><div class="wert">${
        puls ? `${zahl(puls.min)} / ${zahl(puls.mean)} / ${zahl(puls.max)} bpm` : `<span class="fehlt">fehlt</span>`
      }</div>
        ${puls && puls.coverage != null ? `<div class="zusatz">${Math.round(puls.coverage * 100)} % Abdeckung</div>` : ""}
      </div>
      <div class="kennzahl"><div class="titel">HRV (RMSSD)</div><div class="wert">${
        hrv && hrv.rmssd != null ? `${zahl(hrv.rmssd, 1)} ms` : `<span class="fehlt">fehlt</span>`
      }</div>
        ${hrv && hrv.sdnn != null ? `<div class="zusatz">SDNN ${zahl(hrv.sdnn, 1)} ms</div>` : ""}
        ${hrv == null && b.hrv_grund ? `<div class="zusatz">${this._escape(b.hrv_grund)}</div>` : ""}
      </div>
      <div class="kennzahl"><div class="titel">Unterbrechungen</div><div class="wert">${zahl(
        (b.unterbrechungen || {}).anzahl
      )}</div><div class="zusatz">${zahl((b.unterbrechungen || {}).minuten)} min gesamt</div></div>
      <div class="kennzahl"><div class="titel">Bewegung</div><div class="wert">${
        b.bewegung && b.bewegung.steps_total != null ? `${zahl(b.bewegung.steps_total)} Schritte` : `<span class="fehlt">fehlt</span>`
      }</div></div>`;

    return `
      ${b.ist_schaetzung ? this._schaetzungshinweis(b) : ""}
      <div class="kennzahlen">${kennzahlen}</div>
      <div class="abschnittstitel">Phasen</div>
      <div class="anteile">${anteile_balken}</div>
      <div class="legende">${legende}</div>
      <div class="abschnittstitel">Hypnogramm</div>
      ${this._hypnogramm(b)}
      <div class="abschnittstitel">Pulsverlauf</div>
      ${this._pulskurve(b)}
      ${this._fehlendhinweise(b)}`;
  }

  _schaetzungshinweis(b) {
    const quellen = (b.quellen || []).filter((q) => q.toLowerCase().includes("schätzung"));
    const algorithmen = (b.phasen_verlauf || [])
      .map((s) => s.algorithm)
      .filter((a, i, arr) => a && arr.indexOf(a) === i);
    return `
      <div class="hinweis schaetzung">
        <strong>Phasen sind grob geschätzt.</strong>
        Quelle: ${this._escape(quellen.join(", ") || "grobe Schätzung aus Puls und Bewegung")}.
        ${algorithmen.length ? `Schätzer: ${this._escape(algorithmen.join(", "))}.` : ""}
        Ohne echte IBI-/Plattform-Phasen ist das Raten mit Ansage — das Bett schaltet danach
        zurückhaltend, und die Güte der Messung trägt das schon in sich.
      </div>`;
  }

  _fehlendhinweise(b) {
    const fehlend = b.fehlend || [];
    if (!fehlend.length) return "";
    const liste = fehlend
      .map((f) => `<li><strong>${this._escape(f.quelle)}</strong>: ${this._escape(f.grund || "kein Grund genannt")}</li>`)
      .join("");
    return `
      <div class="hinweis">
        <strong>Fehlt in dieser Nacht</strong> (wird im Bericht benannt, nie ersetzt):
        <ul>${liste}</ul>
      </div>`;
  }

  /* ── Hypnogramm ─────────────────────────────────────────────── */

  _hypnogramm(b) {
    const start = new Date(b.start).getTime();
    const ende = new Date(b.end).getTime();
    if (isNaN(start) || isNaN(ende) || ende <= start) return `<div class="leer">Zeiten fehlen — kein Hypnogramm.</div>`;
    const zeilen = PHASEN.length + 1; // +1: Lücke unten
    const hoehe = 150;
    const zeilenhoehe = hoehe / zeilen;
    const breite = 1000;
    const rand = 48; // Platz für die Zeilenbeschriftung links
    const skala = (t) => rand + ((t - start) / (ende - start)) * (breite - rand);

    const stuecke = [];
    (b.phasen_verlauf || []).forEach((seg) => {
      const s = new Date(seg.start).getTime();
      const e = new Date(seg.end).getTime();
      if (isNaN(s) || isNaN(e) || e <= s) return;
      const zeile = PHASEN.findIndex((p) => p.key === seg.stage);
      if (zeile < 0) return;
      const farbe = PHASE_FARBE[seg.stage] || LUECKE_FARBE;
      const schaetzung = seg.quelle === "estimate" || seg.quelle === "estimate-ibi";
      const x = skala(s).toFixed(1);
      const w = Math.max(0, skala(e) - skala(s)).toFixed(1);
      const y = (zeile * zeilenhoehe + 2).toFixed(1);
      stuecke.push(
        `<rect x="${x}" y="${y}" width="${w}" height="${(zeilenhoehe - 4).toFixed(1)}" rx="3" fill="${farbe}" opacity="${schaetzung ? 0.72 : 1}">
          <title>${this._escape(`${uhrzeit(seg.start)}–${uhrzeit(seg.end)} · ${PHASEN[zeile].label}${schaetzung ? " · grobe Schätzung" : ""}${seg.algorithm ? ` · ${seg.algorithm}` : ""}`)}</title>
        </rect>` +
        (schaetzung
          ? `<rect x="${x}" y="${y}" width="${w}" height="${(zeilenhoehe - 4).toFixed(1)}" rx="3" fill="none" stroke="rgba(255,167,38,0.85)" stroke-width="1.5" stroke-dasharray="4 3">
            <title>grobe Schätzung — kein gemessener Schlafphasen-Wert</title>
          </rect>`
          : "")
      );
    });

    /* Lückenband: Nachtzeit minus abgedeckte Segmente. */
    const bedeckt = (b.phasen_verlauf || [])
      .map((seg) => [new Date(seg.start).getTime(), new Date(seg.end).getTime()])
      .filter((p) => !isNaN(p[0]) && !isNaN(p[1]) && p[1] > p[0])
      .sort((a, b2) => a[0] - b2[0]);
    const luecken = [];
    let zeiger = start;
    bedeckt.forEach(([s, e]) => {
      if (s > zeiger) luecken.push([zeiger, Math.min(e, ende)]);
      zeiger = Math.max(zeiger, e);
    });
    if (zeiger < ende) luecken.push([zeiger, ende]);
    luecken.forEach(([s, e]) => {
      if (e <= s) return;
      stuecke.push(
        `<rect x="${skala(s).toFixed(1)}" y="${(zeilen * zeilenhoehe - zeilenhoehe + 2).toFixed(1)}" width="${(skala(e) - skala(s)).toFixed(1)}" height="${(zeilenhoehe - 4).toFixed(1)}" rx="3" fill="${LUECKE_FARBE}">
          <title>${uhrzeit(new Date(s).toISOString())}–${uhrzeit(new Date(e).toISOString())} · keine Phase gemeldet</title>
        </rect>`
      );
    });

    const beschriftungen = PHASEN.map(
      (p, i) =>
        `<text x="4" y="${(i * zeilenhoehe + zeilenhoehe / 2 + 4).toFixed(1)}" font-size="11" fill="var(--secondary-text-color)">${p.label}</text>`
    ).join("");
    const lueckenText = `<text x="4" y="${(zeilen * zeilenhoehe - zeilenhoehe / 2 + 4).toFixed(
      1
    )}" font-size="11" fill="var(--secondary-text-color)">Lücke</text>`;
    const achse = `
      <text x="${rand}" y="${hoehe + 14}" font-size="11" fill="var(--secondary-text-color)">${uhrzeit(b.start)}</text>
      <text x="${breite}" y="${hoehe + 14}" font-size="11" text-anchor="end" fill="var(--secondary-text-color)">${uhrzeit(b.end)}</text>`;

    return `
      <svg class="graph" viewBox="0 0 ${breite} ${hoehe + 20}" role="img" aria-label="Hypnogramm der Nacht">
        ${beschriftungen}${lueckenText}
        ${stuecke.join("")}
        ${achse}
      </svg>`;
  }

  /* ── Pulskurve ──────────────────────────────────────────────── */

  _pulskurve(b) {
    const puls = b.puls;
    if (!puls || !puls.punkte || puls.punkte.length < 2) {
      return `<div class="leer">Kein Pulsverlauf in dieser Nacht übermittelt.</div>`;
    }
    const breite = 1000;
    const hoehe = 120;
    const rand = 52; // Platz für die bpm-Beschriftung links
    const punkte = puls.punkte;
    const min = Math.min(puls.min, puls.mean, puls.max) - PULS_SPIELRAUM;
    const max = Math.max(puls.min, puls.mean, puls.max) + PULS_SPIELRAUM;
    const t0 = new Date(punkte[0].t).getTime();
    const t1 = new Date(punkte[punkte.length - 1].t).getTime();
    if (isNaN(t0) || isNaN(t1) || t1 <= t0) return `<div class="leer">Pulsverlauf ohne lesbare Zeiten.</div>`;
    const x = (t) => rand + ((t - t0) / (t1 - t0)) * (breite - rand);
    const y = (bpm) => hoehe - ((bpm - min) / (max - min)) * hoehe;
    const pfad = punkte
      .map((p, i) => {
        const t = new Date(p.t).getTime();
        if (isNaN(t)) return null;
        return `${i === 0 ? "M" : "L"}${x(t).toFixed(1)},${y(p.bpm).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");
    const mittel = `<line x1="${rand}" x2="${breite}" y1="${y(puls.mean).toFixed(1)}" y2="${y(puls.mean).toFixed(
      1
    )}" stroke="var(--secondary-text-color)" stroke-dasharray="6 4" stroke-width="1" opacity="0.7"/>`;
    return `
      <svg class="graph" viewBox="0 0 ${breite} ${hoehe + 20}" role="img" aria-label="Pulsverlauf der Nacht">
        ${mittel}
        <path d="${pfad}" fill="none" stroke="var(--primary-color)" stroke-width="2" vector-effect="non-scaling-stroke"/>
        <text x="4" y="14" font-size="11" fill="var(--secondary-text-color)">${zahl(max)} bpm</text>
        <text x="4" y="${hoehe - 4}" font-size="11" fill="var(--secondary-text-color)">${zahl(min)} bpm</text>
        <text x="${rand}" y="${hoehe + 14}" font-size="11" fill="var(--secondary-text-color)">${uhrzeit(punkte[0].t)}</text>
        <text x="${breite}" y="${hoehe + 14}" font-size="11" text-anchor="end" fill="var(--secondary-text-color)">${uhrzeit(punkte[punkte.length - 1].t)}</text>
      </svg>`;
  }

  /* ── Tab Verlauf ────────────────────────────────────────────── */

  _verlauf(b) {
    const vergleich = b.vergleich || [];
    const aktuelle = { nacht: b.nacht, dauer_minuten: b.dauer_minuten, guete: b.guete, ist_schaetzung: b.ist_schaetzung };
    const zeilen = [aktuelle, ...vergleich];
    const maxDauer = Math.max(...zeilen.map((z) => z.dauer_minuten || 0), 1);

    const html = zeilen
      .map((z, i) => {
        const balken = Math.round(((z.dauer_minuten || 0) / maxDauer) * 100);
        const etikett = i === 0 ? `<span class="etikett">diese Nacht</span>` : z.ist_schaetzung ? `<span class="etikett">grobe Schätzung</span>` : "";
        return `
          <div class="verlauf-zeile">
            <span class="datum">${this._escape(z.nacht)}</span>
            <span class="balken-wrap"><span class="balken" style="width:${balken}%;background:${guete_farbe(z.guete)}"></span></span>
            <span class="wert">${dauer_text(z.dauer_minuten)} · ${zahl(z.guete)} %</span>
            ${etikett}
          </div>`;
      })
      .join("");

    return `
      <div class="abschnittstitel">Schlafdauer und Messgüte — die letzten Nächte</div>
      ${html}
      <div class="verlauf-tabellenhinweis">
        Balkenlänge = Schlafdauer, Farbe = Messgüte (grün ≥ 80 %, amber ≥ 50 %, rot darunter).
        „grobe Schätzung“ markiert Nächte, deren Phasen aus Puls und Bewegung geschätzt wurden.
      </div>
      ${vergleich.length === 0 ? `<div class="leer">Noch keine weitere Nacht — der Vergleich wächst mit jeder Übertragung.</div>` : ""}`;
  }

  _escape(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

class RejuvenationNightReportCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._built) this._render();
  }

  _build() {
    this._built = true;
    this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      .feld { display: block; margin: 8px 0; }
      .feld label { display: block; font-size: 12px; color: var(--secondary-text-color); margin-bottom: 4px; }
      .feld select {
        width: 100%;
        padding: 8px;
        border-radius: 4px;
        border: 1px solid var(--divider-color);
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font: inherit;
      }
      .hinweis { font-size: 12px; color: var(--secondary-text-color); margin: 6px 0; }
    `;
    const box = document.createElement("div");
    box.className = "editor";
    this.shadowRoot.append(style, box);
    this._box = box;
    this._render();
  }

  _kandidaten() {
    if (!this._hass) return [];
    const gefunden = [];
    for (const id of Object.keys(this._hass.states)) {
      const attrs = this._hass.states[id] && this._hass.states[id].attributes;
      if (attrs && attrs[MARKER] === true) gefunden.push(id);
    }
    gefunden.sort();
    return gefunden;
  }

  _render() {
    if (!this._box) return;
    const kandidaten = this._kandidaten();
    const aktuell = this._config && this._config.entity;
    const optionen = [`<option value="">— Sensor automatisch erkennen —</option>`]
      .concat(
        kandidaten.map((id) => `<option value="${id}" ${id === aktuell ? "selected" : ""}>${id}</option>`)
      )
      .concat(
        aktuell && !kandidaten.includes(aktuell)
          ? [`<option value="${aktuell}" selected>${aktuell}</option>`]
          : []
      )
      .join("");
    this._box.innerHTML = `
      <div class="hinweis">Die Karte findet den Bericht-Sensor meist von selbst. Ausnahmsweise wählen —
      etwa bei zwei Betten oder wenn die Entity umbenannt wurde.</div>
      <div class="feld"><label>Bericht-Sensor</label><select data-feld="entity">${optionen}</select></div>`;

    this._box.querySelector("select").addEventListener("change", (ereignis) => {
      const wert = ereignis.target.value || null;
      this._config = { ...this._config, entity: wert };
      this.dispatchEvent(
        new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true })
      );
    });
  }
}

if (!customElements.get("rejuvenation-night-report")) {
  customElements.define("rejuvenation-night-report", RejuvenationNightReportCard);
}
customElements.define("rejuvenation-night-report-editor", RejuvenationNightReportCardEditor);

console.info("%c REJUVENATION-NIGHT-REPORT ", "background:#000;color:#42a5f5");

/* Kommt das Skript zu spaet (langsames Geraet, Aussendisplay), hat Lovelace
   die Karte schon durch "Konfigurationsfehler" ersetzt. Diese Fehlerkarten
   bleiben stehen, bis jemand neu laedt — ein ll-rebuild baut sie an Ort und
   Stelle neu auf. */
const rebuildErrorCards = () => {
  try {
    const seen = new Set();
    const walk = (root) => {
      if (!root || seen.has(root)) return;
      seen.add(root);
      root.querySelectorAll("hui-error-card").forEach((card) => {
        const type = card._config && card._config.origConfig && card._config.origConfig.type;
        if (type !== "custom:rejuvenation-night-report") return;
        card.dispatchEvent(new Event("ll-rebuild", { bubbles: true, composed: true }));
      });
      root.querySelectorAll("*").forEach((el) => el.shadowRoot && walk(el.shadowRoot));
    };
    walk(document);
  } catch {
    /* Nur Kosmetik — im Zweifel hilft weiterhin ein Neuladen der Seite. */
  }
};
rebuildErrorCards();
setTimeout(rebuildErrorCards, 2500);
