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
const LAYOUTS = ["auto", "tall", "wide"];
const LAYOUT_NAMES = {
  auto: "Automatisch",
  tall: "Hochkant",
  wide: "Breitbild",
};

/* Ab dieser Breite und diesem Seitenverhaeltnis lohnt die zweite Spalte. */
const WIDE_MIN_PX = 720;
const WIDE_MIN_RATIO = 1.25;

/* Bis zu dieser Kantenlaenge ist der Schirm ein Aussendisplay oder eine
   Kachel — dort zaehlt jeder Punkt, und nichts darf abgeschnitten werden. */
const TINY_MAX_PX = 420;

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
    align-items: stretch;
    background: var(--bg);
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .sheet.show { display: flex; animation: rise 0.28s ease; }
  @keyframes rise { from { opacity: 0; transform: translateY(14px); } }

  /* Speichern, Zurueck und Fertig stehen oben und bleiben beim Scrollen
     stehen. Unten waeren sie auf dem Aussendisplay eines Falters nicht mehr
     zu treffen — dort verdeckt die Kamera den unteren Rand. */
  .sheet .bar {
    position: sticky;
    top: 0;
    z-index: 2;
    flex: none;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 16px 22px;
    background: var(--bg);
    border-bottom: 1px solid var(--amber-faint);
  }

  .sheet-body {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 26px;
    padding: 24px 22px max(28px, env(safe-area-inset-bottom));
  }

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

  /* ── Breitbild ──
     Auf einem quer stehenden Tablet steht die Uhr links und die drei Tasten
     rechts daneben, statt dass beides in der Mitte um die Hoehe kaempft. */
  .root.is-wide {
    display: grid;
    grid-template-columns: 1.1fr minmax(300px, 0.9fr);
    grid-template-rows: 1fr auto;
    align-items: center;
    justify-items: center;
    gap: 20px 40px;
    padding: 56px 42px 26px;
  }

  .root.is-wide .clock { grid-column: 1; grid-row: 1; margin: 0; }
  .root.is-wide .time { font-size: clamp(72px, 11vw, 190px); }
  .root.is-wide .deck { grid-column: 2; grid-row: 1; margin-top: 0; }
  .root.is-wide .status { grid-column: 1 / -1; grid-row: 2; }

  /* ── Kleinstschirm ──
     Aussendisplay eines Falters, Smartwatch-artige Kacheln: rund 350 x 380
     Punkte. Die Karte darf dort keine Mindesthoehe erzwingen, sonst laeuft
     der Inhalt unten aus dem Rahmen und die drei Tasten sind nicht mehr
     erreichbar (overflow: hidden schneidet sie einfach ab). */
  .root.is-tiny {
    min-height: 0;
    gap: 8px;
    padding: 10px 10px 12px;
    border-radius: 0;
  }

  .root.is-tiny .topbar {
    position: static;
    top: auto; left: auto; right: auto;
  }
  .root.is-tiny .icon-btn { padding: 5px 8px; font-size: 9px; letter-spacing: 0.14em; }
  .root.is-tiny .icon-btn svg { width: 15px; height: 15px; }
  .root.is-tiny .clock { margin: 2px 0; }
  .root.is-tiny .time { font-size: clamp(42px, 24vw, 88px); }
  .root.is-tiny .date { margin-top: 5px; font-size: 9px; letter-spacing: 0.22em; }
  .root.is-tiny .deck { max-width: none; gap: 7px; }
  .root.is-tiny .key { gap: 10px; padding: 8px 11px; border-radius: 14px; }
  .root.is-tiny .key .glyph { width: 20px; height: 20px; }
  .root.is-tiny .key .label { font-size: 8px; letter-spacing: 0.14em; }
  .root.is-tiny .key .value { margin-top: 1px; font-size: 15px; }
  .root.is-tiny .key .aux { font-size: 10px; }
  .root.is-tiny .status { display: none; }

  /* Die Overlays scrollen auf so wenig Hoehe, statt zu klemmen. */
  .root.is-tiny .sheet .bar { padding: 8px 10px; gap: 6px; }
  .root.is-tiny .sheet .bar .chip { padding: 8px 14px; font-size: 12px; }
  .root.is-tiny .sheet-body {
    gap: 12px;
    padding: 12px 10px max(16px, env(safe-area-inset-bottom));
    justify-content: flex-start;
  }
  .root.is-tiny .dial { width: min(46vh, 180px); }
  .root.is-tiny .dial .target { font-size: 34px; }
  .root.is-tiny .dial .target sup { font-size: 14px; }
  .root.is-tiny .dial .actual { font-size: 10px; }
  .root.is-tiny .stepper { gap: 14px; }
  .root.is-tiny .stepper button { width: 44px; height: 44px; font-size: 20px; }
  .root.is-tiny .bignum { font-size: 40px; }
  .root.is-tiny .chip { padding: 8px 14px; font-size: 12px; }
  .root.is-tiny .missing { font-size: 11px; }
  .root.is-tiny input[type="range"] { width: 92%; height: 34px; }

  /* ── Nachtruhe ── */
  .root.dozing .deck,
  .root.dozing .status,
  .root.dozing .topbar { opacity: 0; pointer-events: none; }
  .root.dozing .deck,
  .root.dozing .status,
  .root.dozing .topbar,
  .root.dozing .clock { transition: opacity 1.4s ease; }
  /* Wie stark die Uhr in der Nachtruhe abdunkelt, steht in den
     Einstellungen — gesetzt wird es an der Uhr selbst. */

  /* Sicherheitsnetz, bevor die Karte sich selbst gemessen hat: auf einem
     flachen Schirm darf die Mindesthoehe den Inhalt nie herausdruecken. */
  @media (max-height: 460px) {
    .root { min-height: 0; }
  }

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
      <div class="bar">
        <h2>Wasserbett</h2>
        <div class="row"><button class="chip" type="button" data-close>Fertig</button></div>
      </div>
      <div class="sheet-body">
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
      </div>
    </div>

    <div class="sheet" id="sheet-alarm">
      <div class="bar">
        <h2>Wecker</h2>
        <div class="row">
          <button class="chip primary" type="button" id="al-save">Stellen</button>
          <button class="chip" type="button" id="al-clear">Aus</button>
          <button class="chip" type="button" data-close>Zurück</button>
        </div>
      </div>
      <div class="sheet-body">
        <div class="bignum"><span class="unit sel" id="al-hh">07</span>:<span class="unit" id="al-mm">00</span></div>
        <div class="stepper">
          <button type="button" id="al-minus" aria-label="Früher">−</button>
          <button type="button" id="al-plus" aria-label="Später">+</button>
        </div>
      </div>
    </div>

    <div class="sheet" id="sheet-light">
      <div class="bar">
        <h2>Schlafzimmerlampe</h2>
        <div class="row">
          <button class="chip primary" type="button" id="li-toggle">An / Aus</button>
          <button class="chip" type="button" id="li-night">Nachtlicht</button>
          <button class="chip" type="button" data-close>Zurück</button>
        </div>
      </div>
      <div class="sheet-body">
        <div class="bignum"><span id="li-pct">0</span><span style="font-size:24px">%</span></div>
        <input type="range" id="li-range" min="1" max="100" step="1" value="40"/>
      </div>
    </div>

    <div class="sheet" id="sheet-beds">
      <div class="bar">
        <h2>Welches Bett?</h2>
        <div class="row"><button class="chip" type="button" data-close>Zurück</button></div>
      </div>
      <div class="sheet-body">
        <div class="row" id="bed-list"></div>
      </div>
    </div>

    <div class="sheet" id="sheet-prefs">
      <div class="bar">
        <h2>Einstellungen</h2>
        <div class="row"><button class="chip primary" type="button" data-close>Fertig</button></div>
      </div>
      <div class="sheet-body">
        <h2>Zifferblatt</h2>
        <div class="row" id="face-list"></div>
        <h2>Layout</h2>
        <div class="row" id="layout-list"></div>
        <h2>Helligkeit · aktiv</h2>
        <div class="bignum" style="font-size:34px"><span id="dim-pct">100</span><span style="font-size:18px">%</span></div>
        <input type="range" id="dim-range" min="25" max="100" step="5" value="100"/>
        <h2>Helligkeit · Ruhe</h2>
        <div class="bignum" style="font-size:34px"><span id="doze-pct">45</span><span style="font-size:18px">%</span></div>
        <input type="range" id="doze-range" min="5" max="100" step="5" value="45"/>
        <p class="missing">Bedient jemand die Karte, leuchtet die Uhr mit der ersten Helligkeit — so hell wie der übrige Text. Bleibt es eine Weile still, bleibt nur die Uhr stehen und dunkelt auf die zweite ab. Gilt nur für dieses Gerät und wird sofort übernommen.</p>
      </div>
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
    this._dozePeek = null;
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
    if (config.doze && !this._prefs.doze) this._prefs.doze = String(config.doze);
    this._lastFaceKey = "";
    if (this._built) this._render();
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { type: "custom:rejuvenation-nightstand", beds: [{ name: "Bett" }] };
  }

  /* Der grafische Editor: Entities werden ausgewaehlt, nicht getippt. */
  static getConfigElement() {
    return document.createElement("rejuvenation-nightstand-editor");
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
    if (this._sizeObserver) {
      this._sizeObserver.disconnect();
      this._sizeObserver = null;
    }
    clearInterval(this._tick);
    clearTimeout(this._dozeTimer);
    clearTimeout(this._dozePeek);
    clearTimeout(this._pushTimer);
    clearTimeout(this._brightTimer);
  }

  /* ── Geraeteeinstellungen ───────────────────────────────────── */
  _loadPrefs() {
    try {
      return { face: "", dim: "", doze: "", layout: "", bed: 0, ...JSON.parse(localStorage.getItem(PREF_KEY) || "{}") };
    } catch {
      return { face: "", dim: "", doze: "", layout: "", bed: 0 };
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

  /* Am Tag leuchtet die Uhr wie der uebrige Text — alles andere sieht nach
     ausgegrauter Anzeige aus. */
  get _dim() {
    return clamp(parseInt(this._prefs.dim, 10) || 100, 25, 100);
  }

  /* In der Nachtruhe steht nur noch die Uhr da, und die darf niemanden
     wecken. */
  get _dozeDim() {
    return clamp(parseInt(this._prefs.doze, 10) || 45, 5, 100);
  }

  get _layout() {
    return LAYOUTS.includes(this._prefs.layout) ? this._prefs.layout : "auto";
  }

  /* "auto" richtet sich nach der Karte selbst, nicht nach dem Fenster: in
     einer Panel-Ansicht ist beides gleich, in einer schmalen Spalte nicht. */
  _applyLayout() {
    if (!this._built) return;
    const root = this.$("root");
    const box = root.getBoundingClientRect();
    const width = box.width || this.clientWidth;
    /* Ohne eigene Hoehe (Karte noch nicht gelayoutet) hilft das Fenster. */
    const height =
      box.height || this.clientHeight || (window.visualViewport && window.visualViewport.height) ||
      window.innerHeight || 1;

    const tiny = Boolean(width) && (width <= TINY_MAX_PX || height <= TINY_MAX_PX);

    const layout = this._layout;
    let wide;
    if (layout === "wide") {
      wide = true;
    } else if (layout === "tall") {
      wide = false;
    } else {
      wide = !tiny && width >= WIDE_MIN_PX && width / height >= WIDE_MIN_RATIO;
    }

    root.classList.toggle("is-wide", wide);
    root.classList.toggle("is-tiny", tiny);
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

    /* Der Ruhe-Regler zeigt sich sofort an der Uhr, auch wenn die Karte
       gerade wach ist — sonst stellt man blind ein. */
    $("doze-range").addEventListener("input", (event) => {
      this._prefs.doze = event.target.value;
      $("doze-pct").textContent = event.target.value;
      this.$("clock").style.opacity = String(this._dozeDim / 100);
      clearTimeout(this._dozePeek);
      this._dozePeek = setTimeout(() => this._applyDim(), 900);
      this._savePrefs();
    });

    this._paintClock();
    this._applyLayout();
    this._observeSize();
    this._scheduleDoze();
  }

  /* Dreht jemand das Tablet oder geht die Karte in den Vollbildmodus, aendert
     sich nur die Groesse — davon erfaehrt man sonst nichts. */
  _observeSize() {
    if (this._sizeObserver || typeof ResizeObserver === "undefined") return;
    this._sizeObserver = new ResizeObserver(() => this._applyLayout());
    this._sizeObserver.observe(this.$("root"));
  }

  /* ── Nachtruhe ──────────────────────────────────────────────── */
  _scheduleDoze() {
    if (!this._built) return;
    clearTimeout(this._dozeTimer);
    this.$("root").classList.remove("dozing");
    this._applyDim();
    this._dozeTimer = setTimeout(() => {
      this.$("root").classList.add("dozing");
      this._applyDim();
    }, DOZE_AFTER);
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
    const dozing = this.$("root").classList.contains("dozing");
    this.$("clock").style.opacity = String((dozing ? this._dozeDim : this._dim) / 100);
  }

  /* Das Zifferblatt wechselt ausschliesslich ueber die Anzeige-Einstellungen.
     Ein Tipp auf die Uhr tut bewusst nichts: nachts trifft man sie im Halbschlaf
     zu leicht und stand dann vor einem anderen Ziffernbild. */

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

    /* Ein Schalter kennt kein Dimmen und kein Nachtlicht — dann bleiben die
       beiden Bedienelemente weg, statt Dienste zu rufen, die es nicht gibt. */
    const dimmable = this._lightDomain === "light";
    this.$("li-range").style.display = dimmable ? "" : "none";
    this.$("li-night").style.display = dimmable ? "" : "none";
  }

  /* Als Lampe darf auch ein Schalter eingetragen sein — dann gibt es weder
     light.turn_on noch Helligkeit, und der Dienst kommt aus der Entity-ID. */
  get _lightDomain() {
    return String(this._bed.light || "").split(".")[0];
  }

  _lightSupports(mode) {
    const state = this._state(this._bed.light);
    const modes = (state && state.attributes.supported_color_modes) || [];
    return Array.isArray(modes) && modes.includes(mode);
  }

  _setBrightness(pct) {
    if (!this._bed.light) return;
    if (this._lightDomain !== "light") {
      this._call(this._lightDomain, pct ? "turn_on" : "turn_off", { entity_id: this._bed.light });
      return;
    }
    this._call("light", "turn_on", { entity_id: this._bed.light, brightness_pct: pct });
  }

  _toggleLight() {
    if (!this._bed.light) return;
    this._call(this._lightDomain, "toggle", { entity_id: this._bed.light });
  }

  /* 1 % in warmem Bernstein — genug fuer den Weg ins Bad, ohne davon wach zu
     werden. Die Farbtemperatur heisst im Dienst color_temp_kelvin; "kelvin"
     war ein Alias und wird von neueren Kernen als unbekannter Schluessel
     abgewiesen. Gesendet wird sie nur, wenn die Lampe sie ueberhaupt kennt —
     sonst laesst light.turn_on den ganzen Aufruf scheitern. */
  _nightLight() {
    if (!this._bed.light) return;
    if (this._lightDomain !== "light") {
      this._call(this._lightDomain, "turn_on", { entity_id: this._bed.light });
      this._closeSheets();
      return;
    }

    const data = { entity_id: this._bed.light, brightness_pct: 1 };
    if (this._lightSupports("color_temp")) {
      const state = this._state(this._bed.light);
      const min = Number((state && state.attributes.min_color_temp_kelvin) || 0) || 2000;
      const max = Number((state && state.attributes.max_color_temp_kelvin) || 0) || 6500;
      data.color_temp_kelvin = Math.round(clamp(2000, min, max));
    }
    this._call("light", "turn_on", data);
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

    const layouts = this.$("layout-list");
    layouts.innerHTML = "";
    LAYOUTS.forEach((layout) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip" + (layout === this._layout ? " primary" : "");
      chip.textContent = LAYOUT_NAMES[layout];
      chip.addEventListener("click", () => {
        this._prefs.layout = layout;
        this._savePrefs();
        this._applyLayout();
        this._openPrefs();
      });
      layouts.appendChild(chip);
    });

    this.$("dim-range").value = String(this._dim);
    this.$("dim-pct").textContent = String(this._dim);
    this.$("doze-range").value = String(this._dozeDim);
    this.$("doze-pct").textContent = String(this._dozeDim);
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

/* ── Grafischer Editor ───────────────────────────────────────────
 *
 * Die Entities gehoeren in die Karten-Konfiguration, nicht in die
 * Geraete-Einstellungen: sie sind fuer alle Bildschirme dieselben.
 * Hier kommen sie aus Auswahlfeldern, damit niemand Entity-IDs abtippt.
 */

const GLOBAL_SCHEMA = [
  {
    name: "face",
    selector: {
      select: {
        mode: "dropdown",
        options: FACES.map((face) => ({ value: face, label: FACE_NAMES[face] })),
      },
    },
  },
  { name: "dim", selector: { number: { min: 25, max: 100, step: 5, mode: "slider" } } },
  { name: "doze", selector: { number: { min: 5, max: 100, step: 5, mode: "slider" } } },
];

/* Welche Entity passt in welches Feld? Die Domain allein reicht nicht: unter
 * sensor. liegen zehntausend Dinge, von denen genau die Zeitstempel eine
 * Weckzeit sein koennen. Was hier durchfaellt, wird gar nicht vorgeschlagen. */
const BED_MATCH = {
  /* Ein Thermostat ohne Zieltemperatur waere eine Uhr ohne Zeiger. */
  climate: (id, state) =>
    id.startsWith("climate.") &&
    (state.attributes.temperature !== undefined || state.attributes.min_temp !== undefined),

  alarm: (id, state) => {
    if (id.startsWith("input_datetime.")) return state.attributes.has_time === true;
    if (!id.startsWith("sensor.")) return false;
    return (
      state.attributes.device_class === "timestamp" ||
      /^\d{1,2}:\d{2}(:\d{2})?$/.test(String(state.state))
    );
  },

  alarm_switch: (id) => id.startsWith("input_boolean.") || id.startsWith("switch."),

  /* Eine Lampe darf auch ein Schalter sein — dann faellt nur das Dimmen weg. */
  light: (id) => id.startsWith("light.") || id.startsWith("switch."),
};

const BED_DOMAINS = {
  climate: "climate",
  alarm: ["input_datetime", "sensor"],
  alarm_switch: ["input_boolean", "switch"],
  light: ["light", "switch"],
};

/* Passende Entities werden als Liste mitgegeben; findet sich keine (oder ist
 * hass noch nicht da), bleibt es beim Domain-Filter — lieber zu viel
 * vorschlagen als ein leeres Auswahlfeld. */
function entityPicker(field, hass, current) {
  const selector = { entity: { domain: BED_DOMAINS[field] } };
  if (!hass || !hass.states) return { name: field, selector };

  const match = BED_MATCH[field];
  const fits = Object.keys(hass.states).filter((id) => {
    try {
      return match(id, hass.states[id]);
    } catch {
      return false;
    }
  });
  /* Was schon eingetragen ist, bleibt waehlbar — sonst leert das Auswahlfeld
     eine Konfiguration, nur weil die Entity gerade nicht erreichbar ist. */
  if (current && !fits.includes(current)) fits.push(current);
  if (!fits.length) return { name: field, selector };

  return { name: field, selector: { entity: { include_entities: fits.sort() } } };
}

function bedSchema(hass, bed) {
  const pick = (field) => entityPicker(field, hass, bed ? bed[field] : "");
  return [
    { name: "name", selector: { text: {} } },
    pick("climate"),
    pick("alarm"),
    pick("alarm_switch"),
    pick("light"),
    ...BED_NUMBERS,
  ];
}

const BED_NUMBERS = [
  {
    name: "temp_min",
    selector: { number: { min: 10, max: 40, step: 0.5, mode: "box", unit_of_measurement: "°C" } },
  },
  {
    name: "temp_max",
    selector: { number: { min: 10, max: 45, step: 0.5, mode: "box", unit_of_measurement: "°C" } },
  },
];

const EDITOR_LABELS = {
  face: "Zifferblatt (Vorgabe)",
  dim: "Helligkeit in Prozent (Vorgabe)",
  doze: "Helligkeit in der Nachtruhe in Prozent (Vorgabe)",
  name: "Bezeichnung",
  climate: "Bett-Thermostat",
  alarm: "Weckzeit",
  alarm_switch: "Wecker aktiv",
  light: "Schlafzimmerlampe",
  temp_min: "Kleinste Temperatur",
  temp_max: "Groesste Temperatur",
};

const EDITOR_STYLE = `
  .rjv-ed { display: flex; flex-direction: column; gap: 16px; }
  .rjv-ed .bed {
    padding: 14px 16px;
    border: 1px solid var(--divider-color, rgba(127,127,127,0.35));
    border-radius: 12px;
  }
  .rjv-ed .bed-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
    font-weight: 500;
  }
  .rjv-ed .hint { margin: 0; font-size: 13px; color: var(--secondary-text-color, #888); }
  .rjv-ed button {
    padding: 8px 14px;
    border: 1px solid var(--divider-color, rgba(127,127,127,0.35));
    border-radius: 999px;
    background: transparent;
    color: var(--primary-color, #03a9f4);
    font: inherit;
    cursor: pointer;
  }
  .rjv-ed button.danger { color: var(--error-color, #db4437); }
`;

class RejuvenationNightstandCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = { beds: [{}] };
    this._hass = null;
    this._forms = [];
    this._bedCount = -1;
  }

  setConfig(config) {
    const beds = Array.isArray(config.beds) && config.beds.length ? config.beds : [{}];
    this._config = { ...config, beds };
    this._render();
  }

  /* Beim ersten hass entstehen die Vorschlagslisten — bis dahin kennt der
     Editor keine Entities und muss danach einmal neu aufbauen. */
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this._forms.forEach((form) => (form.hass = hass));
    if (first) this._render(true);
  }

  get _globalData() {
    return { face: this._config.face || "outline", dim: this._config.dim || 85 };
  }

  _emit(config) {
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
    );
  }

  _setBed(index, value) {
    const beds = this._config.beds.map((bed, i) => (i === index ? { ...bed, ...value } : bed));
    this._emit({ ...this._config, beds });
  }

  _addBed() {
    this._emit({ ...this._config, beds: [...this._config.beds, {}] });
    this._render(true);
  }

  _removeBed(index) {
    const beds = this._config.beds.filter((_, i) => i !== index);
    this._emit({ ...this._config, beds: beds.length ? beds : [{}] });
    this._render(true);
  }

  /* Neu aufgebaut wird nur, wenn sich die Zahl der Betten aendert — sonst
     verliert das Feld, in dem gerade getippt wird, den Fokus. */
  _render(force) {
    const beds = this._config.beds;
    if (!force && this._bedCount === beds.length && this._forms.length) {
      this._forms[0].data = this._globalData;
      beds.forEach((bed, index) => {
        const form = this._forms[index + 1];
        if (form) form.data = bed;
      });
      return;
    }

    this._bedCount = beds.length;
    this._forms = [];
    this.innerHTML = `<style>${EDITOR_STYLE}</style><div class="rjv-ed" id="ed"></div>`;
    const wrap = this.querySelector("#ed");

    const label = (item) => EDITOR_LABELS[item.name] || item.name;

    const globals = document.createElement("ha-form");
    globals.hass = this._hass;
    globals.schema = GLOBAL_SCHEMA;
    globals.data = this._globalData;
    globals.computeLabel = label;
    globals.addEventListener("value-changed", (event) => {
      event.stopPropagation();
      this._emit({ ...this._config, ...event.detail.value });
    });
    this._forms.push(globals);
    wrap.appendChild(globals);

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent =
      "Vorgeschlagen wird nur, was in das jeweilige Feld passt. " +
      "Zifferblatt und Helligkeit sind nur die Vorgabe — jedes Geraet darf sie in der Karte selbst ueberstimmen.";
    wrap.appendChild(hint);

    beds.forEach((bed, index) => {
      const box = document.createElement("div");
      box.className = "bed";

      const head = document.createElement("div");
      head.className = "bed-head";
      const title = document.createElement("span");
      title.textContent = bed.name || `Bett ${index + 1}`;
      head.appendChild(title);

      if (beds.length > 1) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "danger";
        remove.textContent = "Entfernen";
        remove.addEventListener("click", () => this._removeBed(index));
        head.appendChild(remove);
      }
      box.appendChild(head);

      const form = document.createElement("ha-form");
      form.hass = this._hass;
      form.schema = bedSchema(this._hass, bed);
      form.data = bed;
      form.computeLabel = label;
      form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        this._setBed(index, event.detail.value);
      });
      this._forms.push(form);
      box.appendChild(form);
      wrap.appendChild(box);
    });

    const add = document.createElement("button");
    add.type = "button";
    add.textContent = "Bett hinzufuegen";
    add.addEventListener("click", () => this._addBed());
    wrap.appendChild(add);

    const beds_hint = document.createElement("p");
    beds_hint.className = "hint";
    beds_hint.textContent =
      "Ein Eintrag je Bett oder je Bettseite. Ab zwei Eintraegen merkt sich jedes Geraet, welcher seiner ist.";
    wrap.appendChild(beds_hint);
  }
}

