/*
 * Rejuvenation Bed — Nachttischwecker
 *
 * Lovelace-Karte. Laeuft im Home-Assistant-Frontend und spricht ueber das
 * hass-Objekt mit dem Server: kein Token, keine Adresse, keine zweite
 * Anmeldung. Die Karte wird von der Integration selbst registriert.
 *
 * Beispiel (am besten in einer Ansicht mit "Panel (1 Karte)"):
 *
 *   type: custom:rejuvenation-nightstand
 *   beds:
 *     - name: Schlafzimmer · links
 *       climate: climate.thermostat_bett_links
 *       alarm: input_datetime.wecker_links
 *       alarm_switch: input_boolean.wecker_links_aktiv
 *       light: light.schlafzimmer
 */

const FACES = ["outline", "segment", "matrix", "flip"];
const FACE_NAMES = {
  outline: "Kontur",
  segment: "7-Segment · 80er",
  matrix: "LED-Matrix · 90er",
  flip: "Klappanzeige",
};

const PREF_KEY = "rejuvenation.nightstand.prefs";
const DOZE_AFTER = 45000;

const TAGE = [
  "Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag",
];
const MONATE = [
  "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
  "Jul", "Aug", "Sep", "Okt", "Nov", "Dez",
];

const pad = (n) => String(n).padStart(2, "0");
const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

/* ── Siebensegment ──────────────────────────────────────────────
   a oben, im Uhrzeigersinn bis f, g in der Mitte. */
const hSeg = (x, y, w) =>
  `${x + 1},${y} ${x + w - 1},${y} ${x + w},${y + 1} ${x + w - 1},${y + 2} ${x + 1},${y + 2} ${x},${y + 1}`;
const vSeg = (x, y, h) =>
  `${x},${y + 1} ${x + 1},${y} ${x + 2},${y + 1} ${x + 2},${y + h - 1} ${x + 1},${y + h} ${x},${y + h - 1}`;

const SEG_SHAPES = [
  ["a", hSeg(1, 0, 10)],
  ["b", vSeg(10, 1, 9)],
  ["c", vSeg(10, 11, 9)],
  ["d", hSeg(1, 20, 10)],
  ["e", vSeg(0, 11, 9)],
  ["f", vSeg(0, 1, 9)],
  ["g", hSeg(1, 10, 10)],
];

const SEG_DIGITS = {
  0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg",
  5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg",
};

/* ── 5x7-Punktmatrix ──────────────────────────────────────────── */
const MATRIX_DIGITS = {
  0: ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
  1: ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
  2: ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
  3: ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
  4: ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
  5: ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
  6: ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
  7: ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
  8: ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
  9: ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
};

function segDigit(ch) {
  const lit = SEG_DIGITS[ch] || "";
  const shapes = SEG_SHAPES.map(
    ([key, points]) =>
      `<polygon class="s${lit.includes(key) ? " on" : ""}" points="${points}"/>`,
  ).join("");
  return `<svg class="glyph-seg" viewBox="-1 -1 14 24">${shapes}</svg>`;
}

function segColon() {
  return (
    '<svg class="glyph-seg colon" viewBox="-1 -1 5 24">' +
    '<rect class="s on" x="0" y="5" width="3" height="3" rx="0.6"/>' +
    '<rect class="s on" x="0" y="14" width="3" height="3" rx="0.6"/></svg>'
  );
}

function matrixDigit(ch) {
  const rows = MATRIX_DIGITS[ch] || MATRIX_DIGITS[8];
  let dots = "";
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      dots +=
        `<circle class="d${row[x] === "1" ? " on" : ""}" ` +
        `cx="${x + 0.5}" cy="${y + 0.5}" r="0.4"/>`;
    }
  });
  return `<svg class="glyph-mat" viewBox="-0.2 -0.2 5.4 7.4">${dots}</svg>`;
}

function matrixColon() {
  return (
    '<svg class="glyph-mat colon" viewBox="-0.2 -0.2 1.4 7.4">' +
    '<circle class="d on" cx="0.5" cy="2.5" r="0.4"/>' +
    '<circle class="d on" cx="0.5" cy="4.5" r="0.4"/></svg>'
  );
}

