#!/usr/bin/env python3
"""Tests for gen-pinout-data.py's Rockchip mux reading.

  - RockchipMux.canon drops the map's reset-pull suffix after a letter as well
    as a digit (FLASH_VOL_SEL_u pairs with the TRM's flash_vol_sel).
  - RockchipMux routes are RK3328's own: pinctrl-rockchip.c holds one route
    table per SoC, and a file-wide scan attached other SoCs' entries.
  - MediatekMux (MT8385) reads the MT8183 pin table and mode-field geometry.

The route arms read the kernel tree (--linux, default ../libretech-builder/linux
beside this repo, else ~/git/libretech-builder/linux) and are skipped, and say
so, when it is absent.

usage: tools/test-gen-pinout-data.py [--linux DIR]
Exit 0 = PASS; prints each failing arm.
"""
import argparse
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("gen", HERE / "gen-pinout-data.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--linux", default=None)
a = ap.parse_args()

C = gen.RockchipMux.canon
check("canon must-accept: FLASH_VOL_SEL_u is the TRM's flash_vol_sel", C("FLASH_VOL_SEL_u"), C("flash_vol_sel"))
check("canon: CIF_D7_M1_d is still the TRM's cif_data7m1", C("CIF_D7_M1_d"), C("cif_data7m1"))
check("canon: SPI_RXD keeps its D (only a lowercase _u/_d/_z suffix is a pull)", C("SPI_RXD"), "SPIRXD")


def old_canon(name):        # the pre-fix rule, kept here as the must-fire arm
    s = re.sub(r"[^A-Z0-9]", "", name.upper()).replace("DBG", "")
    s = re.sub(r"(?<=\d)[UDZ]$", "", s)
    return s.replace("DATA", "D")


check("canon must-fire: the old rule leaves FLASH_VOL_SEL_u unpaired",
      old_canon("FLASH_VOL_SEL_u") == old_canon("flash_vol_sel"), False)

CLASSES = ("BOOK-OMISSION", "DRIVER-EXTRA", "DRIVER-ERROR")
TSIN = [("GPIOH_6", "tsin_b_clk"), ("GPIOH_7", "tsin_b_d0"), ("GPIOH_8", "tsin_b_sop"),
        ("GPIOH_9", "tsin_b_d_valid")]
check("driver-only: the table is closed (S905X and S805X GPIOH_6-9 TSIN_B, A311D GPIOX_5 SDCARD_CMD)",
      sorted(gen.DRIVER_ONLY), sorted([(s, p, g) for s in ("S905X", "S805X") for p, g in TSIN]
                                      + [("A311D", "GPIOX_5", "sdcard_cmd_x")]))
check("driver-only: every flag names its class and cites a page",
      [k for k, v in gen.DRIVER_ONLY.items()
       if not (v.startswith("driver-only") and any(c in v for c in CLASSES) and ":" in v.split("(", 1)[-1])], [])
check("driver-only: no row carries DRIVER-ERROR since linux-6.18.y-lc fbffd1cecfd82 fixed the TSIN_B bits",
      [k for k, v in gen.DRIVER_ONLY.items() if "DRIVER-ERROR" in v], [])
check("driver-only: S805X's rows say the function is the book's and only the register is the driver's",
      sorted(v.split(":")[0] for k, v in gen.DRIVER_ONLY.items() if k[0] == "S805X"), ["driver-only register"] * 4)

check("not-observed: a closed table, I2S_AO_CLK_IN on GPIOH_7 of S905X and S805X, each flag says so",
      (sorted(gen.SILICON_NOT_OBSERVED),
       all(v.startswith("not observed on silicon:") for v in gen.SILICON_NOT_OBSERVED.values())),
      ([("S805X", "GPIOH_7", "I2S_AO_CLK_IN"), ("S905X", "GPIOH_7", "I2S_AO_CLK_IN")], True))

A = gen.RK3399_ALIAS
check("G3 alias: a closed table of 19 RK3399 pairs, each citing a datasheet and a TRM page:line",
      (len(A), [k for k, (t, d, r) in A.items() if not (re.fullmatch(r"p\d+:\d+", d) and re.fullmatch(r"p\d+:\d+", r))]),
      (19, []))
docs = next((Path(p) for p in (HERE.parent.parent.parent / "claude", Path.home() / "git" / "claude")
             if (Path(p) / "rockchip/rk3399/gpio_pinmux.json").is_file()), None)
if docs is None:
    print("SKIP G3 lookup arms: no docs repo with rockchip/rk3399/gpio_pinmux.json")
else:
    m = gen.Rk3399Mux(docs)
    e = m.lookup(2, 20, "SDIO0_D0", "GPIO2_C4")      # GPIO2_C4: bank 2, line C4 = 20
    check("G3 must-accept: GPIO2_C4 SDIO0_D0 takes the TRM's sdio_data0 value (1), flagged alias",
          (e.get("value"), e.get("flag", "").startswith("alias: SDIO0_D0 is the TRM's sdio_data0")), (1, True))
    e = m.lookup(2, 21, "SDIO0_D0", "GPIO2_C5")
    check("G3 must-reject: an unlisted (pad, name) never aliases (SDIO0_D0 on GPIO2_C5)",
          ("value" in e, "flag" in e), (False, False))
    e = m.lookup(2, 16, "UART0_RX_u", "GPIO2_C0")
    check("G3: the map's reset-pull suffix does not block the alias (UART0_RX_u -> uart0bt_sin, 1)",
          e.get("value"), 1)

linux = next((Path(p) for p in (a.linux, HERE.parent.parent / "libretech-builder" / "linux",
                                Path.home() / "git" / "libretech-builder" / "linux")
              if p and (Path(p) / gen.RockchipMux.DRIVER).is_file()), None)
if linux is None:
    print("SKIP route arms: no kernel tree with drivers/pinctrl/pinctrl-rockchip.c")
else:
    r = gen.RockchipMux(linux).routes
    check("routes must-accept: RK3328 GPIO2_C0 mux 3 is its own tsp_d5m1 route",
          (r.get((2, 16, 3)) or (None, None, None))[2], "tsp_d5m1")
    check("routes must-reject: GPIO2_B4 mux 2 carries no route (uart2-txm1 is another SoC's)",
          (2, 12, 2) in r, False)
    check("routes: exactly the 12 entries of rk3328_mux_route_data[]", len(r), 12)
    # MediaTek (MT8385 = MT8183 die): mode field 0x10005300 + (pin/8)*0x10, bit (pin%8)*4
    mt = gen.MUX_FOR_SOC["MT8385"](linux, None, None)
    check("mtk must-accept: GPIO81 SDA1 is mode 1 at 0x100053a0 bit 4",
          {k: mt.lookup(0, 81, "SDA1").get(k) for k in ("reg", "bit", "width", "value")},
          {"reg": "0x100053a0", "bit": 4, "width": 4, "value": 1})
    check("mtk: the datasheet's TDM_MCK_2nd matches the driver's TDM_MCK_2ND (GPIO165, case only)",
          (mt.lookup(0, 165, "TDM_MCK_2nd") or {}).get("value"), 6)
    check("mtk must-reject: a function of another pin is no selector here (SCL1 on GPIO81)",
          mt.lookup(0, 81, "SCL1"), None)
    check("mtk: all 192 pins of pinctrl-mtk-mt8183.h parsed", len(mt.pins), 192)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("PASS")
