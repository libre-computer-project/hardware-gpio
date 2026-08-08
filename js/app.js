/* Libre Computer GPIO Pinout — frontend logic (no dependencies). */
"use strict";

/* Function classes. `color` mirrors --c-<key> in css/style.css. */
const CLASS_INFO = {
  /* The supply rails are one warm ramp ordered by voltage, and lightness
     carries the ordering: 12V L*43, 5V L*54, 3.3V L*62, the low rails L*76.
     Higher voltage reads deeper and more alarming, which is the only reading
     that is safe to be wrong about. 12V gets its own deeper red rather than
     sharing 5V's: on Renegade Elite J21 the two sit four pins apart, and one
     swatch for both would make the drawing unable to tell them apart at
     exactly the place it matters (dE 19 in CIE Lab, against 5.5 for the
     closest pair already in this table). 1.8V and 3.0V share one class --
     each is a single pin on a single board, the pin's own name says which,
     and what the colour has to say is "supply, not signal". */
  /* PoE sits at the top of that same ramp and is drawn as its top: L*21,
     below 12V's L*43, because it is the one thing on any of these boards that
     can present a voltage the board neither makes nor limits -- a PSE drives
     up to 57 V DC into Renegade Elite's J1, which is the RJ45 magnetics'
     centre taps on a 2x3 header with no rectifier or current limit in
     between. Deep enough to read as "do not bridge this to anything", and
     dE 38.5 in CIE Lab from 12V, which is the neighbour that matters: J6
     (12V) and J1 (PoE) are two headers on one sheet. Nearest class of any
     kind is dE 33.7 (video), against 5.5 for the closest pair already in this
     table. It is deliberately NOT "eth": that is a green, and green on this
     page means signal. */
  poe:      { label: "PoE (hazardous)",    short: "PoE",       color: "#6e0011" },
  power12v: { label: "12V power",          short: "12V",       color: "#cc0f1b" },
  power5v:  { label: "5V power",           short: "5V",        color: "#e5484d" },
  power3v3: { label: "3.3V power",         short: "3.3V",      color: "#f76b15" },
  powerlv:  { label: "Low-voltage rail",   short: "Rail",      color: "#e8b17a" },
  gnd:      { label: "Ground",             short: "GND",       color: "#454b54" },
  /* Not connected: a pad that is on the connector and wired to nothing. The
     colour has to do two opposite things -- be visible enough that the
     position reads as DRAWN (the whole point of carrying the row), and be
     quiet enough that it never competes with a live signal. So: lower
     lightness and lower chroma than every signal class, a warm neutral
     rather than a slate. Warm, specifically, because the one confusion that
     would be dangerous is NC vs ground, and on J12 the two are adjacent
     (11/12 GND, 13-30 NC) -- GND is a cool slate, this is its opposite hue
     at a different lightness, dE 15.8 apart in CIE Lab, against 5.5 for the
     closest pair already in this table. dE 16.0 from the pin background, so
     an NC pad still reads as a pad and not as a hole in the drawing. */
  nc:       { label: "Not connected",      short: "NC",        color: "#3c3a2e" },
  gpio:     { label: "GPIO",                                   color: "#46a758" },
  i2c:      { label: "I2C",                                    color: "#eac54f" },
  spi:      { label: "SPI",                                    color: "#3b82f6" },
  uart:     { label: "UART / serial",      short: "UART",      color: "#a855f7" },
  pwm:      { label: "PWM",                                    color: "#ec5f87" },
  /* One class per audio bus. They are not variants of each other: I2S, PCM
     and TDM are separate controllers with separate pin groups, and a codec
     wired for one will not work on another. Colours are spaced in CIE Lab
     (worst in-family pair 15.1, nearest non-audio class 18.5) because several
     of them can land on the same pin's strip set. */
  i2s:      { label: "I2S",                                    color: "#1098ad" },
  pcm:      { label: "PCM",                                    color: "#0b7285" },
  tdm:      { label: "TDM",                                    color: "#63e6be" },
  spdif:    { label: "S/PDIF",             short: "SPDIF",     color: "#862e9e" },
  pdm:      { label: "PDM / DMIC",         short: "PDM",       color: "#5c940d" },
  /* Both directions: La Frite's line-out and the meson AL_CH/AR_CH muxes, and
     Renegade Elite's codec header, which brings out HPO_L/R alongside MIC_IN
     and LINE_IN. Labelling that header "analog audio out" would be a mislabel
     in the same class as painting it green. */
  dac:      { label: "Analog audio",       short: "Audio",     color: "#087f5b" },
  adc:      { label: "ADC",                                    color: "#94d82d" },
  clk:      { label: "Clock",                                  color: "#adb5bd" },
  jtag:     { label: "JTAG",                                   color: "#ff922b" },
  cec:      { label: "CEC",                                    color: "#7048e8" },
  ir:       { label: "IR / remote",        short: "IR",        color: "#f06595" },
  sdio:     { label: "SDIO / SD card",     short: "SDIO",      color: "#66d9e8" },
  nand:     { label: "NAND / flash",       short: "NAND",      color: "#8d6e63" },
  video:    { label: "TS / camera / video", short: "Video",    color: "#c2255c" },
  pcie:     { label: "PCI Express",        short: "PCIe",      color: "#b197fc" },
  usb:      { label: "USB",                                    color: "#74c0fc" },
  eth:      { label: "Ethernet",           short: "ETH",       color: "#12b886" },
  misc:     { label: "Other / control",    short: "Other",     color: "#6c757d" },
};

/* Function token -> class. First match wins, so order is load-bearing:
   UART_EE_B_TX-PWM_D is a UART pin, CLKOUT_GMAC is Ethernet not clock. */
const FUNC_RULES = [
  [/^12V$|12V$/i,                             "power12v"],
  [/^3\.3V$|^VCC3/i,                          "power3v3"],
  [/^5V$|^VCC5/i,                             "power5v"],
  [/^VCC_?1V8$|^VCCA?3V0/i,                   "powerlv"],
  [/^GND$/i,                                  "gnd"],
  /* Ahead of the clock rule: PCIE_REF_CLKN is a lane pair's reference clock,
     and it belongs with the lanes it clocks, not with CLK32K_OUT. */
  [/^PCIE/i,                                  "pcie"],
  [/JTAG/i,                                   "jtag"],
  [/CEC/i,                                    "cec"],
  [/IR_REMOTE|REMOTE_OUT/i,                   "ir"],
  [/SARADC|^ADC/i,                            "adc"],
  /* Audio master clocks are clocks: MCLK and the meson AM_CLK feed a codec,
     they do not carry samples. The bus's own SCLK/LRCLK stay with the bus. */
  [/MCLK|AM_CLK/i,                            "clk"],
  [/SPDIF/i,                                  "spdif"],
  [/^(PDM|DMIC)/i,                            "pdm"],
  [/^A[LR]_CH/i,                              "dac"],
  [/^TDM/i,                                   "tdm"],
  [/^PCM/i,                                   "pcm"],
  [/^I2S|I2SOUT|LRCK|WORLD_SYNC/i,            "i2s"],
  [/^I2C|^TWI|^HDMITX_S[CD]/i,                "i2c"],
  [/^SPI/i,                                   "spi"],
  [/UART/i,                                   "uart"],
  [/PWM/i,                                    "pwm"],
  [/^SDIO|^SDMMC|^CARD_/i,                    "sdio"],
  [/^NAND|^FLASH_/i,                          "nand"],
  [/^TSIN|^TSP_|^CIF_|^CVBS|^ISO7816/i,       "video"],
  [/^USB/i,                                   "usb"],
  [/FEPHY|GMAC|^ETH/i,                        "eth"],
  [/^CLK|CLKOUT|CLK_32K/i,                    "clk"],
  [/^GPIO|EINT|_gpio$/i,                      "gpio"],
];