const STYLE = `
  :host {
    --bg: #000000;
    --amber: #ffb454;
    --amber-soft: #d9913f;
    --amber-deep: #8a5a1e;
    --amber-faint: #3a2610;
    --ink: #1a1206;
    display: block;
  }

  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

  .root {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 26px;
    min-height: min(78vh, 780px);
    padding: 26px 20px;
    border-radius: 18px;
    background: var(--bg);
    color: var(--amber-soft);
    font-family: ui-rounded, "SF Pro Rounded", "Segoe UI", system-ui, sans-serif;
    font-variant-numeric: tabular-nums;
    user-select: none;
    overflow: hidden;
  }

  /* Im Vollbild gehoert der ganze Schirm der Karte. */
  .root:fullscreen {
    height: 100vh;
    border-radius: 0;
    padding: max(24px, env(safe-area-inset-top)) 20px
      max(24px, env(safe-area-inset-bottom));
  }

  /* ── Kopfzeile ── */
  .topbar {
    position: absolute;
    top: 14px;
    left: 16px;
    right: 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    transition: opacity 1.4s ease;
  }

  .icon-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    border: 1px solid transparent;
    border-radius: 999px;
    background: transparent;
    color: var(--amber-deep);
    font: inherit;
    font-size: 11px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    cursor: pointer;
  }

  .icon-btn svg { width: 18px; height: 18px; }
  .icon-btn.bed svg { width: 13px; height: 13px; }
  .icon-btn:active { border-color: var(--amber-faint); }
  .tools { display: flex; align-items: center; gap: 2px; }
  .root.single-bed .icon-btn.bed { display: none; }

  /* ── Uhr ── */
  .clock { margin: auto 0; text-align: center; line-height: 0.92; transition: opacity 1.2s ease; }

  .time {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.04em;
    font-size: clamp(76px, 19vw, 168px);
    font-weight: 200;
    letter-spacing: -0.03em;
    line-height: 1;
    color: var(--amber);
  }

  .time .colon { animation: blink 2s steps(1, end) infinite; }
  @keyframes blink { 50% { opacity: 0.12; } }

  /* Alle Zifferblaetter sind Kontur oder schmale Leuchtsegmente:
     eine ausgefuellte Ziffer strahlt nachts zu viel Flaeche ab. */
  .face-outline .time {
    color: transparent;
    -webkit-text-stroke: 2px var(--amber);
  }
  .face-outline .colon { -webkit-text-stroke-width: 2px; }

  .glyph-seg, .glyph-mat { display: block; height: 1em; width: auto; }
  .face-segment .time { gap: 0.09em; }
  .face-matrix .time { gap: 0.12em; }
  .glyph-seg .s { fill: var(--amber); opacity: 0.055; transition: opacity 0.25s ease; }
  .glyph-seg .s.on { opacity: 1; }
  .glyph-mat .d { fill: var(--amber); opacity: 0.05; }
  .glyph-mat .d.on { opacity: 1; }

  .face-flip .time {
    gap: 0.1em;
    color: transparent;
    -webkit-text-stroke: 1.6px var(--amber);
  }
  .face-flip .flap {
    position: relative;
    padding: 0.06em 0.1em 0.1em;
    border: 1px solid var(--amber-faint);
    border-radius: 0.12em;
  }
  .face-flip .flap::after {
    content: "";
    position: absolute;
    left: 0; right: 0; top: 50%;
    border-top: 1px solid var(--amber-faint);
  }
  .face-flip .flap::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 0.12em;
    background: linear-gradient(180deg, rgba(255,180,84,0.05), transparent 48%,
      rgba(0,0,0,0.6) 52%, transparent);
  }
  .face-flip .colon { border: none; padding: 0; }

  .date {
    margin-top: 12px;
    font-size: 13px;
    letter-spacing: 0.34em;
    text-transform: uppercase;
    color: var(--amber-deep);
  }

  /* ── Drei Tasten ── */
  .deck {
    width: 100%;
    max-width: 460px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    margin-top: auto;
  }

  .key {
    display: flex;
    align-items: center;
    gap: 18px;
    width: 100%;
    padding: 18px 20px;
    border: 1px solid var(--amber-faint);
    border-radius: 22px;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: border-color 0.25s ease, background 0.25s ease, transform 0.12s ease;
  }

  .key:active { transform: scale(0.985); }
  .key.live {
    border-color: var(--amber-deep);
    background: radial-gradient(120% 160% at 0% 50%, rgba(255,180,84,0.09), transparent 62%);
  }

  .key .glyph { flex: 0 0 auto; width: 30px; height: 30px; color: var(--amber-deep); transition: color 0.25s ease; }
  .key.live .glyph { color: var(--amber); }
  .key .body { flex: 1 1 auto; min-width: 0; }
  .key .label {
    display: block;
    font-size: 11px;
    letter-spacing: 0.24em;
    text-transform: uppercase;
    color: var(--amber-deep);
  }
  .key .value {
    display: block;
    margin-top: 3px;
    font-size: 22px;
    font-weight: 300;
    color: var(--amber-soft);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .key.live .value { color: var(--amber); }
  .key .aux { flex: 0 0 auto; font-size: 12px; letter-spacing: 0.1em; color: var(--amber-deep); }

  .status {
    font-size: 10px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: var(--ink);
    min-height: 12px;
  }

  /* ── Overlays ── */
  .sheet {
    position: absolute;
    inset: 0;
    z-index: 5;
    display: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 26px;
    padding: 28px;
    background: var(--bg);
  }
  .sheet.show { display: flex; animation: rise 0.28s ease; }
  @keyframes rise { from { opacity: 0; transform: translateY(14px); } }

  .sheet h2 {
    margin: 0;
    font-size: 12px;
    font-weight: 400;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--amber-deep);
  }

  .dial {
    position: relative;
    width: min(62vh, 320px);
    aspect-ratio: 1;
    touch-action: none;
    border-radius: 50%;
    background: radial-gradient(closest-side, transparent 62%, rgba(255,180,84,0.07) 88%, transparent 100%);
  }
  .dial svg { width: 100%; height: 100%; transform: rotate(135deg); }
  .dial .track { fill: none; stroke: var(--amber-faint); stroke-width: 10; stroke-linecap: round; }
  .dial .fill { fill: none; stroke: var(--amber); stroke-width: 10; stroke-linecap: round; transition: stroke-dashoffset 0.18s ease; }
  .dial .readout {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    pointer-events: none;
  }
  .dial .target { font-size: 62px; font-weight: 200; color: var(--amber); }
  .dial .target sup { font-size: 22px; vertical-align: super; }
  .dial .actual { font-size: 12px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--amber-deep); }

  .row { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }

  .chip {
    padding: 12px 20px;
    border: 1px solid var(--amber-faint);
    border-radius: 999px;
    background: transparent;
    color: var(--amber-soft);
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .chip.primary { border-color: var(--amber-deep); color: var(--amber); }

  .stepper { display: flex; align-items: center; gap: 22px; }
  .stepper button {
    width: 58px;
    height: 58px;
    border: 1px solid var(--amber-faint);
    border-radius: 50%;
    background: transparent;
    color: var(--amber);
    font-size: 26px;
    font-weight: 200;
    line-height: 1;
    cursor: pointer;
  }

  .bignum { display: flex; align-items: baseline; gap: 6px; font-size: 66px; font-weight: 200; color: var(--amber); }
  .bignum .unit { padding: 0 6px; border-radius: 14px; cursor: pointer; }
  .bignum .unit.sel { background: rgba(255,180,84,0.12); }

  input[type="range"] {
    -webkit-appearance: none;
    appearance: none;
    width: min(78%, 320px);
    height: 44px;
    background: transparent;
    cursor: pointer;
  }
  input[type="range"]::-webkit-slider-runnable-track { height: 8px; border-radius: 4px; background: var(--amber-faint); }
  input[type="range"]::-moz-range-track { height: 8px; border-radius: 4px; background: var(--amber-faint); }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    margin-top: -9px;
    width: 26px; height: 26px;
    border: none; border-radius: 50%;
    background: var(--amber);
  }
  input[type="range"]::-moz-range-thumb {
    width: 26px; height: 26px; border: none; border-radius: 50%; background: var(--amber);
  }

  .missing { font-size: 13px; line-height: 1.6; color: var(--amber-deep); text-align: center; max-width: 320px; }

  /* ── Nachtruhe ── */
  .root.dozing .deck,
  .root.dozing .status,
  .root.dozing .topbar { opacity: 0; pointer-events: none; }
  .root.dozing .deck,
  .root.dozing .status,
  .root.dozing .topbar,
  .root.dozing .clock { transition: opacity 1.4s ease; }
  .root.dozing .clock { opacity: 0.42; }

  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
`;