/* Das Skript kann mehrfach ins Frontend geraten (Reload der Integration,
 * zweiter Tab, alter Ressourcen-Eintrag aus /config/www). Ein zweites
 * define() wuerde werfen und die Karte im Dashboard verschwinden lassen. */
if (!customElements.get("rejuvenation-nightstand")) {
  customElements.define("rejuvenation-nightstand", RejuvenationNightstandCard);
  customElements.define("rejuvenation-nightstand-editor", RejuvenationNightstandCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "rejuvenation-nightstand",
    name: "Rejuvenation Nachttischwecker",
    description:
      "AMOLED-Weckerdisplay mit drei Tasten: Wasserbett, Wecker, Schlafzimmerlampe.",
    preview: false,
  });

  console.info("%c REJUVENATION-NIGHTSTAND ", "background:#000;color:#ffb454");

  /* Kommt das Skript zu spaet (langsames Geraet, Aussendisplay eines
   * Falters), hat Lovelace die Karte schon durch "Konfigurationsfehler"
   * ersetzt. Diese Fehlerkarten bleiben stehen, bis jemand neu laedt —
   * ein ll-rebuild baut sie an Ort und Stelle neu auf. */
  const rebuildErrorCards = () => {
    try {
      const seen = new Set();
      const walk = (root) => {
        if (!root || seen.has(root)) return;
        seen.add(root);
        root.querySelectorAll("hui-error-card").forEach((card) => {
          const type = card._config && card._config.origConfig && card._config.origConfig.type;
          if (type !== "custom:rejuvenation-nightstand") return;
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
}