const selectEl = document.getElementById("board-select");
const searchEl = document.getElementById("search");
const diagramEl = document.getElementById("diagram");
const detailEl = document.getElementById("pin-detail");
const legendEl = document.getElementById("legend");
const tooltipEl = document.getElementById("tooltip");
const sheetCloseEl = document.getElementById("sheet-close");

/* Pre-production and unreleased boards ship in the data but stay out of the
   picker until ?hidden=1 asks for them. */
const STATUS_LABEL = { preprod: "pre-production", unreleased: "unreleased" };

let boardIndex = [];       /* every board in data/boards.json */
let visibleBoards = [];    /* the ones this visitor may pick */
let showHidden = false;
let board = null;
let classFilter = null;   /* legend click: show only pins offering this class */
/* What the header rails are labelled with. null = the SoC pad name; otherwise
   the mux name each pin takes for the focused class or function, so the
   diagram reads as the bus rather than as a list of pad numbers. */
let labelFocus = null;    /* {cls} | {func} */
let resizeTimer = 0;

async function init() {
  try {
    boardIndex = (await fetchJSON("data/boards.json")).boards;
  } catch (e) {
    diagramEl.innerHTML =
      '<p class="muted">Could not load board data. Serve this directory over HTTP ' +
      "(e.g. <code>python3 -m http.server</code>) — <code>file://</code> blocks fetch().</p>";
    return;
  }
  const params = new URLSearchParams(location.search);
  showHidden = ["1", "true", "yes"].includes((params.get("hidden") || "").toLowerCase());
  visibleBoards = boardIndex.filter((b) => showHidden || !b.hidden);
  buildSelect();
  markHiddenMode();
  const wanted = params.get("board");
  const initial = visibleBoards.find((b) => b.id === wanted) ||
    visibleBoards.find((b) => b.id === "aml-s905x-cc") || visibleBoards[0];
  selectEl.value = initial.id;
  selectEl.addEventListener("change", () => loadBoard(selectEl.value));
  searchEl.addEventListener("input", applySearch);
  /* pointerover/-out rather than mouseover/-out, so the handler can see what
     the pointer WAS -- a touch synthesises a mouseover the tooltip has no way
     to tell from a real one. See onPinOver. */
  diagramEl.addEventListener("pointerover", onPinOver);
  diagramEl.addEventListener("pointerout", onPinOut);
  diagramEl.addEventListener("click", onPinClick);
  legendEl.addEventListener("click", onLegendClick);
  detailEl.addEventListener("click", onDetailClick);
  sheetCloseEl.addEventListener("click", closeDetail);
  /* The board view's fit depends on the window, and it has to be able to come
     BACK when the window grows again -- so this re-tests rather than only
     giving up. Re-testing instead of re-rendering keeps the selected pin, the
     search and the relabel exactly where they were. */
  addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(fitBoardView, 120);
  });
  await loadBoard(initial.id);
}

function fetchJSON(url) {
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(url + ": HTTP " + r.status);
    return r.json();
  });
}

function buildSelect() {
  const vendors = [...new Set(visibleBoards.map((b) => b.vendor))];
  for (const vendor of vendors) {
    const group = document.createElement("optgroup");
    group.label = vendor;
    for (const b of visibleBoards.filter((b) => b.vendor === vendor)) {
      const opt = document.createElement("option");
      opt.value = b.id;
      opt.textContent = `${b.name} (${b.model})` +
        (STATUS_LABEL[b.status] ? ` — ${STATUS_LABEL[b.status]}` : "");
      group.appendChild(opt);
    }
    selectEl.appendChild(group);
  }
}

/* Say so, loudly, when the picker is showing boards nobody can buy yet. */
function markHiddenMode() {
  if (!showHidden) return;
  const n = boardIndex.filter((b) => b.hidden).length;
  const flag = document.createElement("span");
  flag.id = "hidden-flag";
  flag.textContent = `+${n} unlisted`;
  flag.title = "?hidden=1 — pre-production and unannounced boards are listed";
  document.getElementById("brand").appendChild(flag);
}

async function loadBoard(id) {
  board = await fetchJSON(`data/${id}.json`);
  searchEl.value = "";
  classFilter = null;
  render();
  const url = new URL(location.href);
  url.searchParams.set("board", id);
  history.replaceState(null, "", url);
}

/* ---- function classification ---- */

function funcClass(name) {
  for (const [re, cls] of FUNC_RULES) if (re.test(name)) return cls;
  return "misc";
}

/* Every mux this pin can be switched to, as an ordered, de-duplicated class
   list. GPIO is mux 0 on every muxable pad, so it leads. */
function muxClasses(p) {
  if (p.type !== "gpio") return [p.cls];
  const out = ["gpio"];
  for (const f of p.funcs) {
    const c = funcClass(f);
    if (!out.includes(c)) out.push(c);
  }
  return out;
}

/* What the board itself calls this pin -- the silkscreen's colour, not the
   SoC's full mux list. Boards paint the header's I2C pins yellow and its SPI
   block blue; every other muxable pad is just a green GPIO. SPI wins a tie
   because the shared pads (e.g. Le Potato 23/24, I2C_x_D + SPI_SCLK/SS0) sit
   in the header's SPI block. */
function primaryClass(p) {
  if (p.type !== "gpio") return p.cls;               /* 5V, 3.3V, GND */
  if (p.funcs.some((f) => /^SPI/i.test(f))) return "spi";
  if (p.funcs.some((f) => /^(I2C|TWI)/i.test(f))) return "i2c";
  return "gpio";
}

/* Analog header pins -- the SoC's SARADC inputs and the audio DAC's line-out --
   are not digital GPIO pads: they have no mux, no pull or drive control, and
   the DC thresholds in the datasheet's digital-GPIO table do not describe them.
   The generator marks them in the data (elec.pad_type === "analog"); the
   diagram draws their tile round so they read as different silicon rather than
   as one more green GPIO. */
function isAnalog(p) {
  return Boolean(p.elec && p.elec.pad_type === "analog");
}

/* ---- board view ----

   Where the connectors are drawn, when the board file says where they ARE.

   `layout` carries each header's pad bounding box in millimetres, measured off
   that board's own CAD export (tools/pcb_layout.py). What it does NOT support
   is drawing the headers to scale: a 40-pin header is two rails of pad names
   wide, which is hundreds of pixels for a connector 2.5 mm across, so a
   to-scale board would either be unreadable or the size of a wall. So the
   millimetres decide the ARRANGEMENT and nothing else — which header is left
   of which, which is above which — and the note beside the drawing says so
   rather than letting the frame imply a scale it does not have.

   The arrangement is a grid rather than free positioning because free
   positioning of blocks whose size has nothing to do with the board's is just
   overlap by another name. Tracks come from the connectors' own spans: two
   headers share a column when their x ranges overlap (so a run of overlapping
   connectors is one column, and a gap is a column boundary), and the same
   along y. That is a fact about the board, not a threshold someone tuned. */

/* Connected runs of overlapping [lo, hi] spans, in order. Returns, per input
   index, which run it fell in. */
function spanTracks(spans) {
  const order = spans.map((s, i) => i).sort((a, b) => spans[a][0] - spans[b][0]);
  const track = new Array(spans.length);
  let n = -1;
  let end = -Infinity;
  for (const i of order) {
    if (spans[i][0] > end) n += 1;      /* clear of everything so far: new track */
    track[i] = n;
    end = Math.max(end, spans[i][1]);
  }
  return { track, count: n + 1 };
}

