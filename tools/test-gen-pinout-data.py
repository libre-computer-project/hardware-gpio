#!/usr/bin/env python3
"""Tests for gen-pinout-data.py's Rockchip mux reading.

  - RockchipMux.canon drops the map's reset-pull suffix after a letter as well
    as a digit (FLASH_VOL_SEL_u pairs with the TRM's flash_vol_sel).
  - RockchipMux routes are RK3328's own: pinctrl-rockchip.c holds one route
    table per SoC, and a file-wide scan attached other SoCs' entries.

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
check("driver-only: the swapped TSIN_B bits carry DRIVER-ERROR on both SoCs, nothing else does",
      sorted(k[1:] for k, v in gen.DRIVER_ONLY.items() if "DRIVER-ERROR" in v),
      sorted([("GPIOH_7", "tsin_b_d0"), ("GPIOH_9", "tsin_b_d_valid")] * 2))
check("driver-only: S805X's rows say the function is the book's and only the register is the driver's",
      sorted(v.split(":")[0] for k, v in gen.DRIVER_ONLY.items() if k[0] == "S805X"), ["driver-only register"] * 4)

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

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("PASS")
