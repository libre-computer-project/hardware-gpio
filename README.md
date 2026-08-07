# Libre Computer GPIO Pinout

Interactive GPIO / pinmux reference for Libre Computer boards, served at
[gpio.hardware.libre.computer](https://gpio.hardware.libre.computer) via
GitHub Pages. Inspired by [pinout.xyz](https://pinout.xyz).

Pick a board from the dropdown. Each header is drawn the way it sits on the
board — pin numbers down the middle, odd pins on the left rail, even on the
right. Every pin carries a square split across the middle: the top band is the
board's own colour for that pin (yellow I2C, blue SPI, orange 3.3V, red 5V),
and below it sits one vertical stripe per *other* mux the pad can reach. A pin
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
| `data/<board>.json` | Per-board headers and pins with function classes, pinmux registers, and (where published) per-pad electricals + the board's rail/DC tables |

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

Function classes (power, ground, GPIO, I2C, SPI, UART, PWM, I2S, PCM, TDM,
S/PDIF, PDM/DMIC, analog audio out, ADC, clock, JTAG, CEC, IR, SDIO, NAND,
video/TS, USB, Ethernet, misc) are derived from the pin's SoC pad name and
declared functions. Audio is split by bus rather than lumped: an I2S data lane,
an S/PDIF output and a mic bitstream are not interchangeable, and the audio
master clocks (MCLK, meson AM_CLK) sit with the other clocks.

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