/* null unless the board file places EVERY header. A board view missing one
   connector reads as a board that does not have it — the generator refuses to
   emit a partial layout for the same reason, and this is the second half of
   that guarantee: data that arrives incomplete anyway falls back rather than
   drawing most of a board. */
function measuredGrid() {
  const lay = board.layout;
  if (!lay || !lay.headers || !lay.board) return null;
  const ids = board.headers.map((h) => h.id);
  if (!ids.every((id) => lay.headers[id])) return null;

  /* Two frame changes, and only one of them is a fact.
     +y is up in the CAD data (that is the frame the board was laid out in) and
     down on a screen, so the vertical span is flipped here rather than in the
     data — that one is forced.
     `orient` is the other, and is a CHOICE the data cannot make: a CAD frame
     fixes the connectors relative to each other and never says which edge the
     reader holds towards them, so 0 and 180 are both faithful. The board file
     carries the choice and its own provenance beside it (layout.orient_source)
     rather than this file assuming one. 180 is a rotation, so it mirrors both
     axes; the millimetres it reads are untouched. */
  const flip = lay.orient === 180;
  const xs = ids.map((id) => {
    const h = lay.headers[id];
    return flip ? [lay.board.w - h.x2, lay.board.w - h.x1] : [h.x1, h.x2];
  });
  const ys = ids.map((id) => {
    const h = lay.headers[id];
    return flip ? [h.y1, h.y2] : [lay.board.h - h.y2, lay.board.h - h.y1];
  });
  const cols = spanTracks(xs);
  const rows = spanTracks(ys);
  const at = new Map();
  ids.forEach((id, i) => at.set(id,
    { col: cols.track[i], row: rows.track[i], span: 1 }));
  return { at, cols: cols.count, rows: rows.count, kind: "measured",
           source: lay.source + (flip ? " · " + lay.orient_source : ""),
           board: lay.board };
}

/* The arrangement a board's OWNER specified. Read from a different key than
   `layout` on purpose: it is a different claim — how to group the connectors,
   from someone holding the board, rather than where they are — and the note
   beside the drawing says which one is on screen.

   The require-every-header rule above does NOT apply here, and its absence is
   the point. A measured layout missing a header is data that failed; an
   authored one missing a header is a direction that did not cover it, which
   the generator refuses to paper over with an invented cell. Those fall to a
   row of their own at the bottom, after everything the direction did place.

   `overrides` is set when the board ALSO carries a measurement, i.e. when this
   arrangement is drawn in place of one. It changes nothing about the grid and
   everything about the note: a drawing that departs from the board's own CAD
   data has to say so, or the reader takes the departure for the board. */
function authoredGrid() {
  const arr = board.arrangement;
  if (!arr || !arr.cells) return null;
  const at = new Map();
  let cols = 0;
  let rows = 0;
  for (const h of board.headers) {
    const c = arr.cells[h.id];
    if (!c) continue;
    at.set(h.id, { col: c[0], row: c[1], span: c[2] || 1 });
    cols = Math.max(cols, c[0] + (c[2] || 1));
    rows = Math.max(rows, c[1] + 1);
  }
  if (!at.size) return null;
  /* One row each, so an unplaced connector never reads as sharing a position
     with another — the thing a shared cell means everywhere else here. */
  for (const h of board.headers) {
    if (!at.has(h.id)) at.set(h.id, { col: 0, row: rows++, span: cols });
  }
  const measured = board.layout && board.layout.source;
  return { at, cols, rows, kind: "authored",
           overrides: Boolean(measured),
           /* Both citations, because both are load-bearing now: what is drawn,
              and what was measured and is not being drawn. */
           source: arr.source + (measured ? " · Measurement not drawn: " + measured : "") };
}

/* The board owner's rule for boards built around the 40-pin header.
   In one sentence: **where every other connector on the board, stacked one
   above another, is still shorter than the 40-pin header is tall, they are
   drawn in a single column beside it.**

   That is a statement about the only resource the drawing is short of. A 40-pin
   header is 20 pin rows tall and about two rails of pad names wide; the other
   connectors on these boards are 3 to 8 pins, one or two rows apiece. Beside the
   40-pin header there is therefore a column-shaped hole roughly 20 rows deep
   that the drawing is already paying for, and the whole question is whether the
   rest of the board fits in it. Where it does, the column is free — the diagram
   gets no taller and no other block gets narrower — and the alternative is
   leaving that hole empty while the small connectors queue up underneath. Where
   it does not, the rule declines and the packed layout, which can wrap into as
   many columns as the window gives it, keeps the board.

   Height is the test rather than the header count because height is what is
   actually being spent. The count version of this rule — "a 40-pin header and
   exactly one other" — fired on six boards and could not say why seven was six
   plus one exception; it stopped at two connectors and left La Frite needing a
   per-board arrangement to do what the same reasoning already implied. It is
   also why there is no minimum size on the "other" connectors: a 3-pin header
   in the right column reads sparse, but it reads sparse in the packed layout
   too, with the whole right half of the diagram empty behind it.

   ONE column, not two or a grid. A second right-hand column costs width, and
   width is what the pad names are competing for (see the min-width note in the
   board-view CSS); depth beside the 40-pin header costs nothing until it runs
   out, at which point the rule stops rather than spending the scarce axis. The
   small connectors stack in the order the page already lists them — the wiring
   map's, after the 40-pin hoist — because inventing a different order here
   would be a claim about the board, and this rule has none to make.

   Still a rule about a SHAPE of board, so it is still deliberately NOT a key in
   the board file. `layout` is millimetres off THIS board's export and
   `arrangement` is a direction naming THIS board's connectors; a rule read off
   the header list is neither, and serialising it into nine board files beside
   Renegade Elite's one arrangement would make a computed default
   indistinguishable from nine directions somebody gave. Its only input is the
   header list the file already carries, so it is computed here.

   Owner, 2026-08-08, in three parts: "when it's just 40P header and one other
   header. make use of the right side space and put the other header on the
   right side."; "for La Frite, 2J2 and 9J5 should be one on top of another to
   make better use of the space."; and "das frite, le potato, sweet potato all
   need this fix. we need to improve heuristics rather than hard code." */
/* The connector the direction (and the page) is about, in positions — the same
   count HEADER_FIRST_POSITIONS orders by in the generator and the header title
   shows, so "40P header" means the same thing in all three. */
const MAIN_HEADER_POSITIONS = 40;

/* What a connector costs the drawing vertically, in pin rows — the unit the
   diagram is actually built out of. A dual-row header draws two pads per row,
   which is the whole reason a 40-pin connector is the SHORT way round and has
   room beside it. Positions, not map rows: a pin wired to two SoC lines is two
   rows in the data and one pad on the connector. */
function headerPositions(h) {
  return new Set(h.pins.map((p) => p.pin)).size;
}

function headerRows(h) {
  const n = headerPositions(h);
  return h.rows === 2 ? Math.ceil(n / 2) : n;
}

