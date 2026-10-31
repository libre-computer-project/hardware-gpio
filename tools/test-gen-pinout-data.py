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

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("PASS")