const TEMPLATE = `
  <div class="root" id="root">
    <div class="topbar" id="topbar">
      <button class="icon-btn bed" id="bed-switch" type="button">
        <span id="bed-label">Bett</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
      </button>
      <span class="tools">
        <button class="icon-btn" id="btn-full" type="button" title="Vollbild">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>
        </button>
        <button class="icon-btn" id="btn-prefs" type="button" title="Anzeige">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3.2"/>
            <path d="M12 2.6v2.2M12 19.2v2.2M4.2 12H2m20 0h-2.2M6.5 6.5 5 5m14 14-1.5-1.5M17.5 6.5 19 5M5 19l1.5-1.5"/>
          </svg>
        </button>
      </span>
    </div>

    <div class="clock" id="clock">
      <div class="time" id="time"></div>
      <div class="date" id="date">&nbsp;</div>
    </div>

    <div class="deck">
      <button class="key" id="k-bed" type="button">
        <svg class="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 17h18M3 17v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4M3 17v3M21 17v3"/>
          <path d="M6 11V8a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v3"/>
          <path d="M2 14c1.4 0 1.4-1.2 2.8-1.2S6.2 14 7.6 14" opacity="0.55"/>
        </svg>
        <span class="body"><span class="label">Wasserbett</span><span class="value" id="v-bed">--,-°</span></span>
        <span class="aux" id="a-bed"></span>
      </button>

      <button class="key" id="k-alarm" type="button">
        <svg class="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M5 3 2.5 5.5M19 3l2.5 2.5"/>
        </svg>
        <span class="body"><span class="label">Wecker</span><span class="value" id="v-alarm">Aus</span></span>
        <span class="aux" id="a-alarm"></span>
      </button>

      <button class="key" id="k-light" type="button">
        <svg class="glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 18h6M10 21h4"/>
          <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8v.3h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3Z"/>
        </svg>
        <span class="body"><span class="label">Schlafzimmerlampe</span><span class="value" id="v-light">Aus</span></span>
        <span class="aux" id="a-light"></span>
      </button>
    </div>

    <div class="status" id="status">&nbsp;</div>

    <div class="sheet" id="sheet-bed">
      <h2>Wasserbett</h2>
      <div class="dial" id="dial">
        <svg viewBox="0 0 200 200">
          <circle class="track" cx="100" cy="100" r="86" id="arc-track"/>
          <circle class="fill" cx="100" cy="100" r="86" id="arc-fill"/>
        </svg>
        <div class="readout">
          <div class="target"><span id="d-target">--,-</span><sup>°</sup></div>
          <div class="actual" id="d-actual">Ist --,-°</div>
        </div>
      </div>
      <div class="stepper">
        <button type="button" id="t-minus" aria-label="Kälter">−</button>
        <button type="button" id="t-plus" aria-label="Wärmer">+</button>
      </div>
      <div class="row"><button class="chip" type="button" data-close>Fertig</button></div>
    </div>

    <div class="sheet" id="sheet-alarm">
      <h2>Wecker</h2>
      <div class="bignum"><span class="unit sel" id="al-hh">07</span>:<span class="unit" id="al-mm">00</span></div>
      <div class="stepper">
        <button type="button" id="al-minus" aria-label="Früher">−</button>
        <button type="button" id="al-plus" aria-label="Später">+</button>
      </div>
      <div class="row">
        <button class="chip primary" type="button" id="al-save">Stellen</button>
        <button class="chip" type="button" id="al-clear">Aus</button>
        <button class="chip" type="button" data-close>Zurück</button>
      </div>
    </div>

    <div class="sheet" id="sheet-light">
      <h2>Schlafzimmerlampe</h2>
      <div class="bignum"><span id="li-pct">0</span><span style="font-size:24px">%</span></div>
      <input type="range" id="li-range" min="1" max="100" step="1" value="40"/>
      <div class="row">
        <button class="chip primary" type="button" id="li-toggle">An / Aus</button>
        <button class="chip" type="button" id="li-night">Nachtlicht</button>
        <button class="chip" type="button" data-close>Zurück</button>
      </div>
    </div>

    <div class="sheet" id="sheet-beds">
      <h2>Welches Bett?</h2>
      <div class="row" id="bed-list"></div>
      <div class="row"><button class="chip" type="button" data-close>Zurück</button></div>
    </div>

    <div class="sheet" id="sheet-prefs">
      <h2>Anzeige</h2>
      <div class="row" id="face-list"></div>
      <div class="bignum" style="font-size:34px"><span id="dim-pct">85</span><span style="font-size:18px">%</span></div>
      <input type="range" id="dim-range" min="25" max="100" step="5" value="85"/>
      <p class="missing">Gilt nur für dieses Gerät — jeder stellt seine Uhr so hell, wie er sie nachts erträgt.</p>
      <div class="row"><button class="chip" type="button" data-close>Fertig</button></div>
    </div>
  </div>
`;

class RejuvenationNightstandCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._built = false;
    this._lastFaceKey = "";
    this._pendingTarget = null;
    this._pushTimer = null;
    this._brightTimer = null;
    this._dozeTimer = null;
    this._driftMinute = -1;
    this._editHH = 7;
    this._editMM = 0;
    this._editUnit = "hh";
    this._prefs = this._loadPrefs();
  }

  /* ── Konfiguration ──────────────────────────────────────────── */
  setConfig(config) {
    if (!config) throw new Error("Konfiguration fehlt");

    let beds = Array.isArray(config.beds) ? config.beds.slice() : [];
    if (!beds.length) {
      /* Kurzform ohne beds-Liste: die Entities stehen direkt in der Karte. */
      beds = [
        {
          name: config.name,
          climate: config.climate,
          alarm: config.alarm,
          alarm_switch: config.alarm_switch,
          light: config.light,
          temp_min: config.temp_min,
          temp_max: config.temp_max,
        },
      ];
    }

    this._config = { ...config, beds };
    this._bedIndex = clamp(this._prefs.bed | 0, 0, beds.length - 1);
    if (config.face && FACES.includes(config.face) && !this._prefs.face) {
      this._prefs.face = config.face;
    }
    if (config.dim && !this._prefs.dim) this._prefs.dim = String(config.dim);
    this._lastFaceKey = "";
    if (this._built) this._render();
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { type: "custom:rejuvenation-nightstand", beds: [{ name: "Bett" }] };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._render();
  }

  connectedCallback() {
    if (!this._built && this._config) this._build();
    this._tick = setInterval(() => this._paintClock(), 1000);
    this._scheduleDoze();
  }

  disconnectedCallback() {
    clearInterval(this._tick);
    clearTimeout(this._dozeTimer);
    clearTimeout(this._pushTimer);
    clearTimeout(this._brightTimer);
  }

  /* ── Geraeteeinstellungen ───────────────────────────────────── */
  _loadPrefs() {
    try {
      return { face: "", dim: "", bed: 0, ...JSON.parse(localStorage.getItem(PREF_KEY) || "{}") };
    } catch {
      return { face: "", dim: "", bed: 0 };
    }
  }

  _savePrefs() {
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify(this._prefs));
    } catch {
      /* Privater Modus o.ae. — dann gilt die Wahl eben nur bis zum Neuladen. */
    }
  }

  get _face() {
    return FACES.includes(this._prefs.face) ? this._prefs.face : "outline";
  }

  get _dim() {
    return clamp(parseInt(this._prefs.dim, 10) || 85, 25, 100);
  }

  get _bed() {
    const beds = (this._config && this._config.beds) || [{}];
    return beds[clamp(this._bedIndex, 0, beds.length - 1)] || {};
  }

  get _tempMin() {
    return parseFloat(this._bed.temp_min) || 20;
  }

  get _tempMax() {
    return parseFloat(this._bed.temp_max) || 40;
  }

  _state(entity) {
    if (!entity || !this._hass) return null;
    return this._hass.states[entity] || null;
  }

  _call(domain, service, data) {
    if (!this._hass) return Promise.resolve();
    return this._hass.callService(domain, service, data);
  }

  /* ── Aufbau ─────────────────────────────────────────────────── */
  _build() {
    const style = document.createElement("style");
    style.textContent = STYLE;
    const wrap = document.createElement("div");
    wrap.innerHTML = TEMPLATE;
    this.shadowRoot.append(style, wrap);
    this._built = true;

    const $ = (id) => this.shadowRoot.getElementById(id);
    this.$ = $;

    const ARC = 2 * Math.PI * 86;
    this._arc = ARC;
    this._sweep = 0.75;
    $("arc-track").style.strokeDasharray = `${ARC * this._sweep} ${ARC}`;
    $("arc-fill").style.strokeDasharray = `${ARC * this._sweep} ${ARC}`;

    /* Erste Beruehrung weckt nur auf und loest keine Taste aus. */
    ["pointerdown", "keydown"].forEach((evt) =>
      $("root").addEventListener(evt, (event) => this._wake(event), true),
    );

    $("clock").addEventListener("click", () => this._cycleFace());
    $("btn-full").addEventListener("click", () => this._toggleFullscreen());
    $("btn-prefs").addEventListener("click", () => this._openPrefs());
    $("bed-switch").addEventListener("click", () => this._openBeds());

    $("k-bed").addEventListener("click", () => this._openSheet("sheet-bed"));
    $("k-light").addEventListener("click", () => this._openSheet("sheet-light"));
    $("k-alarm").addEventListener("click", () => this._openAlarm());

    this.shadowRoot.querySelectorAll("[data-close]").forEach((btn) =>
      btn.addEventListener("click", () => this._closeSheets()),
    );

    $("t-plus").addEventListener("click", () => this._setTarget(this._currentTarget() + 0.5));
    $("t-minus").addEventListener("click", () => this._setTarget(this._currentTarget() - 0.5));

    const dial = $("dial");
    let dragging = false;
    const drag = (event) => {
      const temp = this._angleToTemp(event, dial);
      if (temp != null) this._setTarget(temp);
    };
    dial.addEventListener("pointerdown", (event) => {
      dragging = true;
      dial.setPointerCapture(event.pointerId);
      drag(event);
    });
    dial.addEventListener("pointermove", (event) => dragging && drag(event));
    dial.addEventListener("pointerup", () => (dragging = false));
    dial.addEventListener("pointercancel", () => (dragging = false));

    $("al-hh").addEventListener("click", () => { this._editUnit = "hh"; this._paintAlarmSheet(); });
    $("al-mm").addEventListener("click", () => { this._editUnit = "mm"; this._paintAlarmSheet(); });
    $("al-plus").addEventListener("click", () => this._nudgeAlarm(1));
    $("al-minus").addEventListener("click", () => this._nudgeAlarm(-1));
    $("al-save").addEventListener("click", () => this._saveAlarm());
    $("al-clear").addEventListener("click", () => this._clearAlarm());

    $("li-range").addEventListener("input", (event) => {
      const pct = +event.target.value;
      $("li-pct").textContent = String(pct);
      clearTimeout(this._brightTimer);
      this._brightTimer = setTimeout(() => this._setBrightness(pct), 250);
    });
    $("li-toggle").addEventListener("click", () => this._toggleLight());
    $("li-night").addEventListener("click", () => this._nightLight());

    $("dim-range").addEventListener("input", (event) => {
      this._prefs.dim = event.target.value;
      $("dim-pct").textContent = event.target.value;
      this._applyDim();
      this._savePrefs();
    });

    this._paintClock();
    this._scheduleDoze();
  }

  /* ── Nachtruhe ──────────────────────────────────────────────── */
  _scheduleDoze() {
    if (!this._built) return;
    clearTimeout(this._dozeTimer);
    this.$("root").classList.remove("dozing");
    this._dozeTimer = setTimeout(
      () => this.$("root").classList.add("dozing"),
      DOZE_AFTER,
    );
  }

  _wake(event) {
    const wasDozing = this.$("root").classList.contains("dozing");
    this._scheduleDoze();
    if (wasDozing && event) {
      event.stopPropagation();
      event.preventDefault();
    }
  }

  /* ── Vollbild ───────────────────────────────────────────────── */
  _toggleFullscreen() {
    const root = this.$("root");
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (root.requestFullscreen) {
      root.requestFullscreen().catch(() => {
        this._flash("Vollbild vom Browser abgelehnt");
      });
    } else {
      this._flash("Vollbild wird hier nicht unterstützt");
    }
  }

  /* ── Uhr ────────────────────────────────────────────────────── */
  _paintClock() {
    if (!this._built) return;
    const now = new Date();
    this._renderTime(now.getHours(), now.getMinutes());
    this.$("date").textContent =
      `${TAGE[now.getDay()]} · ${now.getDate()}. ${MONATE[now.getMonth()]}`;
    this._drift(now);
  }

  /* Die Ziffern wandern minuetlich ein paar Pixel, damit sich auf
     einem OLED-Panel ueber Nacht nichts einbrennt. */
  _drift(now) {
    if (now.getMinutes() === this._driftMinute) return;
    this._driftMinute = now.getMinutes();
    const phase = (now.getHours() * 60 + this._driftMinute) / 12;
    const dx = Math.sin(phase) * 9;
    const dy = Math.cos(phase * 0.7) * 7;
    this.$("clock").style.transform = `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)`;
  }

  _renderTime(hh, mm) {
    const face = this._face;
    const digits = `${pad(hh)}${pad(mm)}`;
    const key = `${face}|${digits}`;
    if (key === this._lastFaceKey) return;
    this._lastFaceKey = key;

    const root = this.$("root");
    FACES.forEach((name) => root.classList.remove(`face-${name}`));
    root.classList.add(`face-${face}`);

    const c = digits.split("");
    let html;
    if (face === "segment") {
      html = segDigit(c[0]) + segDigit(c[1]) + segColon() + segDigit(c[2]) + segDigit(c[3]);
    } else if (face === "matrix") {
      html = matrixDigit(c[0]) + matrixDigit(c[1]) + matrixColon() + matrixDigit(c[2]) + matrixDigit(c[3]);
    } else if (face === "flip") {
      html =
        `<span class="flap">${c[0]}</span><span class="flap">${c[1]}</span>` +
        '<span class="colon">:</span>' +
        `<span class="flap">${c[2]}</span><span class="flap">${c[3]}</span>`;
    } else {
      html =
        `<span>${c[0]}${c[1]}</span><span class="colon">:</span><span>${c[2]}${c[3]}</span>`;
    }
    this.$("time").innerHTML = html;
  }

  _applyDim() {
    this.$("clock").style.opacity = String(this._dim / 100);
  }

  _cycleFace() {
    const index = FACES.indexOf(this._face);
    this._prefs.face = FACES[(index + 1) % FACES.length];
    this._savePrefs();
    this._lastFaceKey = "";
    this._paintClock();
    this._flash(FACE_NAMES[this._face]);
  }

  _flash(text) {
    this.$("status").textContent = text;
    clearTimeout(this._flashTimer);
    this._flashTimer = setTimeout(() => this._paintStatus(), 1800);
  }

  /* ── Wasserbett ─────────────────────────────────────────────── */
  _fmt(value) {
    const n = typeof value === "number" ? value : parseFloat(value);
    return isNaN(n) ? "--,-" : n.toFixed(1).replace(".", ",");
  }

  _currentTarget() {
    if (this._pendingTarget != null) return this._pendingTarget;
    const state = this._state(this._bed.climate);
    const target = state && state.attributes ? state.attributes.temperature : null;
    return typeof target === "number" ? target : this._tempMin;
  }

  _setTarget(value) {
    this._pendingTarget = clamp(Math.round(value / 0.5) * 0.5, this._tempMin, this._tempMax);
    this._paintBed();
    clearTimeout(this._pushTimer);
    this._pushTimer = setTimeout(() => {
      const temperature = this._pendingTarget;
      this._pendingTarget = null;
      if (this._bed.climate) {
        this._call("climate", "set_temperature", {
          entity_id: this._bed.climate,
          temperature,
        });
      }
    }, 600);
  }

  _angleToTemp(event, dial) {
    const box = dial.getBoundingClientRect();
    const x = event.clientX - (box.left + box.width / 2);
    const y = event.clientY - (box.top + box.height / 2);
    let deg = (Math.atan2(y, x) * 180) / Math.PI - 135;
    while (deg < 0) deg += 360;
    if (deg > 270) return null; /* in der offenen Luecke unten */
    return this._tempMin + (deg / 270) * (this._tempMax - this._tempMin);
  }

  _paintBed() {
    const state = this._state(this._bed.climate);
    const attrs = (state && state.attributes) || {};
    const actual = attrs.current_temperature;
    const target = this._currentTarget();
    const heating = attrs.hvac_action === "heating";
    const off = !state || state.state === "off" || state.state === "unavailable";

    this.$("v-bed").textContent = !this._bed.climate
      ? "nicht gesetzt"
      : off
        ? "Aus"
        : `${this._fmt(actual)}°`;
    this.$("a-bed").textContent =
      !this._bed.climate || off ? "" : heating ? "heizt" : `Ziel ${this._fmt(target)}°`;
    this.$("k-bed").classList.toggle("live", Boolean(heating));

    this.$("d-target").textContent = this._fmt(target);
    this.$("d-actual").textContent = `Ist ${this._fmt(actual)}°`;

    const span = this._tempMax - this._tempMin;
    const frac = span <= 0 ? 0 : clamp((target - this._tempMin) / span, 0, 1);
    this.$("arc-fill").style.strokeDashoffset = String(this._arc * this._sweep * (1 - frac));
  }

  /* ── Wecker ─────────────────────────────────────────────────── */
  _parseAlarm() {
    const state = this._state(this._bed.alarm);
    if (!state || !state.state) return null;
    const attrs = state.attributes || {};
    if (typeof attrs.hour === "number" && typeof attrs.minute === "number") {
      return { hh: attrs.hour, mm: attrs.minute };
    }
    const match = /(\d{1,2}):(\d{2})/.exec(state.state);
    return match ? { hh: +match[1], mm: +match[2] } : null;
  }

  _alarmActive() {
    const time = this._parseAlarm();
    if (!time) return false;
    if (!this._bed.alarm_switch) return true;
    const state = this._state(this._bed.alarm_switch);
    return state ? state.state === "on" : true;
  }

  _countdown(time) {
    const now = new Date();
    const next = new Date(now);
    next.setHours(time.hh, time.mm, 0, 0);
    if (next <= now) next.setDate(next.getDate() + 1);
    const mins = Math.round((next - now) / 60000);
    const h = Math.floor(mins / 60);
    return h > 0 ? `in ${h} h ${mins % 60} min` : `in ${mins} min`;
  }

  _paintAlarm() {
    const time = this._parseAlarm();
    const active = this._alarmActive();
    this.$("v-alarm").textContent = !this._bed.alarm
      ? "nicht gesetzt"
      : time
        ? `${pad(time.hh)}:${pad(time.mm)}`
        : "Aus";
    this.$("k-alarm").classList.toggle("live", active);
    this.$("a-alarm").textContent = active ? this._countdown(time) : time ? "aus" : "";
  }

  _paintAlarmSheet() {
    this.$("al-hh").textContent = pad(this._editHH);
    this.$("al-mm").textContent = pad(this._editMM);
    this.$("al-hh").classList.toggle("sel", this._editUnit === "hh");
    this.$("al-mm").classList.toggle("sel", this._editUnit === "mm");
  }

  _nudgeAlarm(delta) {
    if (this._editUnit === "hh") this._editHH = (this._editHH + delta + 24) % 24;
    else this._editMM = (this._editMM + delta * 5 + 60) % 60;
    this._paintAlarmSheet();
  }

  _openAlarm() {
    const time = this._parseAlarm();
    if (time) {
      this._editHH = time.hh;
      this._editMM = time.mm;
    }
    this._editUnit = "hh";
    this._paintAlarmSheet();
    this._openSheet("sheet-alarm");
  }

  async _saveAlarm() {
    if (this._bed.alarm) {
      await this._call("input_datetime", "set_datetime", {
        entity_id: this._bed.alarm,
        time: `${pad(this._editHH)}:${pad(this._editMM)}:00`,
      });
    }
    if (this._bed.alarm_switch) {
      await this._call("input_boolean", "turn_on", { entity_id: this._bed.alarm_switch });
    }
    this._closeSheets();
  }

  async _clearAlarm() {
    if (this._bed.alarm_switch) {
      await this._call("input_boolean", "turn_off", { entity_id: this._bed.alarm_switch });
    } else {
      this._flash("Ohne alarm_switch bleibt der Wecker stehen");
    }
    this._closeSheets();
  }

  /* ── Lampe ──────────────────────────────────────────────────── */
  _paintLight() {
    const state = this._state(this._bed.light);
    const on = state && state.state === "on";
    const brightness = state && state.attributes ? state.attributes.brightness : null;
    const pct = on && typeof brightness === "number"
      ? Math.max(1, Math.round((brightness / 255) * 100))
      : 0;

    this.$("v-light").textContent = !this._bed.light
      ? "nicht gesetzt"
      : on
        ? pct ? `An · ${pct} %` : "An"
        : "Aus";
    this.$("k-light").classList.toggle("live", Boolean(on));
    this.$("a-light").textContent = this._bed.light && !on ? "aus" : "";
    this.$("li-pct").textContent = String(pct || 0);
    if (pct) this.$("li-range").value = String(pct);
  }

  _setBrightness(pct) {
    if (!this._bed.light) return;
    this._call("light", "turn_on", { entity_id: this._bed.light, brightness_pct: pct });
  }

  _toggleLight() {
    if (!this._bed.light) return;
    this._call("light", "toggle", { entity_id: this._bed.light });
  }

  /* 1 % in warmem Bernstein — genug fuer den Weg ins Bad, ohne
     davon wach zu werden. */
  _nightLight() {
    if (!this._bed.light) return;
    this._call("light", "turn_on", {
      entity_id: this._bed.light,
      brightness_pct: 1,
      kelvin: 2000,
    });
    this._closeSheets();
  }

  /* ── Overlays ───────────────────────────────────────────────── */
  _openSheet(id) {
    this._closeSheets();
    this.$(id).classList.add("show");
  }

  _closeSheets() {
    this.shadowRoot.querySelectorAll(".sheet.show").forEach((el) => el.classList.remove("show"));
  }

  _openBeds() {
    const list = this.$("bed-list");
    list.innerHTML = "";
    this._config.beds.forEach((entry, index) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + (index === this._bedIndex ? " primary" : "");
      chip.textContent = (entry.name || "").trim() || `Bett ${index + 1}`;
      chip.addEventListener("click", () => {
        this._bedIndex = index;
        this._prefs.bed = index;
        this._savePrefs();
        this._closeSheets();
        this._render();
      });
      list.appendChild(chip);
    });
    this._openSheet("sheet-beds");
  }

  _openPrefs() {
    const list = this.$("face-list");
    list.innerHTML = "";
    FACES.forEach((face) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + (face === this._face ? " primary" : "");
      chip.textContent = FACE_NAMES[face];
      chip.addEventListener("click", () => {
        this._prefs.face = face;
        this._savePrefs();
        this._lastFaceKey = "";
        this._paintClock();
        this._openPrefs();
      });
      list.appendChild(chip);
    });
    this.$("dim-range").value = String(this._dim);
    this.$("dim-pct").textContent = String(this._dim);
    this._openSheet("sheet-prefs");
  }

  /* ── Zeichnen ───────────────────────────────────────────────── */
  _paintStatus() {
    const missing = ["climate", "alarm", "light"].filter((key) => !this._bed[key]);
    this.$("status").textContent = missing.length
      ? `Nicht konfiguriert: ${missing.join(", ")}`
      : " ";
  }

  _render() {
    if (!this._built || !this._config) return;
    const beds = this._config.beds;
    this._bedIndex = clamp(this._bedIndex, 0, beds.length - 1);
    this.$("root").classList.toggle("single-bed", beds.length < 2);
    this.$("bed-label").textContent =
      (this._bed.name || "").trim() || `Bett ${this._bedIndex + 1}`;

    this._applyDim();
    this._paintClock();
    this._paintBed();
    this._paintAlarm();
    this._paintLight();
    this._paintStatus();
  }
}

/* Das Skript kann mehrfach ins Frontend geraten (Reload der Integration,
 * zweiter Tab, alter Ressourcen-Eintrag aus /config/www). Ein zweites
 * define() wuerde werfen und die Karte im Dashboard verschwinden lassen. */
if (!customElements.get("rejuvenation-nightstand")) {
  customElements.define("rejuvenation-nightstand", RejuvenationNightstandCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "rejuvenation-nightstand",
    name: "Rejuvenation Nachttischwecker",
    description:
      "AMOLED-Weckerdisplay mit drei Tasten: Wasserbett, Wecker, Schlafzimmerlampe.",
    preview: false,
  });

  console.info("%c REJUVENATION-NIGHTSTAND ", "background:#000;color:#ffb454");
}