function ruleGrid() {
  const main = board.headers.find(
    (h) => headerPositions(h) === MAIN_HEADER_POSITIONS);
  if (!main) return null;
  const others = board.headers.filter((h) => h !== main);
  if (!others.length) return null;
  /* Strict: equal heights would fill the column exactly in pin rows and then
     overrun it by the titles and gaps the stacked blocks also carry. */
  if (others.reduce((n, h) => n + headerRows(h), 0) >= headerRows(main)) {
    return null;
  }
  const at = new Map([[main.id, { col: 0, row: 0, span: 1 }]]);
  /* One shared cell, which is how the measured path already draws connectors at
     one position: the cell is a flex column, so they stack inside it. Separate
     grid ROWS would not stack them — row 0's height is set by the 40-pin
     header, so the second connector would land far below the first, which is
     the empty space this rule exists to remove. */
  for (const h of others) at.set(h.id, { col: 1, row: 0, span: 1 });
  const measured = board.layout && board.layout.source;
  return { at, cols: 2, rows: 1, kind: "rule",
           overrides: Boolean(measured),
           source: 'Layout rule from the board owner, 2026-08-08: "when it\'s '
                 + 'just 40P header and one other header. make use of the right '
                 + 'side space and put the other header on the right side", '
                 + 'and, of La Frite\'s two: "2J2 and 9J5 should be one on top '
                 + 'of another to make better use of the space" — generalised '
                 + 'at the owner\'s direction ("we need to improve heuristics '
                 + 'rather than hard code") to every board whose other '
                 + 'connectors, stacked, are shorter than its 40-pin header. It '
                 + 'is read off this board\'s header list, so it is not a '
                 + 'statement about where any connector sits on this PCB'
                 + (measured ? ' — and this board IS measured: ' + measured
                             + '. That measurement is unchanged in its data; it '
                             + 'is simply not what is drawn' : '') };
}

/* Most specific statement about the DRAWING, first — which is not the same
   axis as most specific statement about the board, and the difference is the
   whole of this chain.

   It first read measured || authored || rule, on the reasoning that a
   millimetre beats an opinion. La Frite falsified that: the page is a pinout,
   nothing on it is to scale, and what an arrangement decides is which connector
   to read next and how much width each gets — a question about the drawing,
   which a coordinate does not answer. A coordinate answers where the copper is.
   So a direction moved above a measurement, and the measurement stayed in the
   file, cited, undrawn.

   The rule now sits above the measurement too, for the same reason plus one
   the La Frite case could not show. It is the owner's direction as well — the
   same person, generalised at their instruction from the boards they named —
   and it answers the same drawing question. What it adds is that it is
   answered UNIFORMLY: La Frite is measured and Das Frite is not, Le Potato is
   measured and Sweet Potato and Das Potato are not, and those pairs are the
   same product at different revisions. Under measured-first they would be drawn
   differently from each other — three columns for La Frite against a stacked
   two for Das Frite, one tall column for Le Potato against two for the others —
   with the difference tracking nothing about the product and everything about
   which board happened to have a CAD export we could read. A reader comparing
   revisions would read that as a change to the hardware.

   The cost is real and is stated rather than hidden: no board in the tree is
   drawn from its measurement today, because both measured boards carry a 40-pin
   header the rule covers. measuredGrid is the fallback for a board the rule
   does not reach — one with no 40-pin header, or whose other connectors do not
   fit beside it — and Renegade Elite is that shape but carries a direction of
   its own. The measurements are not deleted, edited or downgraded: they stay in
   the board files, they are what the note and its hover cite as not-drawn, and
   they are the reason the page can say the drawing departs from the board at
   all.

   Order of the three: a direction naming THIS board's connectors, then the
   owner's rule for boards of its shape, then the board's own millimetres. */
function boardGrid() {
  return authoredGrid() || ruleGrid() || measuredGrid();
}

/* Whether this board's arrangement is currently drawn. The class is the whole
   switch — `.board-cell { display: contents }` outside it hands the header
   blocks back to the packed layout — so giving up is one line. */
let boardViewWanted = false;

/* The board view is worth having only while it FITS. Its column count is the
   board's, not the window's, so unlike the packed layout it cannot reflow: on
   a narrow desktop the tracks are squeezed until the pad names ellipse, and a
   pad label cut in half is worse than a header drawn in the wrong order —
   the name is the thing the page exists to tell you. So the arrangement is
   drawn, measured, and dropped if it cost anything.
   (Measured on this board at 900x600: 40 of 40 labels on 7J1 ellipsed, which
   is what this rule now catches.) */
function fitBoardView() {
  if (!boardViewWanted) return;
  diagramEl.classList.add("board-view");
  const overflows = diagramEl.scrollWidth > diagramEl.clientWidth + 1;
  const clipped = overflows || Array.prototype.some.call(
    diagramEl.querySelectorAll(".pin-label"),
    (l) => l.scrollWidth > l.clientWidth + 1);
  diagramEl.classList.toggle("board-view", !clipped);
}

/* The note is where the kinds of arrangement are told apart, and it is not
   optional for any of them: a reader is entitled to assume a drawing that
   looks like a board WAS one, and "measured off the PCB", "how the person who
   makes it says to group these connectors" and "how this page draws any board
   shaped like this one" are three different promises. So the sentence differs,
   not just the hover — and the weakest of them does not call itself a board
   view at all, because it says nothing about the board.

   A drawing that DEPARTS from a measurement the board carries is the sentence
   that most needs writing, and either of the two undrawn-measurement cases can
   be in it — a direction for the board (La Frite, before the rule generalised)
   or the rule for its shape (La Frite and Le Potato now). A reader who is not
   told will read the departure as the board: that 2J2 sits above 9J5 when the
   DXF puts them 39 mm apart, or that Le Potato's three small connectors are to
   the right of 7J1 when the gerbers put all four in one column. So those
   sentences do not call themselves a board view, and they state the
   disagreement outright rather than leaving it to the hover — which carries
   the citation for the measurement that is not being drawn. */
const BOARD_NOTE = {
  measured: (g) =>
    `Board view — headers arranged by their measured position on the ` +
    `${g.board.w} × ${g.board.h} mm PCB. Arrangement, not scale.`,
  authored: (g) => (g.overrides
    ? "Grouped as the board's maker directs, NOT as measured — this board's " +
      "own CAD export places these connectors differently, and that " +
      "measurement is kept in its data. Not a position on the PCB."
    : "Board view — headers arranged as the board's maker specifies. " +
      "Not measured from the PCB."),
  rule: (g) => (g.overrides
    ? "Side by side as the board's maker asks for boards built around a " +
      "40-pin header, NOT as measured — this board's own CAD export places " +
      "these connectors differently, and that measurement is kept in its " +
      "data. Not a position on the PCB."
    : "Side by side — the 40-pin header, and every other connector on this " +
      "board stacked in the space beside it, the way the board's maker asks " +
      "for boards of this shape. Not a position on the PCB, and not a " +
      "direction about this board."),
};

function boardNote(grid) {
  const el = document.createElement("p");
  el.className = "board-note";
  el.textContent = BOARD_NOTE[grid.kind](grid);
  /* Same treatment as the electrical section's citation: the source belongs
     one hover away, not taking a second line on every board. */
  el.title = "Source: " + grid.source;
  return el;
}

/* ---- rendering ---- */

