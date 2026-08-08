# Libre Computer GPIO Pinout

Interactive GPIO / pinmux reference for Libre Computer boards, served at
[gpio.hardware.libre.computer](https://gpio.hardware.libre.computer) via
GitHub Pages. Inspired by [pinout.xyz](https://pinout.xyz).

Pick a board from the dropdown. Each header is drawn the way it sits on the
board — pin numbers down the middle, odd pins on the left rail, even on the
right — the 40-pin header first. Where the board's own CAD data says where its
connectors are, the headers are arranged on the page the way the PCB arranges
them; where it does not but the board's maker has said how they should read,
that arrangement is drawn and labelled as the weaker claim it is (see [Board
layout](#board-layout)). Every pin carries a square split across the middle: the top band is the
board's own colour for that pin (yellow I2C, blue SPI, orange 3.3V, red 5V,
deeper red 12V), and below it sits one vertical stripe per *other* mux the pad
can reach. Supply rails ramp by voltage — the higher the rail, the deeper the
red — so a supply never reads as less alarming than a lower one, and never as
the green that means "muxable pad". A pin
whose only role is GPIO has no band — green would say what every pad on the
header already is, and the stripes get the whole tile instead.

Select a pin for the full pinmux (SoC function, libgpiod chip/line, legacy
sysfs number, BGA pad, alternate functions with the register write that
chooses each one, then the pad's electrical characteristics); select it again
to close. Select a legend class to show only pins that can mux to it, or
search across names, functions, pads and pin numbers. On a pointer device,
hovering a pin also gives its mux list without opening anything.

**Select to relabel.** A legend class, or a function chip in a pin's detail
panel, rewrites the header labels with that mux name: the rails read
`TDMB_SCLK` / `TDMB_FS` instead of `GPIOAO_8` / `GPIOAO_7`, which is how you
see where a bus actually lands (and that a signal reaches more than one pad).
Select it again to clear; the pad name stays in the tooltip throughout.

## Data

Pin data is generated at build time from
[libretech-wiring-tool](https://github.com/libre-computer-project/libretech-wiring-tool)
`libre-computer/<board>/gpio.map` files (MIT) and committed as JSON under
`data/`, so the site is fully static.

| File | Content |
|---|---|
| `data/boards.json` | Board index (id, model, name, SoC, vendor, status, hidden) |
| `data/<board>.json` | Per-board headers and pins with function classes, pinmux registers, and (where published) per-pad electricals + the board's rail/DC tables, plus the connectors' physical placement (`layout`) where the board's CAD data gives it, or the maker's own grouping (`arrangement`) where it does not |

### Board layout

**The 40-pin header comes first on every board that has one.** It is the
connector the page exists for, and on all thirteen boards that carry one the
wiring map happens to list it first anyway — which made the right answer depend
on a file we do not own. `order_headers()` in the generator states it as a rule
instead, so a map that ever reorders its stanzas cannot quietly demote it. It
counts pin *positions*, not map rows: a pin wired to two SoC lines is two rows
and still one position on the connector.

Where a board's own CAD export says where its connectors sit, the board file
carries a `layout` block — the board outline's size and each header's pad
bounding box, in millimetres, origin at the outline's minimum corner and +y up
(the CAD frame; the drawing flips it). On a wide screen the headers are then
arranged the way the PCB arranges them — a connector near the top-left edge is
drawn near the top-left — instead of packed into columns in map order, which
told the reader nothing.

**Which edge is up is not in the CAD.** A layout export fixes every connector
relative to every other and says nothing about how the reader is holding the
board, so 0° and 180° are both faithful readings of the same millimetres. That
choice therefore travels as its own field, `layout.orient`, with its own
`layout.orient_source` — never folded into the `source` that cites the CAD
file. Le Potato is the one board that needs it: 7J1 sits along the y-minimum
edge of the design frame, so read +y-up it lands at the bottom of the drawing
and the three small connectors come first. `orient: 180` turns the board
end-for-end, which is where the measurements alone leave the question. Nothing
measured moves — and on that board all four connectors share one column
(their x spans all overlap 7J1's 26.454–76.446 mm), so the rotation is only
observable in the vertical order and cannot swap a left for a right.

The arrangement is *ordinal, not to scale*, and the page says so. A 2.54 mm
connector needs two rails of pad names, which is a few hundred pixels, so
drawing the headers at their true relative sizes would make either the names or
the board unreadable. What the millimetres decide is which header is left of
which and which is above which: columns and rows come from the connectors' own
overlapping spans, so the tracks are a fact about the board rather than a
threshold someone tuned.

**Placement is held to the same standard of proof as row count** (see
`DUAL_ROW_HEADERS` in the generator). A header's position comes from its own
reference designator in that board's layout export — never from a product
photo, a sibling revision, or the designator's number. And a board is placed
only when *every* header the wiring map lists is found: a board view missing one
connector cannot be told apart from a board that does not have one.

Two kinds of export can supply this, and `tools/pcb_layout.py` reads both:

* a **mechanical DXF**, which places the parts itself;
* a **fab package** — a pick-and-place spreadsheet beside the gerbers the
  boards were made from. Neither half places a connector alone (the P&P names
  the designator and its pin count but gives a point; the gerber has every pad
  and no designator anywhere), and together they are what the DXF gives. The
  two files also check each other: the part origin has to fall inside the pad
  array grown from it, and that array has to come to exactly the pin count the
  P&P states, or the header is not placed.

A board no export places can still be *arranged*, and that is a different claim
— so it is a different key. `arrangement` carries grid cells, not millimetres,
and the note beside the drawing reads "arranged as the board's maker specifies.
Not measured from the PCB" rather than naming a file. Writing an authored
arrangement as invented coordinates would have made it indistinguishable from a
measurement the moment it was serialised; a board never carries both.

A header the arrangement does not name is **not placed**: it falls to a row of
its own below everything that is, in map order. That is the honest rendering of
"the direction did not cover this connector". A name the board does not have,
on the other hand, aborts the run — otherwise a typo would land in that same
unplaced row and look exactly like a deliberate omission.

| Board | Placed | Kind | Evidence |
|---|---|---|---|
| 🟢 La Frite (`aml-s805x-ac`) | 7J1, 2J2, 9J5 | measured | `AML-S805X-AC-TOP-190308.dxf`, a PADS/PowerPCB export of `XH_S805X_DDR4_V01_190302.pcb`: outline 55.999 × 65.000 mm from layer `BOARD_OUTLINE_00`, each header from its placed part and the pad stacks under it |
| 🟢 Le Potato (`aml-s905x-cc`) | 7J1, 2J3, 2J1, 9J1 | measured, `orient: 180` | `AML-S905X-CC-V1.0-A-smt-production-180611.rar`, the V1.0-A SMT production package: designators, origins and pin counts from `坐标文件/tmp3774.xlsx`, pad extents from the soldermask layer `ln457zc06129a0.gts` of the fab gerbers inside it, outline 84.000 × 56.000 mm from `ln457zc06129a0.gko`. The gerbers are a 2-up panel with each board rotated 180°; the mapping between the two frames lands all four designators on their own pads to within 0.001 mm, and the grown arrays come to 40 / 8 / 3 / 3 pads against the P&P's own counts. The **orientation** is not from the package — it is the board owner's, 2026-08-08, so the 40-pin header reads first; see `orient` above |
| 🟡 Renegade Elite (`roc-rk3399-pc`) | J6, J15, J20 · J1, J12, J21 · J13 | **owner-directed, not measured** | Board owner, 2026-08-08: "the 40P header should always be first. for ROC-RK3399-PC, it should display similar like how it's laid out on the left/right side with the 6 pin then the 30 pin headers on each side. the 3P uart header can go on the bottom." Which connectors share a side is not in that direction and no export places this board (below), so the pairing follows the V1.1-A schematic's own grouping — `J12`+`J21` are one M.2 NGFF interface drawn side by side under a single label, `J15`+`J20` are the two connectors the product specification calls the 30-pin GPIO headers. **`J16` (1×4 SPI-NOR programming header) is not placed**: the direction never mentions it, so it falls to the end rather than being given a side |
| 🟡 Tritium H3 / H5 | — | — | The DXF places 7J1 (40 pads, board 84.000 × 56.000 mm), but 2J3 is in neither the top nor the bottom export, so one of two headers has no position. Nothing else in the directory carries placement: the two `.dwg` are unreadable (below) and `ALL-H3-CC-V1.0A Headers.xlsx` is a pin table, not coordinates |
| 🔴 Renegade Elite — *placement* | — | — | No layout export for *this* board, which is why the row above is an arrangement and not a placement. `rk3399-silkscreen-{top,bottom}.pdf` are filed under `roc-rk3399-pc-v2/` beside a v1.2A schematic and changelog, so they are the later board's plots — and they are CAM350 vector output regardless: 5404 stroked paths, zero text elements and zero images after `pdftocairo -svg`, so the designators cannot be read as text. Needs a DXF/ODB++/IPC-2581 export, or the layout in `ROC_3399_ACC_V1.0_180619.rar` (a git-LFS pointer whose object is not fetched) |
| 🔴 Alta, Solitude | — | — | The V0.2 Gerber archives are apertures and stroked silkscreen only — no reference designators, and no pick-and-place or assembly file beside them. Which pad array is which header cannot be read out, only guessed |
| 🔴 Das Frite | — | — | Two binary AutoCAD `.dwg` (AC1018) and no reader: LibreCAD ships only a `dxf2pdf` console tool that takes DXF, and fed the file it produced nothing in 180 s; there is no `dwg2dxf`/libredwg/QCAD anywhere on the fleet. V2.0 is a different PCB from the V1.0A La Frite stands on, so that DXF is not evidence for it |
| ⚪ everything else | — | — | No mechanical or layout export in the tree |

`tools/pcb_layout.py` can be run directly against a DXF to see what it found
before the number is trusted:

```sh
tools/pcb_layout.py <file.dxf> [designator ...]
```

Reading a fab package needs `unrar` (the packages are RARs holding a second RAR
of gerbers). A host without it places every other board exactly as before and
says so for this one, rather than failing the run.

### Electrical

Where a datasheet extract exists for the SoC, the detail panel also carries an
**Electrical** section: IO pad type, direction, state and pull at reset, drive
strength, interrupt capability, the pad's VCCIO power domain, and — resolved
from that domain — the rail range and the DC characteristics (Vil / Vih / Vol /
Voh, threshold points, pull-up and pull-down resistance) for that supply. A rail
that is supply-selectable shows *both* operating points and says which fact is
missing (what the board feeds it), rather than picking one.

Today that is the RK3328 boards, from `rockchip/rk3328/gpio_pinmux.json`
(datasheet Table 3-2 rails + Table 3-3 DC, plus the per-pad power domains TRM
part 1 names) and `rockchip/rk3328/gpio_pinmux_datasheet.json` (Table 2-3
per-pad characteristics) in the internal hardware-documentation repo, whose
location the generator takes as `--docs-repo`. Another SoC drops in by
adding a class to `ELEC_FOR_SOC` in the generator: it needs a `board()` and a
`lookup(chip, line)`, and the frontend renders whatever those return.

Values are transcribed, never computed — the datasheet's own expressions
(`3.3x0.7`) survive as expressions, `NA` becomes an em dash, and a field the
extract does not carry renders as an em dash rather than as a default. Fields
are genuinely sparse: a VCCIO rail is named for 25 of the Renegade's 29 header
GPIO rows, and the other 4 show the domain as unknown and no thresholds at all.

The rail is **not** in the datasheet — its Table 2-3 has no domain column. The
only per-pin statement is the suffix on the pad-cell name in TRM part 1's
per-module interface tables (`IO_PWM2_GPIO2A6vccio5`). The four that stay blank
— GPIO0_A0, GPIO0_A2, GPIO0_D3, GPIO1_D4 — appear in no interface table in
either book, so nothing is known to transcribe; inferring one from a
neighbouring ball would put a wrong V<sub>ih</sub> on a page people wire
hardware from. See `tools/gpio-extract.md` in the docs repo.

**Analog pins are marked as analog.** The `ADC` / `DAC` rows in the wiring-tool
map (Renegade `SARADC_IN0/IN1`, La Frite `LOLN/LORN`) are not digital GPIO
pads — the RK3328 datasheet's Table 2-5 type B ("tri-state output pad with
input, ... pull-up/pull-down, slew rate and drive strength configurable")
describes every digital GPIO and none of these. They get a round tile instead of
a square one, and their panel says the digital thresholds do not apply rather
than showing numbers that describe a different pad cell.

Function classes (12V / 5V / 3.3V / low-voltage rail, ground, GPIO, I2C, SPI,
UART, PWM, I2S, PCM, TDM, S/PDIF, PDM/DMIC, analog audio, ADC, clock, JTAG,
CEC, IR, SDIO, NAND, video/TS, PCI Express, USB, Ethernet, misc) come from the
map's `Chip` column where it names one outright, and otherwise from the pin's
SoC pad name and declared functions. Audio is split by bus rather than lumped:
an I2S data lane, an S/PDIF output and a mic bitstream are not
interchangeable, and the audio master clocks (MCLK, meson AM_CLK) sit with the
other clocks.

**A `Chip` value the generator does not know is a build failure, not a green
pin.** Every fixed-function `Chip` in the wiring-tool maps — `12V`, `1.8V`,
`3.0V`, `PCIE`, `USB`, `PHY`, `AUDIO`, `CVBS`, `CLK`, `I2C` as well as the
rails, `GND`, `ADC` and `DAC` — is mapped explicitly in `CHIP_CLASS`, and an
unmapped one aborts the run. The classifier used to fall through to `gpio` for
anything it did not recognise, which painted Renegade Elite's 12V rail and its
sixteen PCIe lanes the same green as a muxable header pad.

### Board visibility

Each board carries a `status` in the generator's `BOARDS` table:

| status | Meaning | Listed |
|---|---|---|
| `production` | Shipping, sold to customers | Always |
| `preprod` | V0.X engineering build, never sold | `?hidden=1` only |
| `unreleased` | Production design, not launched yet | `?hidden=1` only |

`?hidden=1` adds the unlisted boards to the dropdown, badges the header, and
banners the board itself. Without it a `?board=<unlisted-id>` deep link falls
back to the default board, so an unannounced product cannot be reached by
guessing its id.

### Regenerating

```sh
tools/gen-pinout-data.py                 # default: ../libretech-wiring-tool
tools/gen-pinout-data.py --lwt <path>    # explicit wiring-tool checkout
tools/gen-pinout-data.py --out <dir>     # write elsewhere (data/ is replaced)
```

Add a board by extending the `BOARDS` dict in the generator and re-running it.
Boards without a `gpio.map` in the wiring tool are not listed.

## Frontend

Framework-free static site: `index.html`, `css/style.css`, `js/app.js`.
Deep links use `?board=<id>`. Serve the directory over HTTP to run locally
(`python3 -m http.server`); `file://` blocks the JSON fetches.

## License

Generated data inherits the MIT license of libretech-wiring-tool.
