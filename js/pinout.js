/* What a board's pins ARE, as data and as plain HTML -- shared by the
   interactive view (js/app.js) and the static pages (tools/render.mjs).

   Pure on purpose: no DOM, no `location`, nothing run at import. Node imports
   it to write each board's page, the browser imports it to draw the same
   section when the board changes in place, so the text a crawler reads and the
   text a visitor reads come from one function (boardPageHtml). */

/* Function classes. The colour of each is the --c-<key> token in
   css/style.css, read through classColor() in js/app.js. */
export const CLASS_INFO = {
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
  poe:      { label: "PoE (hazardous)",    short: "PoE" },
  power12v: { label: "12V power",          short: "12V" },
  power5v:  { label: "5V power",           short: "5V" },
  power3v3: { label: "3.3V power",         short: "3.3V" },
  powerlv:  { label: "Low-voltage rail",   short: "Rail" },
  gnd:      { label: "Ground",             short: "GND" },
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
  nc:       { label: "Not connected",      short: "NC" },
  gpio:     { label: "GPIO" },
  i2c:      { label: "I2C" },
  spi:      { label: "SPI" },
  uart:     { label: "UART / serial",      short: "UART" },
  pwm:      { label: "PWM" },
  /* One class per audio bus. They are not variants of each other: I2S, PCM
     and TDM are separate controllers with separate pin groups, and a codec
     wired for one will not work on another. Colours are spaced in CIE Lab
     (worst in-family pair 15.1, nearest non-audio class 18.5) because several
     of them can land on the same pin's strip set. */
  i2s:      { label: "I2S" },
  pcm:      { label: "PCM" },
  tdm:      { label: "TDM" },
  spdif:    { label: "S/PDIF",             short: "SPDIF" },
  pdm:      { label: "PDM / DMIC",         short: "PDM" },
  /* Both directions: La Frite's line-out and the meson AL_CH/AR_CH muxes, and
     Renegade Elite's codec header, which brings out HPO_L/R alongside MIC_IN
     and LINE_IN. Labelling that header "analog audio out" would be a mislabel
     in the same class as painting it green. */
  dac:      { label: "Analog audio",       short: "Audio" },
  adc:      { label: "ADC" },
  clk:      { label: "Clock" },
  jtag:     { label: "JTAG" },
  cec:      { label: "CEC" },
  ir:       { label: "IR / remote",        short: "IR" },
  sdio:     { label: "SDIO / SD card",     short: "SDIO" },
  nand:     { label: "NAND / flash",       short: "NAND" },
  video:    { label: "TS / camera / video", short: "Video" },
  pcie:     { label: "PCI Express",        short: "PCIe" },
  usb:      { label: "USB" },
  eth:      { label: "Ethernet",           short: "ETH" },
  misc:     { label: "Other / control",    short: "Other" },
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

/* Pre-production and unreleased boards ship in the data but stay out of the
   picker until ?hidden=1 asks for them. */
export const STATUS_LABEL = { preprod: "pre-production", unreleased: "unreleased",
                              preliminary: "preliminary pinout",
                              reference: "another maker's board, shown for comparison" };

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---- function classification ---- */

export function funcClass(name) {
  for (const [re, cls] of FUNC_RULES) if (re.test(name)) return cls;
  return "misc";
}

/* Every mux this pin can be switched to, as an ordered, de-duplicated class
   list. GPIO is mux 0 on every muxable pad, so it leads. */
export function muxClasses(p) {
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
export function primaryClass(p) {
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
export function isAnalog(p) {
  return Boolean(p.elec && p.elec.pad_type === "analog");
}

/* The connector the direction (and the page) is about, in positions — the same
   count HEADER_FIRST_POSITIONS orders by in the generator and the header title
   shows, so "40P header" means the same thing in all three. */
export const MAIN_HEADER_POSITIONS = 40;

/* What a connector costs the drawing vertically, in pin rows — the unit the
   diagram is actually built out of. A dual-row header draws two pads per row,
   which is the whole reason a 40-pin connector is the SHORT way round and has
   room beside it. Positions, not map rows: a pin wired to two SoC lines is two
   rows in the data and one pad on the connector. */
export function headerPositions(h) {
  return new Set(h.pins.map((p) => p.pin)).size;
}

/* The banner a board with a status carries, or null: the same sentence above
   the drawing and in the pin table. */
export function statusNote(board, status) {
  if (!STATUS_LABEL[status]) return null;
  return status === "preliminary"
    ? `${board.model}: this pinout is preliminary and not final.`
    : `${board.model} is ${STATUS_LABEL[status]} — ` +
      (status === "reference"
        ? "transcribed from its maker's datasheet, not a Libre Computer product."
        : "pinout may change before launch.");
}

/* ---- the pin table: a board's pins as plain HTML ----

   Every header, every pin: its number, the SoC name, the board's own signal
   name where it differs, the class the board gives it, the mux functions the
   data lists, and its gpiochip line. Only fields data/<id>.json carries. */

export function boardTitle(board) {
  return `${board.name} (${board.model}) GPIO Pinout — Libre Computer`;
}

export function boardDescription(board) {
  return `GPIO pinout and pinmux for the Libre Computer ${board.name} ` +
    `(${board.model}, ${board.vendor} ${board.soc}): every header pin's name, ` +
    "type, alternate functions and GPIO line.";
}

function pinRow(p) {
  const cls = primaryClass(p);
  const type = (CLASS_INFO[cls] || CLASS_INFO.misc).label + (isAnalog(p) ? " (analog pad)" : "");
  const funcs = p.type === "gpio" ? p.funcs.map(esc).join(", ") : "";
  const gpio = p.chip !== null && p.chip !== undefined ? `gpiochip${esc(p.chip)} line ${esc(p.line)}` : "";
  return `<tr><th scope="row">${esc(p.pin)}</th><td>${esc(p.name)}</td>` +
    `<td>${p.ref && p.ref !== p.name ? esc(p.ref) : ""}</td><td>${esc(type)}</td>` +
    `<td>${funcs}</td><td>${gpio}</td></tr>`;
}

function headerTable(h) {
  return `<div class="lc-table-scroll"><table class="lc-table pin-table">` +
    `<caption>${esc(h.id)} · ${headerPositions(h)} pins</caption>` +
    `<thead><tr><th scope="col">Pin</th><th scope="col">Name</th>` +
    `<th scope="col">Board signal</th><th scope="col">Type</th>` +
    `<th scope="col">Functions</th><th scope="col">GPIO</th></tr></thead>` +
    `<tbody>${h.pins.map(pinRow).join("")}</tbody></table></div>`;
}

/** The inside of section#pin-table for one board (data/<id>.json). */
export function boardPageHtml(board) {
  const note = statusNote(board, board.status);
  return `<h2 id="pin-table-title">${esc(board.name)} (${esc(board.model)}) pin table</h2>` +
    `<p>${esc(board.vendor)} ${esc(board.soc)} · ${board.headers.length} ` +
    `header${board.headers.length === 1 ? "" : "s"}: ` +
    `${board.headers.map((h) => `${esc(h.id)} (${headerPositions(h)} pins)`).join(", ")}.</p>` +
    (note ? `<p class="board-flag">${esc(note)}</p>` : "") +
    board.headers.map(headerTable).join("");
}

/** The inside of section#pin-table on the home page: every listed board,
 *  linked to its page (boards: data/boards.json entries, hidden ones out). */
export function boardListHtml(boards, lede = "") {
  return `<h2 id="pin-table-title">Boards</h2>${lede ? `<p class="board-list-lede">${esc(lede)}</p>` : ""}<ul class="board-list">` +
    boards.map((b) => `<li><a href="/${esc(b.id)}/">${esc(b.name)} (${esc(b.model)})</a> · ` +
      `${esc(b.vendor)} ${esc(b.soc)}, ${esc(b.npins)} pins</li>`).join("") +
    `</ul>`;
}