function render() {
  diagramEl.innerHTML = "";
  const grid = boardGrid();
  boardViewWanted = Boolean(grid);
  diagramEl.classList.toggle("board-view", boardViewWanted);
  diagramEl.style.gridTemplateColumns = grid ? `repeat(${grid.cols}, auto)` : "";

  /* The full-width rows come first and are placed explicitly, so the connector
     rows can start below them with no empty track in between — an empty grid
     row still costs a gap, which would open a hole in the middle of the board
     view for a banner that is not there. */
  let rowBase = 0;
  const entry = boardIndex.find((b) => b.id === board.id);
  const status = board.status || (entry && entry.status);
  if (STATUS_LABEL[status]) {
    const flag = document.createElement("div");
    flag.className = "board-flag";
    flag.textContent = `${board.model} is ${STATUS_LABEL[status]} — ` +
      "pinout may change before launch.";
    if (grid) flag.style.gridRow = String(++rowBase);
    diagramEl.appendChild(flag);
  }
  if (grid) {
    const note = boardNote(grid);
    note.style.gridRow = String(++rowBase);
    diagramEl.appendChild(note);
  }

  /* In board view the grid CELL is what gets positioned, not the header block:
     two connectors can share a cell (they overlap on both axes) and two grid
     items in one cell are drawn on top of each other. */
  const cells = new Map();
  const cellFor = (headerId) => {
    if (!grid) return diagramEl;
    const at = grid.at.get(headerId);
    const key = `${at.col}/${at.row}`;
    let cell = cells.get(key);
    if (!cell) {
      cell = document.createElement("div");
      cell.className = "board-cell";
      cell.style.gridColumn = at.span > 1
        ? `${at.col + 1} / span ${at.span}` : String(at.col + 1);
      cell.style.gridRow = String(at.row + 1 + rowBase);
      cells.set(key, cell);
      diagramEl.appendChild(cell);
    }
    return cell;
  };

  for (const header of board.headers) {
    const block = document.createElement("div");
    block.className = "header-block";
    const title = document.createElement("h2");
    /* Count header positions, not rows: a pin wired to two SoC lines has two
       rows but is still one pin on the connector. Same count the layout rule
       reads, so the title and the rule cannot disagree about "40-pin". */
    title.textContent = header.id + " · " + headerPositions(header) + " pins";
    block.appendChild(title);
    /* Geometry comes from the data, which takes it from the board's connector
       footprint. It is not inferrable from the pin count: Le Potato's 2J3 has
       8 pins in one row, and guessing "even count means two rails" drew it as
       a 2x4 that does not exist. */
    const highest = Math.max(...header.pins.map((p) => p.pin));
    block.appendChild(header.rows === 2
      ? renderDual(header, highest)
      : renderStrip(header));
    cellFor(header.id).appendChild(block);
  }
  renderLegend();
  fitBoardView();
  renderDetailPlaceholder();
  applySearch();
  applyFilter();
}

/* Physical layout: odd pins on the left rail, even pins on the right,
   pin numbers down the middle — the way the header sits on the board. */
function renderDual(header, highest) {
  const grid = document.createElement("div");
  grid.className = "pin-grid-dual";
  const body = document.createElement("div");
  body.className = "connector-body";
  grid.appendChild(body);

  const byPin = new Map();
  for (const p of header.pins) {
    if (!byPin.has(p.pin)) byPin.set(p.pin, []);
    byPin.get(p.pin).push(p);
  }

  /* One cell per header position; a position with two SoC lines stacks them. */
  const cell = (entries, side) => {
    if (!entries || !entries.length) return blankEl();
    if (entries.length === 1) return pinEl(entries[0], header, side);
    const stack = document.createElement("div");
    stack.className = "pin-stack side-" + side;
    for (const p of entries) stack.appendChild(pinEl(p, header, side));
    return stack;
  };

  for (let n = 1; n <= highest; n += 2) {
    const left = byPin.get(n);
    const right = byPin.get(n + 1);
    grid.appendChild(cell(left, "left"));
    grid.appendChild(left ? padEl(left[0], header, "left") : blankEl());
    grid.appendChild(right ? padEl(right[0], header, "right") : blankEl());
    grid.appendChild(cell(right, "right"));
  }
  return grid;
}

function renderStrip(header) {
  const grid = document.createElement("div");
  grid.className = "pin-grid-strip";
  for (const p of header.pins) {
    grid.appendChild(padEl(p, header, "left"));
    grid.appendChild(pinEl(p, header, "right"));
  }
  return grid;
}

function blankEl() {
  const el = document.createElement("span");
  el.className = "pin-blank";
  return el;
}

/* The numbered pad in the connector body. */
function padEl(p, header, side) {
  const el = document.createElement("span");
  el.className = "pin-pad side-" + side + (p.pin === 1 ? " first" : "");
  el.dataset.h = header.id;
  el.dataset.pin = p.pin;
  el.dataset.cls = primaryClass(p);
  if (isAnalog(p)) el.dataset.analog = "1";
  el.textContent = p.pin;
  return el;
}

/* The name rail either side of the connector: SoC name + mux square. */
function pinEl(p, header, side) {
  const el = document.createElement("div");
  el.className = "pin side-" + side;
  el.dataset.h = header.id;
  el.dataset.pin = p.pin;
  el.dataset.name = p.name;
  el.dataset.cls = primaryClass(p);
  if (isAnalog(p)) el.dataset.analog = "1";
  const label = document.createElement("span");
  label.className = "pin-label";
  label.textContent = focusedFunc(p) || p.name;
  if (focusedFunc(p)) el.classList.add("relabelled");
  const square = muxSquare(p, side);
  if (side === "left") el.append(label, square);
  else el.append(square, label);
  return el;
}

/* Half a square, split across the pin's axis: the half facing the connector
   is the board's own colour for that pin, the far half is one strip per OTHER
   mux the pad can be switched to -- the near half already stands for the
   primary, so repeating it there would spend width saying the same thing.
   `side` is which rail the tile sits on, so the primary half always ends up
   nearest the numbered pad. */
function muxSquare(p, side) {
  const box = document.createElement("span");
  box.className = "mux-square near-" + (side === "left" ? "right" : "left");
  const primary = primaryClass(p);
  const classes = muxClasses(p).filter((c) => c !== primary);

  const alts = document.createElement("span");
  alts.className = "mux-alts";
  alts.dataset.n = classes.length;
  for (const c of classes) {
    const strip = document.createElement("span");
    strip.className = "mux-strip";
    strip.dataset.cls = c;
    strip.style.background = (CLASS_INFO[c] || CLASS_INFO.misc).color;
    alts.appendChild(strip);
  }

  const near = document.createElement("span");
  near.className = "mux-primary";
  near.dataset.cls = primary;
  near.style.background = (CLASS_INFO[primary] || CLASS_INFO.gpio).color;

  /* Nothing left to show beside the primary (power, ground, a pad whose only
     function is GPIO) -- one solid colour. */
  if (!classes.length) box.classList.add("solid");
  /* GPIO is not a primary the way I2C or SPI is -- it is what every one of
     these pads already does, so spending half the tile on it says nothing
     while halving the room the alternates get to say something. A pad whose
     ONLY function is GPIO keeps its solid green: there the colour IS the
     answer. */
  if (primary === "gpio" && classes.length) {
    box.classList.add("alts-only");
    box.append(alts);
    return box;
  }
  box.append(alts, near);
  return box;
}

function renderLegend() {
  legendEl.innerHTML = "";
  const present = new Set();
  for (const h of board.headers)
    for (const p of h.pins)
      for (const c of muxClasses(p)) present.add(c);
  for (const [cls, info] of Object.entries(CLASS_INFO)) {
    if (!present.has(cls)) continue;
    const item = document.createElement("div");
    item.className = "legend-item" + (classFilter === cls ? " active" : "");
    item.dataset.cls = cls;
    item.title = "Show only pins that can mux to " + info.label;
    const sw = document.createElement("span");
    sw.className = "legend-swatch";
    sw.style.background = info.color;
    const text = document.createElement("span");
    /* The row is one line of equal columns, so the visible text is the
       short form where one exists; the full name stays in the title, so
       nothing is lost -- PDM / DMIC is still one hover away. */
    text.textContent = info.short || info.label;
    item.append(sw, text);
    legendEl.appendChild(item);
  }
}

function renderDetailPlaceholder() {
  /* Nothing is selected, so the pane is back to being a pane: on a narrow
     screen `pin-open` is what lifts it into a sheet over the drawing. Cleared
     here rather than at each call site, because every route back to the
     placeholder -- deselect, Close, a board switch, a legend re-render --
     comes through this function. */
  document.body.classList.remove("pin-open");
  detailEl.innerHTML =
    '<p class="muted">The half of each square facing the connector is the ' +
    "board's colour for that pin (yellow I2C, blue SPI, green GPIO); the far " +
    "half carries one strip per other mux the pad can reach. Hover a pin " +
    "for its mux list, select it for the full pinmux, or select a legend " +
    "entry to filter.</p>";
}

function closeDetail() {
  diagramEl.querySelectorAll(".selected").forEach((n) => n.classList.remove("selected"));
  renderDetailPlaceholder();
}

/* ---- pin lookup + events ---- */

function findPin(headerId, pinNum) {
  const header = board.headers.find((h) => h.id === headerId);
  if (!header) return null;
  const pin = header.pins.find((p) => p.pin === Number(pinNum));
  return pin ? { header, pin } : null;
}

function pinCells(headerId, pinNum) {
  return diagramEl.querySelectorAll(
    `[data-h="${CSS.escape(headerId)}"][data-pin="${CSS.escape(String(pinNum))}"]`);
}

function onPinOver(e) {
  /* A tap raises the pointer's over event and then never a matching out, so on
     touch this tooltip would open on the first pin and stay there, parked over
     the sheet the same tap just raised. Nothing is lost by dropping it: the
     tooltip's facts -- the pad name, the mux list and the groups -- are all in
     the detail pane the tap opens.

     Keyed on the pointer that raised the event, not on a media query: a
     desktop seat with no mouse attached matches `(hover: none)` too (measured
     on this project's own Wayland test seat, maxTouchPoints 0), and it would
     have lost the tooltip for a machine that can hover perfectly well. Pen is
     left alone -- it hovers. */
  if (e.pointerType === "touch") return;
  const el = e.target.closest("[data-pin]");
  if (!el) return;
  const found = findPin(el.dataset.h, el.dataset.pin);
  if (!found) return;
  const { header, pin } = found;
  highlightClass(el.dataset.cls);
  pinCells(header.id, pin.pin).forEach((n) => n.classList.add("hover"));
  const muxes = muxClasses(pin)
    .map((c) => (CLASS_INFO[c] || CLASS_INFO.misc).label).join(" · ");
  tooltipEl.textContent =
    `${header.id} pin ${pin.pin} · ${pin.name}` +
    (isAnalog(pin) ? "\nanalog pad — not a digital GPIO" : "") +
    (pin.type === "gpio"
      ? `\nmux: ${pin.funcs.join(" / ")}\ngroups: ${muxes}`
      : "");
  tooltipEl.hidden = false;
  const r = el.getBoundingClientRect();
  const below = r.bottom + 6;
  tooltipEl.style.left =
    Math.min(Math.max(8, r.left), innerWidth - tooltipEl.offsetWidth - 8) + "px";
  tooltipEl.style.top =
    (below + tooltipEl.offsetHeight > innerHeight ? r.top - tooltipEl.offsetHeight - 6 : below) + "px";
}

function onPinOut(e) {
  if (!e.target.closest("[data-pin]")) return;
  clearHighlight();
  tooltipEl.hidden = true;
}

function onPinClick(e) {
  const el = e.target.closest("[data-pin]");
  if (!el) return;
  const found = findPin(el.dataset.h, el.dataset.pin);
  if (!found) return;
  /* Clicking the selected pin again closes the pane. Selecting is how you open
     it, so the same gesture is how you put it away -- otherwise the only route
     back to the placeholder is a reload.

     Asked of the DOM rather than of a remembered pin: a legend filter or a
     board switch re-renders the diagram and drops .selected, and a variable
     that outlived that would make the next click on that pin CLOSE a pane
     that was never open. */
  const wasSelected = el.classList.contains("selected");
  diagramEl.querySelectorAll(".selected").forEach((n) => n.classList.remove("selected"));
  if (wasSelected) {
    renderDetailPlaceholder();
    return;
  }
  pinCells(found.header.id, found.pin.pin).forEach((n) => n.classList.add("selected"));
  renderDetail(found.header, found.pin);
  /* The sheet takes the bottom of the screen, so a pin tapped down there ends
     up underneath it. scroll-margin-bottom in the stylesheet is what the
     "nearest" edge is measured against, so this lifts the pin clear of the
     sheet and leaves a pin already above it alone. */
  if (document.body.classList.contains("pin-open"))
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function onLegendClick(e) {
  const item = e.target.closest(".legend-item");
  if (!item) return;
  classFilter = classFilter === item.dataset.cls ? null : item.dataset.cls;
  labelFocus = classFilter ? { cls: classFilter } : null;
  for (const el of legendEl.querySelectorAll(".legend-item"))
    el.classList.toggle("active", el.dataset.cls === classFilter);
  applyFilter();
  applyLabels();
}

/* Click a function in the detail panel to see where else that exact mux
   lands -- pin 3 says I2C_SDA_AO, not GPIOAO_5. */
function onDetailClick(e) {
  const chip = e.target.closest(".func-chip");
  if (!chip) return;
  const func = chip.dataset.func;
  labelFocus = labelFocus && labelFocus.func === func ? null : { func };
  detailEl.querySelectorAll(".func-chip").forEach((c) =>
    c.classList.toggle("focused", labelFocus && c.dataset.func === func));
  applyLabels();
}

/* The mux name this pin takes under the current focus, or null. */
function focusedFunc(pin) {
  if (!labelFocus || pin.type !== "gpio") return null;
  if (labelFocus.func) {
    return pin.funcs.find((f) => f === labelFocus.func) || null;
  }
  return pin.funcs.find((f) => funcClass(f) === labelFocus.cls) || null;
}

function applyLabels() {
  for (const el of diagramEl.querySelectorAll(".pin")) {
    const found = findPin(el.dataset.h, el.dataset.pin);
    if (!found) continue;
    /* A pin number with two SoC lines has two tiles; label each from its own
       row, matched by the pad name the tile was built with. */
    const rows = board.headers
      .find((h) => h.id === el.dataset.h).pins
      .filter((p) => p.pin === found.pin.pin);
    const pin = rows.find((p) => p.name === el.dataset.name) || found.pin;
    const label = el.querySelector(".pin-label");
    const func = focusedFunc(pin);
    label.textContent = func || pin.name;
    el.classList.toggle("relabelled", Boolean(func));
  }
}

function highlightClass(cls) {
  /* Plain GPIO is most of the header -- lighting all of it says nothing. */
  if (!cls || cls === "gpio") return;
  diagramEl.querySelectorAll(`[data-cls="${CSS.escape(cls)}"]`)
    .forEach((n) => n.classList.add("hl"));
}

function clearHighlight() {
  diagramEl.querySelectorAll(".hl, .hover")
    .forEach((n) => n.classList.remove("hl", "hover"));
}

/* ---- detail panel ---- */

function renderDetail(header, p) {
  const info = CLASS_INFO[primaryClass(p)] || CLASS_INFO.gpio;
  const rows = [];
  rows.push(["SoC function", p.name]);
  /* Which buses the pad can reach, spelled out. It is the one thing the
     tooltip said that nothing else did, and the tooltip needs a cursor --
     on a phone the colours in the mux chips were the only trace of it. */
  if (p.type === "gpio") {
    rows.push(["Groups", muxClasses(p)
      .map((c) => (CLASS_INFO[c] || CLASS_INFO.misc).label).join(" · ")]);
  }
  if (p.chip !== null) {
    rows.push(["GPIO (libgpiod)", `gpiochip${p.chip} line ${p.line}`]);
    if (p.sysfs !== null) rows.push(["Legacy sysfs", `/sys/class/gpio/gpio${p.sysfs}`]);
  }
  /* A position the board ties to two SoC balls carries the second here. Both
     have to be configured to use the pin, so both get a row rather than the
     pane implying the first one is the whole story. */
  for (const a of p.also || []) {
    rows.push([`GPIO (${esc(a.name)})`, `gpiochip${a.chip} line ${a.line}`]);
    if (a.sysfs !== undefined && a.sysfs !== null)
      rows.push([`Legacy sysfs (${esc(a.name)})`, `/sys/class/gpio/gpio${a.sysfs}`]);
  }
  rows.push(["SoC pad (BGA)", p.pad]);

  let html = `<h3><span class="cls-badge" style="background:${info.color}"></span>` +
    `${esc(header.id)} pin ${p.pin} <span class="muted" style="font-size:13px;font-weight:400">${esc(info.label)}</span></h3>`;
  html += "<table>";
  /* What the pin can BE comes before what it currently IS. The mux chips are
     the reason to open this pane -- and they are the clickable control that
     relabels the header -- so burying them under four rows of identifiers put
     the answer below the question. */
  /* A position with no functions at all -- an NC pad, whose Desc is the map's
     "-" -- gets no Muxes row rather than an empty one. An empty control reads
     as "we failed to load them"; no row reads as "there are none", which is
     the true statement about a pad wired to nothing. */
  if (p.funcs.length) html += `<tr><th>Muxes</th><td><div class="func-chips">` +
    p.funcs.map((f) => {
      const c = funcClass(f);
      const color = (CLASS_INFO[c] || CLASS_INFO.misc).color;
      const focused = labelFocus && labelFocus.func === f ? " focused" : "";
      return `<span class="func-chip${f === p.ref ? " ref" : ""}${focused}" ` +
        `data-func="${esc(f)}" title="Label the header with this mux">` +
        `<span class="chip-dot" style="background:${color}"></span>${esc(f)}</span>`;
    }).join("") +
    `</div></td></tr>`;
  for (const [k, v] of rows) html += `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  html += "</table>";

  if (Array.isArray(p.muxes) && p.muxes.length) {
    /* On a position the board ties to two SoC balls, which ball a function
       belongs to is the one thing the table cannot be read without: the seven
       here split across two lines, and [2:0] vs [5:3] only says so to someone
       who already knows. The column appears only on those pins -- everywhere
       else it would repeat the pin's own name on every row. */
    const tied = p.muxes.some((m) => m.owner);
    html += '<table class="mux-table"><tr><th>Function</th>' +
      (tied ? "<th>Line</th>" : "") + "<th>Group</th>" +
      "<th>Register</th><th>Field</th><th>Write</th></tr>";
    for (const m of p.muxes) {
      /* Bit field as the datasheet writes it: high:low, not bit:width. */
      const lo = m.bit;
      const hi = lo + (m.width || 1) - 1;
      const field = hi === lo ? `[${lo}]` : `[${hi}:${lo}]`;
      html += `<tr><td>${esc(m.name)}</td>` +
        (tied ? `<td>${esc(m.owner || "")}</td>` : "") +
        `<td>${esc(m.group)}</td>` +
        `<td>${esc(m.reg)}</td><td>${esc(field)}</td>` +
        `<td>${m.value !== undefined ? esc(m.value) : "—"}</td></tr>`;
    }
    html += "</table>";
  }

  /* Commands before characteristics. Someone opening a pin wants to drive it;
     the reset state, drive strength and VCCIO domain are what they check when
     it does not behave, or before wiring something that cares. Putting the
     electrical table first pushed the two lines people actually copy below a
     table they mostly scroll past. */
  if (p.chip !== null) {
    html += `<pre class="usage"># inspect
gpioinfo gpiochip${p.chip}

# drive as output (libgpiod)
gpioset gpiochip${p.chip} ${p.line}=1</pre>`;
  }
  html += renderElectrical(p);
  detailEl.innerHTML = html;
  document.body.classList.add("pin-open");
}

/* ---- electrical ----

   Everything here is transcribed from the datasheet extract in the board file.
   Nothing is computed: "3.3x0.3" stays the expression the datasheet printed
   (only the times sign is prettified), "NA" becomes an em dash, and a field the
   extract does not carry renders as an em dash rather than as a default. A
   number nobody published is a number nobody can check. */

const RESET_STATE = { I: "input", O: "output", Z: "high-Z", "I/O": "bidirectional" };
const DIRECTION = { "I/O": "bidirectional (I/O)", I: "input", O: "output" };

/* Datasheet symbol -> the plain-English name the datasheet gives it. */
const DC_ROWS = [
  ["vil", "Vil — input low"],
  ["vih", "Vih — input high"],
  ["vol", "Vol — output low"],
  ["voh", "Voh — output high"],
  ["Vtr_pos", "Vtr+ — threshold, rising"],
  ["Vtr_neg", "Vtr− — threshold, falling"],
  ["rpu", "Rpu — pull-up"],
  ["rpd", "Rpd — pull-down"],
];

function elecCell(v) {
  if (v === undefined || v === null || v === "" || /^(NA|N\/A|TBD)$/i.test(String(v)))
    return "—";
  return esc(String(v).replace(/(\d)\s*x\s*(\d)/gi, "$1×$2"));
}

/* min/typ/max for one supply of a rail. A fixed rail carries them directly; a
   selectable rail carries one set per selectable voltage. */
function railRange(rail, supply) {
  if (!rail) return null;
  if (rail[supply] && typeof rail[supply] === "object") return rail[supply];
  return rail.min !== undefined ? rail : null;
}

function renderElectrical(p) {
  const e = p.elec;
  const spec = board.electrical;
  /* Power and ground rows are the header's own rails, not SoC pads -- the pad
     table has nothing to say about them. */
  if (!e && p.type !== "gpio") return "";
  if (!e && !spec) {
    return '<p class="muted elec-none">No per-pad electrical data published ' +
      "for this SoC yet.</p>";
  }

  let html = '<h4 class="elec-head">Electrical</h4>';

  if (e && e.pad_type === "analog") {
    html += `<p class="muted elec-analog">${esc(e.note)}</p>`;
    return html;
  }

  const rows = [];
  if (e && e.pad_type && spec && spec.pad_types && spec.pad_types[e.pad_type]) {
    const t = spec.pad_types[e.pad_type];
    rows.push(["IO type", `Type ${e.pad_type} — ${t.desc}`]);
  }
  if (e && e.direction) rows.push(["Direction", DIRECTION[e.direction] || e.direction]);
  if (e && (e.io_reset || e.pupd_reset)) {
    const st = e.io_reset ? (RESET_STATE[e.io_reset] || e.io_reset) : null;
    rows.push(["At reset",
      [st, e.pupd_reset].filter(Boolean).join(", ")]);
  }
  if (e && e.pull_capability) {
    /* sunxi publishes what the pad CAN be pulled to, which is not the same
       claim as what it is pulled to at reset -- keep them apart. */
    rows.push(["Pull available", e.pull_capability]);
  }
  if (e && e.drive) rows.push(["Drive strength", e.drive]);
  if (e && e.open_drain) {
    rows.push(["Output stage", "open-drain — needs an external pull-up"]);
  }
  if (e && e.tolerant_5v) rows.push(["5 V tolerant", "yes"]);
  if (e && e.interrupt !== undefined) rows.push(["Interrupt capable", e.interrupt ? "yes" : "no"]);

  const domain = e && e.domain;
  const rail = domain && spec && spec.rails ? spec.rails[domain] : null;
  const supplies = rail && Array.isArray(rail.select) ? rail.select : [];
  /* The SoC datasheet says a rail MAY be 3.3 or 1.8; only the schematic says
     which this board feeds it. Where that is recorded, say so -- "selectable"
     is the honest answer for the part and a useless one for the board in
     front of you. */
  const onBoard = (spec && spec.board_rails && domain)
    ? spec.board_rails[domain] : null;
  if (domain) {
    let text = domain.toUpperCase();
    if (onBoard) {
      text += ` — ${onBoard} V on this board` +
        (supplies.length > 1 ? ` (${supplies.join(" V / ")} V selectable)` : "");
    } else if (supplies.length > 1) {
      text += ` — ${supplies.join(" V or ")} V selectable`;
    } else if (supplies.length === 1 && /^[\d.]+$/.test(supplies[0])) {
      text += ` — ${supplies[0]} V`;
    }
    /* A named rail (sunxi VCC-PC) is its own label; restating it as
       "VCC-PC — VCC-PC V" says nothing and reads like a bug. */
    rows.push(["Power domain", text]);
  } else if (spec) {
    /* Not "not in the datasheet's pad table" -- that names the wrong book.
       RK3328's rails come from the TRM's interface tables, not from the
       datasheet's Table 2-3, which has no domain column at all; the pads left
       blank are the ones no vendor document states a rail for. */
    rows.push(["Power domain",
      "— (no rail stated for this pad in the vendor documentation)"]);
  }

  if (!rows.length) {
    return '<h4 class="elec-head">Electrical</h4><p class="muted">No pad ' +
      "characteristics published for this pin.</p>";
  }

  html += "<table>";
  for (const [k, v] of rows) html += `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`;
  html += "</table>";

  /* Thresholds follow the pad's supply, so they are only shown when the pad's
     rail is known. A selectable rail gets both tables, side by side, and says
     so -- which one applies is a board-strapping fact this data does not
     carry, and picking one would be a guess. */
  /* Amlogic states a different threshold set per pad-cell family (a plain DIO
     and an open-drain pad on the same rail do not share numbers), so its dc
     table is keyed by family first. Vendors with one set per supply keep the
     flat shape. */
  const dcTable = (spec && spec.dc && e && e.dc_family && spec.dc[e.dc_family])
    ? spec.dc[e.dc_family]
    : (spec && spec.dc) || null;

  if (rail && supplies.length && dcTable) {
    if (supplies.length > 1 && onBoard) {
      html += '<p class="muted elec-note">' +
        `${esc(domain.toUpperCase())} is supply-selectable; this board feeds ` +
        `it <strong>${esc(onBoard)} V</strong>, so that is the row that ` +
        "applies. The other is kept for the pad, not for this board.</p>";
    } else if (supplies.length > 1) {
      html += '<p class="muted elec-note">' +
        `${esc(domain.toUpperCase())} is supply-selectable: both ` +
        "operating points are shown, and which one applies depends on what the " +
        "board feeds that rail.</p>";
    }
    for (const supply of supplies) {
      const dc = dcTable[supply];
      if (!dc) continue;
      const active = onBoard !== null && onBoard === supply;
      const range = railRange(rail, supply);
      /* A supply is either a voltage (RK3328: "3.3") or a rail name (sunxi:
         "VCC-PC", because its thresholds are fractions of whatever that rail
         carries). Only the former takes a "V". */
      const supplyLabel = /^[\d.]+$/.test(supply) ? `${supply} V` : supply;
      html += `<table class="dc-table${active ? " dc-active" : ""}` +
        `${onBoard !== null && !active ? " dc-inactive" : ""}">` +
        `<tr><th colspan="5">${esc(supplyLabel)}` +
        (active ? " — on this board" : "") + " — " +
        (range
          ? `rail ${elecCell(range.min)} / ${elecCell(range.typ)} / ${elecCell(range.max)} V`
          : "rail range not published") +
        "</th></tr><tr><th>Parameter</th><th>Min</th><th>Typ</th><th>Max</th>" +
        "<th>Unit</th></tr>";
      for (const [sym, label] of DC_ROWS) {
        const v = dc[sym];
        if (!v) continue;
        const unit = (spec.units && spec.units[sym]) || "";
        html += `<tr><td class="dc-sym">${esc(label)}</td>` +
          `<td>${elecCell(v.min)}</td><td>${elecCell(v.typ)}</td>` +
          `<td>${elecCell(v.max)}</td><td>${esc(unit)}</td></tr>`;
      }
      html += "</table>";
    }
    if (spec.dc_note) {
      html += `<p class="muted elec-note">${esc(spec.dc_note)}</p>`;
    }
  } else if (dcTable && Object.keys(dcTable).length) {
    html += '<p class="muted elec-note">Without the pad\'s VCCIO rail the ' +
      "input thresholds cannot be resolved, so none are shown.</p>";
    /* Say WHY the rail is unknown where the SoC's extract explains it --
       RK3399 publishes the thresholds but no pad-to-domain binding at all,
       which is a different situation from a pad the domain table happened to
       miss, and the reader should not have to guess which one they hit. */
    if (spec.dc_note)
      html += `<p class="muted elec-note">${esc(spec.dc_note)}</p>`;
  } else if (spec && spec.dc_note) {
    /* Say the thresholds are missing from the source, so nobody assumes
       another SoC's numbers carry over. */
    html += `<p class="muted elec-note">${esc(spec.dc_note)}</p>`;
  }

  /* The citation moves onto the heading rather than out of the page. Every
     figure above is transcribed from a named datasheet table and a reader has
     to be able to find out which -- but that belongs behind a hover, not
     taking a line at the bottom of every pin. */
  const src = [spec && spec.pad_source, spec && spec.source].filter(Boolean);
  if (src.length)
    html = html.replace('<h4 class="elec-head">Electrical</h4>',
      `<h4 class="elec-head" title="Source: ${esc(src.join(" · "))}">` +
      "Electrical</h4>");
  return html;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---- search + legend filter ---- */

function applySearch() {
  const q = searchEl.value.trim().toLowerCase();
  for (const el of diagramEl.querySelectorAll("[data-pin]")) {
    if (!q) {
      el.classList.remove("nomatch", "match");
      continue;
    }
    const found = findPin(el.dataset.h, el.dataset.pin);
    if (!found) continue;
    const { pin } = found;
    const hay = [pin.name, pin.ref, pin.pad, pin.type, pin.cls,
      "pin " + pin.pin, String(pin.pin), ...pin.funcs].join(" ").toLowerCase();
    el.classList.toggle("match", hay.includes(q));
    el.classList.toggle("nomatch", !hay.includes(q));
  }
  applyDim();
}

function applyFilter() {
  for (const el of diagramEl.querySelectorAll("[data-pin]")) {
    if (!classFilter) {
      el.classList.remove("nofilter");
      continue;
    }
    const found = findPin(el.dataset.h, el.dataset.pin);
    if (!found) continue;
    el.classList.toggle("nofilter", !muxClasses(found.pin).includes(classFilter));
  }
  applyDim();
}

function applyDim() {
  for (const el of diagramEl.querySelectorAll("[data-pin]"))
    el.classList.toggle("dim",
      el.classList.contains("nomatch") || el.classList.contains("nofilter"));
}

init();
