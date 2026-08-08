#!/usr/bin/env python3
"""Generate pinout JSON data from libretech-wiring-tool gpio.map files.

Source of truth: libre-computer-project/libretech-wiring-tool (MIT),
libre-computer/<board>/gpio.map, tab-separated schema:

    #Header Pin Chip Line sysfs Name Pad Ref Desc

Pinmux cross-reference: the kernel pinctrl drivers are parsed at generation
time so every mux option on a GPIO pin carries its exact register offset
(absolute address + bit field + value written by the driver):

    meson-gxl   drivers/pinctrl/meson/pinctrl-meson-gxl.c      (S905X/S805X)
    meson-g12a  drivers/pinctrl/meson/pinctrl-meson-g12a.c     (A311D/S905D3)
    rockchip    drivers/pinctrl/pinctrl-rockchip.c             (RK3328)
    sunxi       drivers/pinctrl/sunxi/pinctrl-sun{8i-h3,50i-h5}.c (H3/H5)

Electrical cross-reference: where a datasheet extract exists for the SoC, each
pad also carries its direction, state and pull at reset, drive strength,
interrupt capability and VCCIO power domain, and the board file carries the
rail + DC-characteristics tables those resolve against (see ELEC_FOR_SOC).

Output (committed, served by GitHub Pages):
    data/boards.json      board index
    data/<board-id>.json  full pin data per board

Usage: tools/gen-pinout-data.py [--lwt ...] [--linux ...] [--out ...]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pcb_layout

REPO_ROOT = Path(__file__).resolve().parent.parent

# Board metadata: id -> (model, product name, SoC, vendor, status)
#
# status drives visibility on the site:
#   production  shipping, sold to customers -- shown to everyone
#   preprod     V0.X engineering build, never sold  -- only with ?hidden=1
#   unreleased  production design, not launched yet -- only with ?hidden=1
BOARDS = {
    "all-h3-cc-h3":    ("ALL-H3-CC-H3",    "Tritium H3",           "H3",     "Allwinner", "production"),
    "all-h3-cc-h5":    ("ALL-H3-CC-H5",    "Tritium H5",           "H5",     "Allwinner", "production"),
    "aml-a311d-cc":    ("AML-A311D-CC",    "Alta",                 "A311D",  "Amlogic",   "production"),
    "aml-a311d-cc-v01": ("AML-A311D-CC-V01", "Alta (pre-prod)",    "A311D",  "Amlogic",   "preprod"),
    "aml-s805x-ac":    ("AML-S805X-AC",    "La Frite",             "S805X",  "Amlogic",   "production"),
    "aml-s805x-ac-v2": ("AML-S805X-AC-V2", "Das Frite",            "S805X",  "Amlogic",   "production"),
    "aml-s905d3-cc":   ("AML-S905D3-CC",   "Solitude",             "S905D3", "Amlogic",   "production"),
    "aml-s905d3-cc-v01": ("AML-S905D3-CC-V01", "Solitude (pre-prod)", "S905D3", "Amlogic", "preprod"),
    "aml-s905x-cc":    ("AML-S905X-CC",    "Le Potato",            "S905X",  "Amlogic",   "production"),
    "aml-s905x-cc-v2": ("AML-S905X-CC-V2", "Sweet Potato",         "S905X",  "Amlogic",   "production"),
    "aml-s905x-cc-v3": ("AML-S905X-CC-V3", "Das Potato",           "S905X",  "Amlogic",   "unreleased"),
    "roc-rk3328-cc":   ("ROC-RK3328-CC",   "Renegade",             "RK3328", "Rockchip",  "production"),
    "roc-rk3328-cc-v2": ("ROC-RK3328-CC-V2", "Das Renegade",       "RK3328", "Rockchip",  "unreleased"),
    "roc-rk3399-pc":   ("ROC-RK3399-PC",   "Renegade Elite",       "RK3399", "Rockchip",  "production"),
}

# Physical arrangement per header, because the wiring-tool map does not carry
# it: it has Header and Pin and nothing about rows. The site used to infer
# "8 pins, even -> 2x4", which is wrong -- Le Potato's 2J3 is 8 pins in ONE
# row, and inferring geometry from a count is guessing at a fact the board
# either has or does not.
#
# Only the 40-pin headers are two-row, and each one is confirmed by its
# connector footprint in that board's own schematic:
#
#   Le/Sweet/Das Potato  7J1  CON40-2X20-2.54MM-DIP / 40P-2X20-2.54MM
#   La Frite / Das Frite 7J1  40P-2X20-2.54MM
#   Alta (+v01)          7J1  CON40-2X20 / 40P-2X20-2-54MM
#   Solitude (+v01)      7J1  CON40-2X20-2.54MM-DIP
#   Tritium H3 / H5      7J1  CN-2P00-2X20P / A2005WV-N-2X20P
#   Renegade (+v2)       J1   CON_2X20PIN_2D54_DIP
#
# Renegade Elite's four 30-pin headers are two-row on the same standard, from
# the Extension Interface sheet of its schematic (page 28 on V0.1 / V1.1-A,
# page 29 on V1.2A): J12, J15, J20 and J21 are every one of them part CON30A
# with footprint SMD_PH_15x2_2d0, four of each on the sheet in all three
# revisions -- "15x2" states the geometry outright. J21 is the last of the
# four and carries no SoC GPIO (four PCIe lanes, the reference clock, 12V/5V
# and grounds), which is why it was absent for a while; the footprint is the
# same evidence the other three stand on, and a connector you can plug into
# belongs on the pinout whatever is behind it.
#
# Everything else is single-row, and none of it is guesswork any more:
#
#   Renegade J21, J22          SIP-3P-2D54 in the schematic -- "single in-line"
#   Le Potato 2J3 (8 pins)     1x8, confirmed by the board owner
#   La Frite 2J2, 9J5 (4 pins) 1x4, confirmed by the board owner
#   every 3-pin header         1x3 by arithmetic: Potato 2J1/9J1, Alta 2J1,
#                              Solitude 2J1, Tritium 2J3 -- three pins cannot
#                              be two rows
#
# The two 4-pin La Frite headers were the only ones a count could not settle
# (1x4 or 2x2), and no connector part text exists for either -- 2J2's pads are
# present but unpopulated, which is likely why.
#
# Add a header here only with footprint evidence. Drawing a 1xN header as 2xN
# invents a rail the board does not have; the reverse merely looks unlike the
# hardware, and only the first misleads someone counting pads with a jumper
# wire in hand.
# Entries are either a bare header id, or "<board-id>:<header-id>" when the
# same id means different geometry on different boards. J21 is exactly that
# case and the reason the qualified form exists: on Renegade Elite it is one
# of the four CON30A 2x15 headers, while on Renegade (+v2) J21 is the 3-pin
# SIP-3P-2D54 listed above as single-row. A bare "J21" here would draw
# Renegade's 3-pin strip as a 2x2 -- the invented-rail error this whole
# comment block exists to prevent.
#
# Renegade Elite's two CON6A are the same standard again, off the same
# Extension Interface sheet: J1 and J6 are both part CON6A with footprint
# SMD_PH_3x2_2d0 -- "3x2" states the geometry outright -- in V0.1, V1.1-A and
# V1.2A alike. Neither carries an SoC pad (J6 is the 12 V pair, J1 the four
# PoE magnetics taps), which is why they were absent for a while; the
# footprint is the same evidence the other six stand on.
#
# "roc-rk3399-pc:J1" is board-qualified even though a bare "J1" is already
# present for Renegade's 40-pin CON_2X20PIN_2D54_DIP and would match it too.
# The two are unrelated connectors that collide on an id, and the whole point
# of the qualified form is that the set says which board's evidence it is
# quoting -- an unqualified match here would be a coincidence, not a citation.
DUAL_ROW_HEADERS = {"7J1", "J1", "J12", "J15", "J20",
                    "roc-rk3399-pc:J1", "roc-rk3399-pc:J6",
                    "roc-rk3399-pc:J21"}


def is_dual_row(board, header):
    return header in DUAL_ROW_HEADERS or f"{board}:{header}" in DUAL_ROW_HEADERS


# The 40-pin header comes first on every board that has one (board owner,
# 2026-08-08).
#
# It is the connector the page exists for -- the one a reader came to count pads
# on -- and on every other board it is also the one the wiring map happens to
# list first, so leaving the order to the map made the right answer depend on a
# file we do not own. Stated here it is a rule instead of a coincidence, and a
# map that ever reorders its stanzas cannot quietly demote it.
#
# Positions, not rows: a pin wired to two SoC lines is two rows in the map and
# still one position on the connector, which is the same count the header title
# shows.
HEADER_FIRST_POSITIONS = 40


def order_headers(headers):
    """Headers in draw order: a 40-position connector first, else map order."""
    def positions(h):
        return len({p["pin"] for p in h["pins"]})
    return sorted(headers, key=lambda h: positions(h) != HEADER_FIRST_POSITIONS)


# Where each connector physically sits on the board.
#
# Same standard of proof as DUAL_ROW_HEADERS above, for the same reason. Row
# count and position are both claims about hardware, and both are only worth
# drawing if they come from that board's own CAD data: a header drawn at the
# wrong end of the board misleads someone counting pads with a jumper wire in
# hand exactly as an invented second rail does. So a board is placed only from a
# layout export that names the reference designator itself -- never from a
# product photo, never from a sibling revision, and never from the designator's
# number (7J1 does not mean "sheet 7", and even where it does that is a
# schematic fact, not a placement).
#
# Paths are relative to --docs-repo (the internal hardware-documentation repo).
# `source` is what the site shows as provenance, so it has to name the file and
# what was read out of it, not just the board.
#
# An entry is one of two shapes, matching the two readers in pcb_layout:
#
#   dxf   a mechanical DXF, which places the parts itself.
#   fab   a fab package -- {pnp, mask, frame, board}. `pnp` and `mask` are
#         archive-member chains ("a.rar!inner.rar!x.gts"); `frame` and `board`
#         are the two facts about the panel that neither file states, quoted
#         with the file they were read from in the comment on the entry.
#
# `orient` is the one thing in the entry that is NOT measured, and is kept
# separate from `source` for exactly that reason. A CAD frame has no "this way
# up": it fixes every connector RELATIVE to every other, and says nothing about
# which edge the reader is holding towards them. Both 0 and 180 are faithful
# views of the same measurements -- 180 is the same board seen from the other
# end -- so the choice has to come from somewhere else, and where it does it
# says so in `orient_source` rather than riding along on the CAD citation.
PCB_LAYOUT = {
    "aml-s805x-ac": {
        "dxf": "amlogic/gxl/s805x/schematics/aml-s805x-ac/technical-reference/"
               "model/public/AML-S805X-AC-TOP-190308.dxf",
        "source": "AML-S805X-AC-TOP-190308.dxf — PADS/PowerPCB DXF export of "
                  "XH_S805X_DDR4_V01_190302.pcb: board edge from layer "
                  "BOARD_OUTLINE_00, each header from its own placed part and "
                  "the pad stacks under it",
    },
    # Le Potato has no mechanical export -- what it has is the SMT production
    # package for V1.0-A, and both halves of it are needed (pcb_layout.fab_parts).
    #
    # frame  The gerbers are a 2-up panel, 84.000 x 112.000 mm, in which each
    #        board is placed rotated 180 degrees; the P&P is in the design's own
    #        frame. panel = (83.0, 56.0) - pnp maps between them, and lands
    #        7J1 / 2J1 / 9J1 / 2J3 on their own pads to within 0.001 mm.
    # board  Board 1 of that panel is the rounded rectangle x -2.000..82.000,
    #        y 0..56.000 on ln457zc06129a0.gko -- 84.000 x 56.000 mm.
    #
    # The pin counts the grown pad arrays come to (40 / 8 / 3 / 3) are checked
    # against the P&P's own Pins column, which is what makes the arrays the
    # connectors they are named for rather than whatever was nearby.
    "aml-s905x-cc": {
        "fab": {
            "pnp": "amlogic/gxl/s905x/schematics/aml-s905x-cc/"
                   "AML-S905X-CC-V1.0-A-smt-production-180611.rar"
                   "!AML-S905X-CC_V1.0-A贴片生产文件_180611/坐标文件/tmp3774.xlsx",
            "mask": "amlogic/gxl/s905x/schematics/aml-s905x-cc/"
                    "AML-S905X-CC-V1.0-A-smt-production-180611.rar"
                    "!AML-S905X-CC_V1.0-A贴片生产文件_180611/钢网文件/"
                    "AML-S905X-CC_V1.0-A打板文件_180611生产稿.rar"
                    "!ln457zc06129a0/ln457zc06129a0 Working Gerber/"
                    "ln457zc06129a0.gts",
            "frame": (83.0, 56.0),
            "board": (-2.0, 0.0, 82.0, 56.0),
        },
        "source": "AML-S905X-CC-V1.0-A-smt-production-180611.rar — the V1.0-A "
                  "SMT production package: designators, origins and pin counts "
                  "from the pick-and-place 坐标文件/tmp3774.xlsx, each header's "
                  "pad extent from the soldermask layer ln457zc06129a0.gts of "
                  "the fab gerbers inside it, board edge 84.000 × 56.000 mm "
                  "from ln457zc06129a0.gko",
        # 7J1 sits along the y-minimum edge of the design frame, so read with
        # +y up it lands at the BOTTOM of the drawing and the three small
        # connectors read before it. Turning the board end-for-end puts it
        # first, which is the order the owner asked for and the way the product
        # is pictured. Nothing measured moves: all four connectors share one
        # column either way (their x spans all overlap 7J1's 26.454..76.446),
        # so on THIS board the rotation is only observable in the vertical
        # order -- it cannot swap a left for a right here.
        "orient": 180,
        "orient_source": "Board owner, 2026-08-08: the 40-pin header reads "
                         "first. The CAD frame fixes the connectors relative "
                         "to each other and not which edge is up, so this "
                         "picks between the two views its data allows; the "
                         "millimetres are untouched",
    },
}

# Boards examined and NOT placed, so the next person does not re-walk the tree:
#
#   all-h3-cc-h5     "ALL-H3-CC-H5-V1.1-220802 top.dxf" is the same kind of
#   all-h3-cc-h3     export and does place 7J1 (40 pads, board 84.000 x 56.000
#                    mm) -- but 2J3 is in neither the top nor the bottom export,
#                    so one of the board's two headers has no position. Placing
#                    the one and packing the other would read as a board view
#                    that is missing a connector rather than one this data
#                    cannot site, which is why require_all below refuses it.
#                    Nothing else in the directory carries placement: the two
#                    .dwg are unreadable (see aml-s805x-ac-v2 below) and
#                    "ALL-H3-CC-V1.0A Headers.xlsx" is a pin table, not
#                    coordinates.
#   roc-rk3399-pc    No layout export for THIS board. rk3399-silkscreen-{top,
#                    bottom}.pdf sit under roc-rk3399-pc-v2/ beside a v1.2A
#                    schematic and changelog, so they are the later board's
#                    plots -- and they are CAM350 vector output regardless:
#                    pdftocairo -svg gives 5404 stroked paths, 0 text elements
#                    and 0 images, so the designators cannot be read as text.
#                    The product specification PDF gives the board as
#                    120 x 72 x 11.9 mm and has a "4.PCB Size" drawing, but only
#                    as a JPEG. What would settle it: a DXF/ODB++/IPC-2581
#                    export, or the layout in ROC_3399_ACC_V1.0_180619.rar (a
#                    git-LFS pointer here, and the object is not fetched).
#                    Still not placed -- it carries an owner-directed
#                    arrangement instead (BOARD_ARRANGEMENT below), which is a
#                    weaker claim and says so on the page.
#   aml-a311d-cc     A311D-V0.2_Gerber.zip / S905D3-V0.2_Gerber.zip are Gerber
#   aml-s905d3-cc    only: apertures and stroked silkscreen, no reference
#                    designators, and no pick-and-place or assembly file beside
#                    them -- so unlike Le Potato below there is nothing to name
#                    a pad array, and which one is which header cannot be read
#                    out, only guessed.
#   aml-s805x-ac-v2  Two .dwg (binary AutoCAD AC1018) and no reader: LibreCAD
#                    ships only a dxf2pdf console tool that takes DXF, and fed
#                    the file it produced nothing in 180 s; no dwg2dxf/libredwg/
#                    QCAD anywhere on the fleet. V2.0 is a different PCB from the
#                    V1.0A the La Frite entry stands on.
#   everything else  No mechanical or layout export in the tree at all.


# A board named in PCB_LAYOUT that cannot be placed on THIS host is a run that
# would emit that board with less data than the committed file already carries,
# and nothing in the output says so. Le Potato is the live case: its measurement
# comes out of a RAR, so a host without `unrar` writes its board file with the
# whole `layout` block gone -- and the only trace is one line among fourteen.
#
# So a board that is SUPPOSED to be placed and is not stops the run by default.
# The documented "a host without unrar places every other board exactly as
# before and says so for this one" behaviour is still available, but as a
# deliberate --allow-unplaced rather than as what happens when you look away.
# Boards with no PCB_LAYOUT entry are unaffected: not being placed is their
# normal state, not a degradation.
class Unplaced(Exception):
    """A board PCB_LAYOUT names could not be placed from this host's files."""


def board_layout(board, headers, docs_repo, require_all=True):
    """Physical placement for one board, or None.

    Returns millimetres in a frame whose origin is the board outline's own
    minimum corner and whose +y is UP, which is the CAD frame -- the drawing
    flips it, rather than this baking a screen convention into the data.

    Raises Unplaced (never returns None) for a board PCB_LAYOUT names: see the
    note above. None only for a board it does not name.

    Nothing is placed unless EVERY header the wiring map lists is placed: a
    board view with a header missing cannot be told apart from a board that does
    not have one.
    """
    spec = PCB_LAYOUT.get(board)
    if not spec:
        return None
    if "dxf" in spec:
        path = Path(docs_repo) / spec["dxf"]
        if not path.is_file():
            raise Unplaced(f"layout source missing ({path})")
        name = path.name
        outline, found = pcb_layout.parts(str(path))
    else:
        fab = dict(spec["fab"])
        for key in ("pnp", "mask"):
            archive, _, member = fab[key].partition("!")
            if not (Path(docs_repo) / archive).is_file():
                raise Unplaced(f"layout source missing ({archive})")
            fab[key] = f"{Path(docs_repo) / archive}!{member}"
        name = Path(spec["fab"]["pnp"].split("!")[0]).name
        try:
            outline, found = pcb_layout.fab_parts(fab)
        except (OSError, subprocess.CalledProcessError) as exc:
            # The fab packages are RARs, so this is the no-`unrar` host.
            raise Unplaced(f"cannot read fab package ({exc})") from exc
    if not outline:
        raise Unplaced(f"no board outline in {name}")
    x0, y0, x1, y1 = outline
    placed = {}
    for h in headers:
        rec = found.get(h["id"])
        if not rec or "pads" not in rec:
            if require_all:
                raise Unplaced(f"{h['id']} not placed in {name}")
            continue
        px0, py0, px1, py1 = rec["pads"]
        placed[h["id"]] = {
            "x1": round(px0 - x0, 3), "y1": round(py0 - y0, 3),
            "x2": round(px1 - x0, 3), "y2": round(py1 - y0, 3),
            "pads": rec["npads"],
        }
    out = {
        "units": "mm",
        "origin": "board outline minimum corner; +x right, +y up (CAD frame)",
        "source": spec["source"],
        "board": {"w": round(x1 - x0, 3), "h": round(y1 - y0, 3)},
        "headers": placed,
    }
    if spec.get("orient"):
        out["orient"] = spec["orient"]
        out["orient_source"] = spec["orient_source"]
    return out


# Arrangements the board OWNER specified.
#
# This is a different KIND of claim from PCB_LAYOUT above and is deliberately a
# different key in the board file, so no reader -- and no later edit -- can
# mistake one for the other. PCB_LAYOUT is millimetres off that board's own
# export and answers "where is this connector"; this answers only "how should
# the page group them", from someone who has the board in hand. Writing it as
# invented millimetres would have made it indistinguishable from a measurement
# the moment it was serialised, so it is written as what it is: grid cells.
#
#   cells   header id -> [column, row] or [column, row, colspan], 0-based.
#           Two headers may share a cell; they are drawn stacked in it, which
#           is the same thing a shared cell means in the measured path (two
#           connectors whose spans overlap on both axes).
#   source  shown as the drawing's provenance, and says whose direction it is.
#
# A header the table does not name is NOT placed: it falls to a row of its own
# below everything named, in map order. That is the honest rendering of "the
# direction did not cover this connector" -- inventing a cell for it would put
# an authored position on the page with nobody behind it.
#
# A board may carry this AND a measured PCB_LAYOUT, and where it does the
# direction is what gets DRAWN -- see the note on emitting both, near the bottom
# of main().
#
# La Frite USED TO HAVE AN ENTRY HERE and deliberately does not any more. The
# direction it carried -- "for La Frite, 2J2 and 9J5 should be one on top of
# another to make better use of the space" (owner, 2026-08-08) -- is now what
# the generalised shape rule in ruleGrid() produces for that board unaided, and
# the owner's next instruction was "das frite, le potato, sweet potato all need
# this fix. we need to improve heuristics rather than hard code." A per-board
# entry that restates a general rule is exactly the hardcoding that asks about:
# it would shadow the rule (authored outranks it), so La Frite would stop
# tracking any later change to the rule while Das Frite -- the same product, one
# revision on, and unmeasured -- kept following it. This table is for directions
# the rule cannot reach.
BOARD_ARRANGEMENT = {
    # Board owner: "the 40P header should always be first. for ROC-RK3399-PC,
    # it should display similar like how it's laid out on the left/right side
    # with the 6 pin then the 30 pin headers on each side. the 3P uart header
    # can go on the bottom."
    #
    # So: two sides, each a 2x3 CON6A over two 2x15 CON30A, and J13 across the
    # bottom. What the direction does not settle is WHICH connectors share a
    # side, and no layout export for this board exists to settle it either (see
    # the not-placed list above). The pairing below is therefore read off the
    # Extension Interface sheet's OWN two columns, and is a grouping rather
    # than a position -- sheet position is draughting layout, not where the
    # connectors sit on the PCB.
    #
    # Measured by geometry off the sheet (stroked body-box runs from
    # `pdftocairo -svg`, designators from `pdftotext -bbox-layout`, both in the
    # 842x595 device space), V1.1-A p28 -- and V0.1 p28 is identical to the
    # hundredth of a point, V1.2A p29 within 0.3 pt:
    #
    #   left column    J6  x 196.70-211.80 (2x3, `DC_12V`/`SYS_12V`)
    #                  J12 x 186.60-201.70, J21 x 186.60-201.70 (2x15)
    #   right column   J1  x 609.90-625.10 (2x3, `POE1`-`POE4`)
    #                  J15 x 609.90-625.10, J20 x 609.90-625.10 (2x15)
    #
    # So the sheet groups the DC power pass-through with the M.2 NGFF pair and
    # the PoE tap with the two GPIO headers -- which is the opposite of what
    # this table said until 2026-08-08, when the board owner asked whether the
    # two 6-pin headers were reversed. They were.
    #
    #   J12 + J21  one M2.NGFF interface split across two connectors -- the
    #              schematic's p28 draws them side by side under a single
    #              label -- so they belong to each other wherever they sit,
    #              and J6 is the 6-pin in their column.
    #   J15 + J20  the two connectors the product specification calls the
    #              30-pin GPIO headers; J1 is the 6-pin in their column.
    #
    # Left is the GPIO side because the GPIO headers are what a reader opened
    # this page for -- so the sheet's right column is drawn left. The sides
    # themselves are owner-directed shape, not a measurement, and which
    # connector shares which side is the sheet's grouping and not a PCB
    # position -- which is what `source` says.
    "roc-rk3399-pc": {
        "cells": {
            "J1": [0, 0], "J15": [0, 1], "J20": [0, 2],
            "J6": [1, 0], "J12": [1, 1], "J21": [1, 2],
            "J13": [0, 3, 2],
        },
        # J16 is absent on purpose: a 1x4 SPI-NOR programming header the
        # direction never mentions. It falls to the end rather than being given
        # a side, because the two sides are the owner's statement and adding to
        # them would be ours.
        "source": "Owner-directed arrangement, 2026-08-08 — NOT measured from "
                  "the PCB: a 6-pin CON6A over two 30-pin CON30A on each side, "
                  "the 3-pin UART header J13 across the bottom. Which "
                  "connectors share a side follows the V1.1-A schematic's own "
                  "grouping — the Extension Interface sheet draws J1 with the "
                  "GPIO headers J15+J20 in one column, and J6 with the M.2 "
                  "NGFF pair J12+J21 in the other — not any layout export: "
                  "this board has none, so the sheet says which connectors go "
                  "together and not where any of them sits on the PCB. J16 is "
                  "not placed",
    },
}


def board_arrangement(board, headers):
    """Owner-directed ordinal arrangement for one board, or None."""
    spec = BOARD_ARRANGEMENT.get(board)
    if not spec:
        return None
    ids = {h["id"] for h in headers}
    # Same standard the Chip classifier is held to: a name that does not exist
    # is a build failure, not a header quietly dropped to the unplaced row --
    # which is where a typo would otherwise land, looking exactly like a
    # connector the direction chose not to place.
    unknown = sorted(set(spec["cells"]) - ids)
    if unknown:
        raise SystemExit(f"{board}: arrangement names headers the board does "
                         f"not have: {', '.join(unknown)}")
    return {"kind": "authored", "source": spec["source"], "cells": spec["cells"]}


# There is a THIRD way a board gets drawn side by side, and it deliberately
# emits nothing here. The board owner also gave a rule about a shape of board
# rather than about a board: where every other connector a board has, stacked,
# is shorter than its 40-pin header is tall, they go in one column beside it.
# That covers thirteen of the fourteen boards -- everything with a 40-pin header
# -- and needs no per-board data at all, because its only input is the header
# list already in the file.
#
# Writing it into those files as `arrangement` cells would be the mistake the
# arrangement/layout split exists to prevent, one level up. `layout` is
# millimetres off THIS board's export and `arrangement` is a direction naming
# THIS board's connectors; a rule read off the header list is neither, and once
# serialised into thirteen board files beside the one Renegade Elite entry it
# would be indistinguishable from thirteen more directions somebody gave. So it
# lives in ruleGrid() in js/app.js, computed, with its own note text that does
# not claim the board -- and these boards keep no placement key, which is the
# true statement about them.


# Function-class detection, checked in order against Ref then Desc.
CLASSES = [
    ("i2c",  ("I2C", "TWI")),
    ("spi",  ("SPI",)),
    ("uart", ("UART",)),
    ("pwm",  ("PWM",)),
    # Audio splits by bus, matching the frontend's classes: a pad is not
    # "audio", it is I2S data or S/PDIF or a mic bitstream.
    ("spdif", ("SPDIF",)),
    ("pdm",  ("PDM", "DMIC")),
    ("dac",  ("AL_CH", "AR_CH")),
    ("tdm",  ("TDM",)),
    ("pcm",  ("PCM",)),
    ("i2s",  ("I2S",)),
    ("adc",  ("ADC", "SARADC")),
    ("clk",  ("CLK",)),
    ("jtag", ("JTAG", "TDO", "TDI", "TMS", "TCK")),
    ("cec",  ("CEC",)),
    ("ir",   ("REMOTE", "IR_")),
    ("sdio", ("SDIO",)),
]


# Chip -> class for every non-gpiochip pad the maps declare.
#
# The Chip column is the map's OWN statement of what a pad is, so it is
# answered here in full and never handed to the name-matching fallback below.
# It used to answer only 5V/3.3V/GND/ADC/DAC, and everything else -- 12V,
# PCIE, USB, 1.8V, 3.0V, PHY, AUDIO, CVBS -- fell through the fallback and
# matched nothing, which returns "gpio", which the frontend paints green.
# A 12V rail wearing the GPIO colour is not a cosmetic slip: green on this
# page means "muxable pad, wire what you like to it", and the reader acts on
# the colour before reading the name.
CHIP_CLASS = {
    "12V":   "power12v",
    "5V":    "power5v",
    "3.3V":  "power3v3",
    "3.0V":  "powerlv",   # Renegade Elite J20.16 VCCA3V0_CODEC
    "1.8V":  "powerlv",   # Renegade Elite J15.16 VCC_1V8
    "GND":   "gnd",
    "ADC":   "adc",
    "DAC":   "dac",       # La Frite 9J5 line-out (LOLN/LORN)
    # Renegade Elite J20 is a codec break-out: HPO_L/R out, MIC_IN and LINE_IN
    # in. They share the DAC class because it covers analog audio in both
    # directions (its label says so) -- they are not SAR-ADC inputs, and
    # "adc" on this page means the SoC's SARADC.
    "AUDIO": "dac",
    "PCIE":  "pcie",
    "USB":   "usb",
    "CVBS":  "video",
    "CLK":   "clk",
    "I2C":   "i2c",
    # Renegade J22 PWREN/PWRON: board-level power control off the PMIC, not a
    # gpiochip line and not a bus -- "Other / control" is exactly that class.
    "PHY":   "misc",
    # A position that physically exists on the connector and is wired to
    # nothing: roc-rk3399-pc J12.13-30, J21.1/2, J20.30 are pads whose pin
    # lead terminates in mid-air on the schematic. It is a class, not an
    # omission -- skipping the row would renumber the drawing and make the
    # reader count pads wrong, which is the failure this class exists to stop.
    "NC":    "nc",
    # roc-rk3399-pc J16.3 FLASH_WP: the SPI NOR's own write-protect pin,
    # brought to the programming header through a 1K series resistor. It is a
    # board-level control line with no path to the SoC at all -- not a gpiochip
    # line, not a bus -- which is exactly what "Other / control" means here.
    "FLASH": "misc",
    # roc-rk3399-pc J1.1/2/4/6 POE1-4: the RJ45 magnetics' centre taps, brought
    # to a 2x3 header with nothing between them and the cable. Its own class
    # rather than a rail class or "eth", for two reasons that point the same
    # way. It is not a rail -- no regulator, no fuse, no current limit on this
    # board -- so painting it with the supply ramp would say "a rail this board
    # makes". And it is the highest voltage anything in these maps can present:
    # a PoE PSE drives up to 57 V DC, against 12 V for the deepest rail here.
    # "eth" would be the worst of the three: a green, on the row of a legend
    # where green means signal.
    "POE":   "poe",
}


def classify(chip, ref, desc):
    if chip in CHIP_CLASS:
        return CHIP_CLASS[chip]
    if not chip.isdigit():
        # The silent fall-through to green is what this guard exists to stop:
        # a new fixed-function Chip value must be given a class deliberately,
        # not inherit the one that says "safe to wire anything here".
        sys.exit(f"classify: unmapped Chip value {chip!r} ({ref} / {desc}); "
                 f"add it to CHIP_CLASS")
    text = (ref + " " + desc).upper()
    for cls, keys in CLASSES:
        if any(k in text for k in keys):
            return cls
    return "gpio"


class DatasheetMux:
    """Mux offsets straight from the vendor's own multiplexing tables.

    tools/gpio_ocr_extract.py in the docs repo writes one
    <vendor>/<soc>/gpio_pinmux.json per SoC, each function carrying the register,
    bit field and the value that selects it. Keyed by BOARD because S905X and
    S805X share a pinctrl driver but not a datasheet, as do A311D and S905D3.
    """

    PATHS = {
        "aml-s905x-cc": "amlogic/gxl/s905x", "aml-s905x-cc-v2": "amlogic/gxl/s905x",
        "aml-s905x-cc-v3": "amlogic/gxl/s905x",
        "aml-s805x-ac": "amlogic/gxl/s805x", "aml-s805x-ac-v2": "amlogic/gxl/s805x",
        "aml-a311d-cc": "amlogic/g12sm1/a311d",
        "aml-a311d-cc-v01": "amlogic/g12sm1/a311d",
        "aml-s905d3-cc": "amlogic/g12sm1/s905d3",
        "aml-s905d3-cc-v01": "amlogic/g12sm1/s905d3",
        "all-h3-cc-h3": "allwinner/h3", "all-h3-cc-h5": "allwinner/h5",
    }

    def __init__(self, docs_repo):
        self.root = Path(docs_repo) if docs_repo else None
        self._cache = {}

    def _load(self, board):
        if board not in self._cache:
            rel = self.PATHS.get(board)
            path = (self.root / rel / "gpio_pinmux.json") if (self.root and rel) else None
            data = {}
            if path and path.is_file():
                raw = json.loads(path.read_text())
                for pad, funcs in raw.get("pads", {}).items():
                    for name, info in funcs.items():
                        key = (pad.upper(), re.sub(r"[^A-Z0-9]", "", name.upper()))
                        data[key] = (name, info)
            self._cache[board] = data
        return self._cache[board]

    def lookup(self, board, pad, token):
        info = self._load(board).get(
            (pad.rstrip("*").upper(), re.sub(r"[^A-Z0-9]", "", token.upper())))
        if not info:
            return None
        name, d = info
        if d.get("bit") is None:
            return None            # a name with no selector is not an offset
        out = {"name": name, "source": "datasheet",
               "bit": d["bit"], "width": d.get("width", 1),
               "value": d.get("value", 1)}
        if d.get("address"):
            out["reg"] = d["address"]
        if d.get("register"):
            out["register"] = re.sub(r"(PERIPHS|AORTI)PINMUX", r"\1_PIN_MUX_",
                                     d["register"]).replace("AORTI", "AO_RTI")
        return out


def split_funcs(desc):
    if "/" in desc:
        toks = [s.strip() for s in desc.split("/")]
    else:
        toks = desc.split()
    out = []
    for t in toks:
        # "-" is the map's way of saying the pad has no alternate function;
        # it is an absence, not a mux, and must not reach the pin's chip list.
        if not t or t == "-":
            continue
        # map typo glue: "PCM1_DOUTPG_EINT12" -> PCM1_DOUT + PG_EINT12
        m = re.fullmatch(r"(.*?)(P[A-G]_EINT\d+)", t)
        if m and m.group(1):
            out += [m.group(1), m.group(2)]
        else:
            out.append(t)
    return out


def parse_map(path, board):
    headers = {}
    order = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 9:
            sys.exit(f"{path}:{lineno}: expected 9 tab-separated fields, got {len(fields)}")
        hdr, pin, chip, line_, sysfs, name, pad, ref, desc = fields
        if hdr not in headers:
            headers[hdr] = []
            order.append(hdr)
        is_gpio = chip.isdigit()
        headers[hdr].append({
            "pin": int(pin),
            "type": "gpio" if is_gpio else chip,
            "chip": int(chip) if is_gpio else None,
            "line": int(line_) if is_gpio else None,
            "sysfs": int(sysfs) if sysfs.isdigit() else None,
            "name": name,
            "pad": pad,
            "ref": ref,
            "funcs": split_funcs(desc),
            "cls": classify(chip, ref, desc),
        })
    for hdr in headers:
        headers[hdr].sort(key=lambda p: p["pin"])
    return [{"id": h,
             "rows": 2 if is_dual_row(board, h) else 1,
             "pins": headers[h]} for h in order]


# ---------------------------------------------------------------------------
# Kernel pinctrl cross-reference
# ---------------------------------------------------------------------------

def _array_body(text, decl):
    """Return the brace body of `decl ... = { ... };` (first match)."""
    m = re.search(re.escape(decl) + r"[^={]*=\s*\{", text)
    if not m:
        sys.exit(f"parser: declaration not found: {decl}")
    start = m.end()
    depth = 1
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
    sys.exit(f"parser: unbalanced braces after: {decl}")


def _parse_pin_numbers(header_text):
    """dt-bindings gpio header: #define NAME N, monotonic per gpio chip.

    Returns list of chips; each chip maps pin symbol -> number. A new chip
    starts whenever the numbering restarts (value <= previous)."""
    chips = []
    cur = {}
    prev = -1
    for name, num in re.findall(r"#define\s+(\w+)\s+(\d+)", header_text):
        num = int(num)
        if num <= prev and cur:
            chips.append(cur)
            cur = {}
        cur[name] = num
        prev = num
    if cur:
        chips.append(cur)
    return chips


def meson_domain(sym, chip, line, name, family):
    """Which meson pinctrl DOMAIN (0 aobus / 1 periphs) a map row belongs to.

    Not the map's Chip column, which is the LINUX GPIOCHIP INDEX -- a probe
    order, not a property of the silicon. GXL enumerates the AO controller as
    gpiochip0 and the periphs one as gpiochip1; G12/SM1 does the OPPOSITE, so
    reading Chip as a domain silently resolved every A311D and S905D3 pad
    against the wrong bank. It did not fail loudly: the group search simply
    matched nothing, every function fell through to the datasheet fallback, and
    the ~47 tokens per board the datasheet does not carry were dropped as
    "unmatched" -- a board's whole pinmux missing its register rows, with the
    only trace a count at the end of the run.

    The pad NAME is the fact that cannot be ambiguous: GPIOAO_3 names its own
    bank, and every bank belongs to exactly one domain. So the domain is read
    off the dt-bindings header, which is the same file the pin numbers come
    from. A name the header does not carry (TEST_N**, which has no muxes) falls
    back to Chip, which is no worse than before; a name it carries at a
    DIFFERENT pin number is a disagreement between the kernel and the wiring
    map, and picking either would put a wrong register on the page.
    """
    key = re.sub(r"[^A-Z0-9_]", "", (name or "").upper())
    for domain, syms in sym.items():
        if key in syms:
            if syms[key] != line:
                sys.exit(f"{family}: {name} is pin {syms[key]} in the "
                         f"dt-bindings header but line {line} in the wiring "
                         "map -- refusing to guess which is right")
            return domain
    return chip


class MesonGxlMux:
    """meson8-pmx: one enable bit per group; reg*4 byte offset, bit set = func.

    Mux block bases (reg-names = "mux"): aobus pinctrl@14 under the AO bus at
    0xc8100000 -> 0xc8100014; periphs pinctrl@4b0 under the EE bus at
    0xc8834000 -> 0xc88344b0 (arch/arm64/boot/dts/amlogic/meson-gxl.dtsi)."""

    family = "meson-gxl"
    BASES = {0: 0xC8100014, 1: 0xC88344B0}
    DRIVER = "drivers/pinctrl/meson/pinctrl-meson-gxl.c"
    NOTE = ("meson8-pmx: one enable bit per pin group at base + reg*4; "
            "bit 1 selects the function, 0 = GPIO")

    def __init__(self, linux):
        text = (linux / self.DRIVER).read_text()
        chips = _parse_pin_numbers(
            (linux / "include/dt-bindings/gpio/meson-gxl-gpio.h").read_text())
        if len(chips) != 2:
            sys.exit("meson-gxl-gpio.h: expected 2 gpio chips")
        self.sym = {0: chips[0], 1: chips[1]}
        pins = {}
        for name, body in re.findall(
                r"static const unsigned int (\w+)_pins\[\]\s*=\s*\{(.*?)\};",
                text, re.S):
            pins[name] = re.findall(r"\b([A-Z][A-Z0-9_]*)\b", body)
        self.groups = {}   # name -> (domain, reg, bit, [pin numbers])
        for domain, arr in ((1, "meson_gxl_periphs_groups"),
                            (0, "meson_gxl_aobus_groups")):
            body = _array_body(text, f"static const struct meson_pmx_group {arr}[]")
            for g, r, b in re.findall(r"GROUP\((\w+),\s*(\d+),\s*(\d+)\)", body):
                nums = [self.sym[domain][s] for s in pins.get(g, [])]
                self.groups[g] = (domain, int(r), int(b), nums)
        self.funcs = {}    # group -> [func names]
        for fname, body in re.findall(
                r"static const char \* const (\w+)_groups\[\] = \{(.*?)\};",
                text, re.S):
            for g in re.findall(r'"(\w+)"', body):
                self.funcs.setdefault(g, []).append(fname)

    def meta(self):
        return {"family": self.family, "driver": self.DRIVER, "note": self.NOTE,
                "bases": {d: f"0x{b:x}" for d, b in
                          (("aobus", self.BASES[0]), ("periphs", self.BASES[1]))}}

    # Datasheet audio tokens whose kernel group base name differs; every
    # other GXL token is the lowercased kernel group name, with bank
    # suffixes (_x/_z/_ao/...) resolved by pin membership in lookup().
    ALIAS = {
        "i2s_lr_clk_out": "i2s_out_lr_clk",
        "i2s_ao_clk_out": "i2s_out_ao_clk",
        "i2s_lr_clk_in": "i2s_in_lr_clk",
        "i2s_ao_clk_in": "i2s_in_ao_clk",
        "remote_output": "remote_input_ao",
    }

    def _base(self, token):
        t = token.lower()
        t = re.sub(r"^i2sout_", "i2s_out_", t)
        t = re.sub(r"^i2sin_", "i2s_in_", t)
        return self.ALIAS.get(t, t)

    def lookup(self, chip, line, token, name=None):
        t = self._base(token)
        dom = meson_domain(self.sym, chip, line, name, self.family)
        cands = [g for g, v in self.groups.items()
                 if v[0] == dom and line in v[3]
                 and (g == t or g.startswith(t + "_"))]
        if not cands:
            return None
        cands.sort(key=lambda g: (g != t, len(g)))
        grp = cands[0]
        domain, reg, bit, _ = self.groups[grp]
        return {"name": token, "group": grp,
                "funcs": sorted(self.funcs.get(grp, [])),
                "reg": f"0x{self.BASES[domain] + reg * 4:x}",
                "bit": bit, "width": 1, "value": 1}


class MesonG12aMux:
    """axg-pmx: 4-bit mux field per pin; value = the group's f in GROUP(grp, f).

    Field position (pinctrl-meson-axg-pmx.c meson_axg_pmx_set_mux):
    shift = pin - bank.first; pos = bank.offset + shift*4;
    reg = bank.reg + pos/32; bit = pos%32. Mux block bases (reg-names "mux"):
    periphs bank@40 reg 0x2c0 under the EE bus at 0xff634400 -> 0xff6346c0;
    aobus reg 0x14 under the AO bus at 0xff800000 -> 0xff800014
    (arch/arm64/boot/dts/amlogic/meson-g12-common.dtsi; SM1/A311D reuse the
    g12a pinctrl via meson-g12-common.dtsi)."""

    family = "meson-g12a"
    BASES = {0: 0xFF800014, 1: 0xFF6346C0}
    DRIVER = "drivers/pinctrl/meson/pinctrl-meson-g12a.c"
    NOTE = ("meson-axg-pmx: 4-bit mux field per pin at base + reg*4; the "
            "written value is the group's mux setting (0 = GPIO)")

    def __init__(self, linux):
        text = (linux / self.DRIVER).read_text()
        chips = _parse_pin_numbers(
            (linux / "include/dt-bindings/gpio/meson-g12a-gpio.h").read_text())
        if len(chips) != 2:
            sys.exit("meson-g12a-gpio.h: expected 2 gpio chips")
        self.sym = {0: chips[0], 1: chips[1]}
        self.banks = {}    # domain -> [(first, last, reg, off)]
        for domain, arr in ((1, "meson_g12a_periphs_pmx_banks"),
                            (0, "meson_g12a_aobus_pmx_banks")):
            body = _array_body(text, f"static const struct meson_pmx_bank {arr}[]")
            banks = []
            for first, last, r, o in re.findall(
                    r'BANK_PMX\("\w+",\s*(\w+),\s*(\w+),\s*(0x[0-9a-f]+),\s*(\d+)\)',
                    body):
                banks.append((self.sym[domain][first], self.sym[domain][last],
                              int(r, 16), int(o)))
            self.banks[domain] = banks
        pins = {}
        for name, body in re.findall(
                r"static const unsigned int (\w+)_pins\[\]\s*=\s*\{(.*?)\};",
                text, re.S):
            pins[name] = re.findall(r"\b([A-Z][A-Z0-9_]*)\b", body)
        self.groups = {}   # name -> (domain, f, [pin numbers])
        for domain, arr in ((1, "meson_g12a_periphs_groups"),
                            (0, "meson_g12a_aobus_groups")):
            body = _array_body(text, f"static const struct meson_pmx_group {arr}[]")
            for g, f in re.findall(r"GROUP\((\w+),\s*(\d+)\)", body):
                nums = [self.sym[domain][s] for s in pins.get(g, [])]
                self.groups[g] = (domain, int(f), nums)
        self.funcs = {}
        for fname, body in re.findall(
                r"static const char \* const (\w+)_groups\[\] = \{(.*?)\};",
                text, re.S):
            for g in re.findall(r'"(\w+)"', body):
                self.funcs.setdefault(g, []).append(fname)

    def meta(self):
        return {"family": self.family, "driver": self.DRIVER, "note": self.NOTE,
                "bases": {d: f"0x{b:x}" for d, b in
                          (("aobus", self.BASES[0]), ("periphs", self.BASES[1]))}}

    # Datasheet pad names -> kernel group base names (the kernel uses
    # controller-index naming); bank suffixes (_x/_z/_h/_a/...) resolved by
    # pin membership in lookup().
    def _base(self, token):
        t = token.lower()
        m = re.fullmatch(r"uart_ee_([abc])_(tx|rx|cts|rts)", t)
        if m:
            return f"uart_{m.group(1)}_{m.group(2)}"
        m = re.fullmatch(r"spi_([ab])_(mosi|miso|sclk|ss0)", t)
        if m:
            role = "clk" if m.group(2) == "sclk" else m.group(2)
            return f"spi{'0' if m.group(1) == 'a' else '1'}_{role}"
        m = re.fullmatch(r"i2c_ee_m([0-3])_(sda|scl)", t)
        if m:
            return f"i2c{m.group(1)}_{'sda' if m.group(2) == 'sda' else 'sck'}"
        m = re.fullmatch(r"i2c_ao_(m0|s0)_(sda|scl)", t)
        if m:
            role = "sda" if m.group(2) == "sda" else "sck"
            return (f"i2c_ao_{role}" if m.group(1) == "m0"
                    else f"i2c_ao_slave_{role}")
        m = re.fullmatch(r"tdm([abc])_d([0-3])", t)
        if m:
            return f"tdm_{m.group(1)}_dout{m.group(2)}"
        m = re.fullmatch(r"mclk_([01])", t)
        if m:
            return f"mclk{m.group(1)}"
        m = re.fullmatch(r"pwm([a-f])", t)
        if m:
            return f"pwm_{m.group(1)}"
        return {
            "pwmao_c": "pwm_ao_c",
            "ir_remote_out": "remote_ao_out",
            "ir_remote_in": "remote_ao_input",
            "hdmitx_scl": "hdmitx_sck",
        }.get(t, t)

    def lookup(self, chip, line, token, name=None):
        t = self._base(token)
        dom = meson_domain(self.sym, chip, line, name, self.family)
        cands = [g for g, v in self.groups.items()
                 if v[0] == dom and line in v[2]
                 and (g == t or g.startswith(t + "_"))]
        if not cands:
            return None
        cands.sort(key=lambda g: (g != t, len(g)))
        grp = cands[0]
        domain, fval, _ = self.groups[grp]
        for first, last, reg, off in self.banks[domain]:
            if first <= line <= last:
                pos = off + (line - first) * 4
                addr = self.BASES[domain] + (reg + pos // 32) * 4
                return {"name": token, "group": grp,
                        "funcs": sorted(self.funcs.get(grp, [])),
                        "reg": f"0x{addr:x}", "bit": pos % 32,
                        "width": 4, "value": fval}
        return None


class RockchipMux:
    """pinctrl-rockchip: per-bank iomux registers in the GRF.

    Offsets allocated at probe (rockchip_pinctrl_probe: grf_offs starts at
    grf_mux_offset, +8 per WIDTH_{2,3,4}BIT group else +4); field layout and
    recalced overrides from rockchip_pmux_get_mux/set_mux. RK3328 GRF base
    0xff100000 (arch/arm64/boot/dts/rockchip/rk3328.dtsi).

    The register and bit field come from the driver; the mux **value** cannot,
    because Rockchip DT carries mux indices without names. It comes from the
    TRM's GRF IOMUX register descriptions, extracted to
    rockchip/rk3328/gpio_pinmux.json by tools/gpio_extract.py in the internal
    repo (--rk-pinmux to point elsewhere).

    This used to be guessed from the function-name suffix ("_M<n> -> n+1, else
    1"), which is wrong wherever a pad has more than one alternate: on
    GPIO2_C2 the TRM gives i2s1_sclk=1, pdm_clkm0=2, tsp_d7m1=3, cif_data7m1=4,
    and rk3328.dtsi independently agrees (<2 RK_PC2 1>, <2 RK_PC2 2>,
    <2 RK_PC2 4>) -- the heuristic emitted 1, 1, 2, 1. A pin whose value is not
    in the extract now carries no value at all rather than a fabricated one."""

    family = "rockchip"
    BASE = 0xFF100000
    DRIVER = "drivers/pinctrl/pinctrl-rockchip.c"
    NOTE = ("pinctrl-rockchip GRF iomux: 2/3/4-bit field per pin; value 0 = "
            "GPIO, M0 = 1, M1 = 2, ...; flagged entries also write a "
            "secondary GRF route register")
    FLAGS = {"0": 0, "IOMUX_WIDTH_2BIT": 2, "IOMUX_WIDTH_3BIT": 3,
             "IOMUX_WIDTH_4BIT": 4}

    @staticmethod
    def canon(name):
        """Comparable mux name across the TRM and the LWT Desc vocabularies.

        cif_data7m1 (TRM) == CIF_D7_M1_d (map): DATA vs D, glued vs separated
        route marker, and a reset-pull suffix that is not part of the name.
        Route markers (M0/M1) stay -- they pick different mux values.
        """
        s = re.sub(r"[^A-Z0-9]", "", name.upper()).replace("DBG", "")
        s = re.sub(r"(?<=\d)[UDZ]$", "", s)
        return s.replace("DATA", "D")

    def __init__(self, linux, pinmux_json=None):
        self.trm = {}      # (chip, line) -> {canon name: value}
        if pinmux_json and Path(pinmux_json).is_file():
            doc = json.loads(Path(pinmux_json).read_text())
            for ball in doc.get("balls", []):
                m = re.match(r"^gpio(\d)_([a-d])(\d)$",
                             ball.get("reset_function", ""), re.I)
                if not m:
                    continue
                chip = int(m.group(1))
                line = (ord(m.group(2).upper()) - ord("A")) * 8 + int(m.group(3))
                self.trm[(chip, line)] = {
                    self.canon(x["signal_name"]): x.get("value")
                    for x in ball.get("mux", []) if x.get("value") is not None
                }

        text = (linux / self.DRIVER).read_text()
        body = _array_body(text, "static struct rockchip_pin_bank rk3328_pin_banks[]")
        self.banks = []    # (banknum, [4 flag values])
        for m in re.finditer(r"PIN_BANK_IOMUX_FLAGS\((\d+),\s*\d+,\s*\"(\w+)\""
                             r"(.*?)\)", body, re.S):
            flags = [self.FLAGS[t] for t in
                     re.findall(r"IOMUX_WIDTH_\dBIT|(?<![A-Z0-9_])0(?![xX0-9A-Za-z_])",
                                m.group(3))]
            if len(flags) != 4:
                sys.exit(f"rk3328 bank {m.group(1)}: cannot parse iomux flags")
            self.banks.append((int(m.group(1)), flags))
        self.banks.sort()
        offs = 0
        self.offs = {}     # (bank, group j) -> offset
        for banknum, flags in self.banks:
            for j, fl in enumerate(flags):
                self.offs[(banknum, j)] = offs
                offs += 8 if fl else 4
        # Scope the recalced overrides to RK3328's own table. The driver holds
        # one per SoC and several reuse the same (bank, pin) numbers, so a
        # file-wide scan let RK3308's gpio2c0 entry (0x50 = GRF_COM_IOMUX, the
        # uart-debug route select) overwrite RK3328's GPIO2_C0.
        recalced_body = _array_body(
            text, "static struct rockchip_mux_recalced_data rk3328_mux_recalced_data[]")
        self.recalced = {}  # (bank, pin) -> (reg, bit, mask)
        for entry in re.finditer(
                r"\.num = (\d+),\s*\.pin = (\d+),\s*\.reg = (0x[0-9a-f]+),\s*"
                r"\.bit = (\d+),\s*\.mask = (0x[0-9a-f]+)", recalced_body):
            self.recalced[(int(entry.group(1)), int(entry.group(2)))] = (
                int(entry.group(3), 16), int(entry.group(4)),
                int(entry.group(5), 16))
        self.routes = {}    # (bank, pin, mux) -> (reg, value, note)
        for m in re.finditer(r"RK_MUXROUTE_SAME\((\d+),\s*RK_P([A-D])(\d+),\s*"
                             r"(\d+),\s*(0x[0-9a-f]+),\s*(.*?)\)\s*,?\s*"
                             r"/\* (.*?) \*/", text):
            bank, port, pnum, mux, reg, val, note = m.groups()
            pinn = (ord(port) - ord("A")) * 8 + int(pnum)
            self.routes[(int(bank), pinn, int(mux))] = (
                int(reg, 16), self._bits(val), note)

    @staticmethod
    def _bits(val):
        total = 0
        for expr in val.split("|"):
            expr = expr.strip()
            m = re.fullmatch(r"BIT\(16 \+ (\d+)\)", expr)
            if m:
                total |= 1 << (16 + int(m.group(1)))
                continue
            m = re.fullmatch(r"BIT\((\d+)\)", expr)
            if m:
                total |= 1 << int(m.group(1))
                continue
            if expr.isdigit():
                total |= int(expr)
        return total

    def meta(self):
        return {"family": self.family, "driver": self.DRIVER, "note": self.NOTE,
                "bases": {"grf": f"0x{self.BASE:x}"}}

    def lookup(self, chip, line, token, name=None):
        tok = token.lower()
        m = re.match(r"^(.*?)(_m(\d+))?$", tok)
        base, _, msuf = m.groups()
        value = self.trm.get((chip, line), {}).get(self.canon(token))
        flags = dict(self.banks).get(chip)
        if flags is None:
            return None
        iomux = line // 8
        reg = self.offs[(chip, iomux)]
        width = flags[iomux]
        if width == 4:
            if line % 8 >= 4:
                reg += 4
            bit, mask = (line % 4) * 4, 0xF
        elif width == 3:
            if line % 8 >= 5:
                reg += 4
            bit, mask = (line % 8 % 5) * 3, 0x7
        else:
            bit, mask = (line % 8) * 2, 0x3
        if (chip, line) in self.recalced:
            reg, bit, mask = self.recalced[(chip, line)]
        entry = {"name": token, "group": base, "funcs": [],
                 "reg": f"0x{self.BASE + reg:x}", "bit": bit,
                 "width": mask.bit_length()}
        if value is not None:
            entry["value"] = value
        route = self.routes.get((chip, line, value))
        if route:
            entry["route"] = {"reg": f"0x{self.BASE + route[0]:x}",
                              "value": route[1], "note": route[2]}
        return entry


class Rk3399Mux:
    """RK3399 iomux, read from the TRM's own GRF register tables.

    No driver parsing here, unlike RK3328: the RK3399 TRM states the register,
    its absolute address, and the field per ball outright, and the extract in
    rockchip/rk3399/gpio_pinmux{,_pmu}.json carries them. Two syscons, because
    the SoC has two -- PMUGRF at 0xff320000 owns GPIO0 and GPIO1, GRF at
    0xff770000 owns GPIO2 through GPIO4 -- and the extract of each states its
    own addresses, so nothing here needs to know which base applies.

    The field belongs to the BALL, so it is known for every function on that
    pad. The VALUE belongs to the function, and is emitted only when the TRM's
    name and the map's name are recognisably the same signal.
    """

    family = "rockchip"
    NOTE = ("RK3399 GRF/PMUGRF iomux: 2-bit field per pin, value 0 = GPIO; "
            "register, address and field from the TRM's own tables")

    @staticmethod
    def canon(name):
        """Comparable name across the TRM and the LWT Desc vocabularies.

        Rockchip glues the reference design's CONSUMER onto the block name --
        i2c2tp_scl (touch panel), uart0bt_sin, spi2tpm_rxd, uart3gps_ctsn -- so
        the TRM records who Rockchip expected to wire there while the board map
        records only which controller it is. The consumer is not part of the
        function. The reset pull rides along as a lowercase _u/_d/_z suffix and
        has to go before case is thrown away, or SPI2_TXD loses its D too.
        """
        s = re.sub(r"_[udz]$", "", name)
        parts = s.split("_")
        # The block name may itself contain a digit -- I2C6TPM is i2c6 + tpm,
        # not i + 2 + ... -- so the split is at the LAST digit, not after a run
        # of letters. Only the first underscore-part is touched, which keeps
        # SPI2_TXD's TXD out of reach.
        parts[0] = re.sub(r"^(.*\d)[A-Za-z]{2,}$", r"\1", parts[0])
        s = re.sub(r"[^A-Z0-9]", "", "_".join(parts).upper())
        return s.replace("DBG", "").replace("DATA", "D")

    def __init__(self, docs):
        self.pads = {}     # (chip, line) -> (field dict, {canon name: value})
        for name in ("gpio_pinmux.json", "gpio_pinmux_pmu.json"):
            path = Path(docs) / "rockchip/rk3399" / name
            if not path.is_file():
                continue
            for ball in json.loads(path.read_text()).get("balls", []):
                m = re.match(r"^gpio(\d)_([a-d])(\d)$",
                             ball.get("reset_function", ""), re.I)
                mux = ball.get("mux") or []
                if not m or not mux:
                    continue
                chip = int(m.group(1))
                line = (ord(m.group(2).upper()) - ord("A")) * 8 + int(m.group(3))
                field = {"reg": mux[0].get("address"),
                         "register": mux[0].get("register"),
                         "bit": mux[0].get("bit"),
                         "width": mux[0].get("width")}
                self.pads[(chip, line)] = (
                    field,
                    {self.canon(x["signal_name"]): x.get("value")
                     for x in mux if x.get("value") is not None})

    def meta(self):
        return {"family": self.family, "source": "rk3399 TRM extract",
                "note": self.NOTE,
                "bases": {"grf": "0xff770000", "pmugrf": "0xff320000"}}

    def lookup(self, chip, line, token, name=None):
        found = self.pads.get((chip, line))
        if not found:
            return None
        field, values = found
        entry = {"name": token, "group": token.lower(), "funcs": []}
        for k, v in field.items():
            if v is not None:
                entry[k] = v
        value = values.get(self.canon(token))
        if value is not None:
            entry["value"] = value
        return entry


class SunxiMux:
    """sunxi pinctrl: 4-bit cfg field per pin, function table per pin in the
    driver. PIO base 0x01c20800, bank stride 0x24, 8 pins per cfg register
    (arch/arm64/boot/dts/allwinner/sunxi-h3-h5.dtsi, pinctrl-sunxi.h)."""

    family = "sunxi"
    BASE = 0x01C20800
    NOTE = ("sunxi PIO: 4-bit mux field per pin at base + bank*0x24 + "
            "(pin%32)/8*4; value from the per-pin function table")
    ALIAS = {"twi": "i2c", "pcm": "i2s", "nand": "nand0"}

    def __init__(self, linux, variant):
        self.driver = f"drivers/pinctrl/sunxi/pinctrl-sun{variant}.c"
        text = (linux / self.driver).read_text()
        self.pins = {}     # global pin number -> {func name: value}
        spans = list(re.finditer(
            r"SUNXI_PIN\(SUNXI_PINCTRL_PIN\(([A-G]),\s*(\d+)\),", text))
        for i, m in enumerate(spans):
            end = spans[i + 1].start() if i + 1 < len(spans) else len(text)
            body = text[m.end():end]
            glo = (ord(m.group(1)) - ord("A")) * 32 + int(m.group(2))
            funcs = {name: int(val, 16) for val, name in
                     re.findall(r"SUNXI_FUNCTION\(0x([0-9a-f]),\s*\"(\w+)\"\)", body)}
            for val in re.findall(r"SUNXI_FUNCTION_IRQ_BANK\(0x([0-9a-f]),", body):
                funcs["irq"] = int(val, 16)
            self.pins[glo] = funcs

    def meta(self):
        return {"family": self.family, "driver": self.driver, "note": self.NOTE,
                "bases": {"pio": f"0x{self.BASE:x}"}}

    def _match(self, funcs, token):
        t = token.lower()
        if re.fullmatch(r"p[a-g]_eint\d+", t):
            return ("irq", funcs["irq"]) if "irq" in funcs else (None, None)
        parts = t.split("_")
        for k in range(len(parts), 0, -1):
            cand = "_".join(parts[:k])
            first, sep, rest = cand.partition("_")
            names = {cand}
            for pre, rep in self.ALIAS.items():
                if first.startswith(pre):
                    names.add(rep + first[len(pre):] + (sep + rest if sep else ""))
            for name in names:
                if name in funcs:
                    return name, funcs[name]
        return None, None

    def lookup(self, chip, line, token, name=None):
        funcs = self.pins.get(line)
        if not funcs:
            return None
        name, value = self._match(funcs, token)
        if name is None:
            return None
        reg = self.BASE + (line // 32) * 0x24 + (line % 32 // 8) * 4
        return {"name": token, "group": name, "funcs": [name],
                "reg": f"0x{reg:x}", "bit": (line % 8) * 4,
                "width": 4, "value": value}


# ---------------------------------------------------------------------------
# Per-pad electrical characteristics
# ---------------------------------------------------------------------------
#
# One class per SoC in ELEC_FOR_SOC, with a two-method contract:
#
#     board()             -> the board-level `electrical` block, or None
#     lookup(chip, line)  -> the per-pad dict for that GPIO line, or None
#
# The frontend reads whatever those two produce, so another SoC's extract drops
# in by adding a class here -- no JSON reshaping and no frontend change. Every
# field is optional: a pad the datasheet does not describe emits nothing at
# all, because a blank cell is honest and a default is a fabrication.

class Rk3328Electrical:
    """RK3328 pad electricals, from the internal datasheet extracts.

    Two files, because the two facts live in two datasheet tables:

      rockchip/rk3328/gpio_pinmux.json            Table 3-2 (VCCIO rails) +
                                                  Table 3-3 (DC characteristics)
                                                  + per-ball `power_domain`,
                                                  which TRM part 1 names for
                                                  only 30 of the 70 pads
      rockchip/rk3328/gpio_pinmux_datasheet.json  Table 2-3, per-ball direction,
                                                  state + pull at reset, drive
                                                  strength, interrupt capability

    Both key a pad by its reset function (`gpio1_c7`), which is exactly the
    (gpiochip, line) pair the LWT map carries, so no ball-location matching is
    needed.
    """

    # Datasheet Table 2-5 "IO Type List", quoted. Type A is the crystal pair,
    # so nothing on a header is type A; every digital GPIO pad is type B.
    PAD_TYPES = {
        "A": {"desc": "Crystal Oscillator with high enable",
              "pins": "XIN24M/XOUT24M"},
        "B": {"desc": "Tri-state output pad with input, which pull-up/"
                      "pull-down, slew rate and drive strength is configurable",
              "pins": "Pad of digital GPIO"},
    }
    # Units for the Table 3-3 symbols; the extract carries the numbers only.
    UNITS = {"vil": "V", "vih": "V", "vol": "V", "voh": "V",
             "Vtr_pos": "V", "Vtr_neg": "V", "rpu": "kΩ", "rpd": "kΩ"}

    @staticmethod
    def _key(reset_function):
        m = re.match(r"^gpio(\d)_([a-d])(\d)$", reset_function or "", re.I)
        if not m:
            return None
        return (int(m.group(1)),
                (ord(m.group(2).upper()) - ord("A")) * 8 + int(m.group(3)))

    def __init__(self, pinmux_json, datasheet_json):
        self.pads = {}          # (chip, line) -> per-pad dict
        self.pad_source = ""
        self._board = None
        pm = Path(pinmux_json) if pinmux_json else None
        ds = Path(datasheet_json) if datasheet_json else None

        if ds and ds.is_file():
            doc = json.loads(ds.read_text())
            for ball in doc.get("balls", []):
                k = self._key(ball.get("reset_function"))
                if k is None:
                    continue
                entry = {"pad_type": "B"}
                for src, dst in (("direction", "direction"),
                                 ("io_reset", "io_reset"),
                                 ("pupd_reset", "pupd_reset"),
                                 ("drive", "drive")):
                    if ball.get(src):
                        entry[dst] = ball[src]
                if ball.get("interrupt_capable"):
                    entry["interrupt"] = True
                self.pads[k] = entry
            # One provenance string for the whole table, not a copy per pad.
            self.pad_source = (f"{doc.get('source_pdf', '')} "
                               f"{doc.get('table', '')}").strip()

        if pm and pm.is_file():
            doc = json.loads(pm.read_text())
            for ball in doc.get("balls", []):
                k = self._key(ball.get("reset_function"))
                if k is None or not ball.get("power_domain"):
                    continue
                self.pads.setdefault(k, {})["domain"] = ball["power_domain"]
            elec = doc.get("electrical")
            if elec:
                self._board = dict(elec)
                self._board["units"] = self.UNITS
                self._board["pad_types"] = self.PAD_TYPES
                if self.pad_source:
                    self._board["pad_source"] = self.pad_source

    def board(self):
        return self._board

    def lookup(self, chip, line, name=None):
        return self.pads.get((chip, line))


class Rk3399Electrical:
    """RK3399 pad electricals, from the internal datasheet extracts.

    Same two-file split as RK3328 and for the same reason -- the TRM owns the
    mux, the datasheet owns the pad columns:

      rockchip/rk3399/gpio_pinmux.json            §2.7 (which modes each IO
                                                  domain supports) + Table 3-2
                                                  (rail min/typ/max) + Table
                                                  3-3 (DC characteristics)
      rockchip/rk3399/gpio_pinmux_datasheet.json  Table 2-3, per-ball
                                                  direction, state + pull at
                                                  reset, drive strength,
                                                  interrupt capability

    Three things differ from RK3328, all of them the document's doing:

    1. THREE supply modes, not two -- @3.3V, @1.8V and @3.0V each get their own
       Table 3-3 block, because APIO1 is 3.3 V-only while APIO2/4/5, PMUIO2 and
       SDMMC0 switch between 1.8 V and 3.0 V (never 3.3 V).
    2. No IO type list. RK3328 Table 2-5 enumerates pad cell types A/B; RK3399
       has no counterpart (its Table 2-5 is the PCIe pin description), so no
       `pad_type` is emitted and the panel shows no IO-type row rather than
       inventing a letter.
    3. NO per-pad power domain, anywhere. RK3328's domains come from the TRM
       naming the rail inside its pad cell strings (`...GPIO3B1vccio6`); RK3399
       does not do that -- `grep -i apio` over the whole TRM returns 12 lines,
       none of them a pad cell -- Table 2-3 has no domain column, and Table 2-2
       lists the power BALLS per group (APIO1_VDD is ball J23), not the signal
       pads that group feeds. So `domain` is never set, the panel renders it as
       an em dash, and the thresholds below stay unbound. The alternative is
       guessing which of APIO1/2/3/4/5 a header pin sits in, and picking the
       wrong rail puts a wrong Vih on a page people wire hardware from.
    """

    UNITS = {"vil": "V", "vih": "V", "vol": "V", "voh": "V",
             "Vtr_pos": "V", "Vtr_neg": "V", "rpu": "kΩ", "rpd": "kΩ"}

    DC_NOTE = (
        "RK3399 publishes the thresholds per IO supply mode (Table 3-3) but "
        "never states which supply rail a given pad sits on — Table 2-3 has no "
        "power-domain column, and Table 2-2 lists each group's power balls "
        "rather than its signal pads. So the three operating points are on "
        "record for the part, and binding one to this pin would be a guess."
    )

    @staticmethod
    def _key(reset_function):
        m = re.match(r"^gpio(\d)_([a-d])(\d)$", reset_function or "", re.I)
        if not m:
            return None
        return (int(m.group(1)),
                (ord(m.group(2).upper()) - ord("A")) * 8 + int(m.group(3)))

    def __init__(self, pinmux_json, datasheet_json):
        self.pads = {}
        self.pad_source = ""
        self._board = None
        pm = Path(pinmux_json) if pinmux_json else None
        ds = Path(datasheet_json) if datasheet_json else None

        if ds and ds.is_file():
            doc = json.loads(ds.read_text())
            for ball in doc.get("balls", []):
                k = self._key(ball.get("reset_function"))
                if k is None:
                    continue
                entry = {}
                for src, dst in (("direction", "direction"),
                                 ("io_reset", "io_reset"),
                                 ("pupd_reset", "pupd_reset"),
                                 ("drive", "drive")):
                    if ball.get(src):
                        entry[dst] = ball[src]
                if ball.get("interrupt_capable") is not None:
                    entry["interrupt"] = bool(ball["interrupt_capable"])
                if entry:
                    self.pads[k] = entry
            self.pad_source = (f"{doc.get('source_pdf', '')} "
                               f"{doc.get('table', '')}").strip()

        if pm and pm.is_file():
            elec = json.loads(pm.read_text()).get("electrical")
            if elec:
                self._board = dict(elec)
                self._board["units"] = self.UNITS
                self._board["dc_note"] = self.DC_NOTE
                if self.pad_source:
                    self._board["pad_source"] = self.pad_source

    def board(self):
        return self._board

    def lookup(self, chip, line, name=None):
        return self.pads.get((chip, line))


class AmlogicElectrical:
    """Amlogic pad electricals, from amlogic/<family>/<soc>/gpio_electrical.json.

    Keyed by pad NAME (GPIOX_8), not (chip, line): the Amlogic source is a
    `PIN` line in a text extract, which names the pad and never numbers it.

    It carries four facts per pad -- cell type, reset pull, IO power domain,
    and (GXL only) drive strength baked into the cell name. There is no
    threshold table anywhere in these extracts, so `dc` stays empty and the
    board block says so rather than leaving the reader to assume the RK3328
    numbers generalise.
    """

    # The cell names that appear in the extracts, described in the terms the
    # extracts use. OD5V matters: GPIOH_4..7 on A311D/S905D3 are open-drain
    # and 5 V-tolerant while the GPIOX pads beside them on the same header are
    # push-pull, which changes what you may wire to them.
    PAD_TYPES = {
        "DIO": {"desc": "Push-pull digital IO"},
        "OD5V": {"desc": "Open-drain, 5 V-tolerant — needs an external "
                         "pull-up, and will not drive high on its own"},
    }

    # Datasheet row -> the site's symbol, per VDDIO mode. GXL states one set
    # for both modes; G12/SM1 states two, and they are NOT the same shape --
    # see DC_NOTE.
    ROWS_BY_SUPPLY = {
        "3.3": {"vih": ("ViH_VDDIO_3V3", "ViH"), "vil": ("ViL_VDDIO_3V3", "ViL"),
                "voh": ("VOH",), "vol": ("VOL",),
                "rpu": ("RPU", "RPU/PD"), "rpd": ("RPD", "RPU/PD")},
        "1.8": {"vih": ("ViH_VDDIO_1V8", "ViH"), "vil": ("ViL_VDDIO_1V8", "ViL"),
                "voh": ("VOH",), "vol": ("VOL",),
                "rpu": ("RPU", "RPU/PD"), "rpd": ("RPD", "RPU/PD")},
    }

    # Why the numbers look unlike every other vendor's on this site.
    DC_NOTE = (
        "Thresholds are stated against IOVREF, a separate 1.8 V reference rail, "
        "not as a fraction of the pad's own VDDIO. On a 3.3 V G12/SM1 pad that "
        "puts Vih min near 2.17 V rather than the 2.31 V a 0.7×VDDIO rule would "
        "predict. Every VDDIO domain is LV/HV selectable, so which column applies "
        "depends on what the board feeds that rail."
    )

    def __init__(self, path):
        self.pads = {}
        self._board = None
        p = Path(path) if path else None
        if not p or not p.is_file():
            return
        doc = json.loads(p.read_text())
        elec = doc.get("electrical") or {}
        dc_families = elec.get("dc") or {}

        # buffer type -> the dc family that describes it, from the extract's
        # own applies_to_buffer_types rather than by guessing at the name.
        family_of = {}
        for family, rows in dc_families.items():
            for bt in rows.get("applies_to_buffer_types", []):
                family_of[bt.replace(" ", "").upper()] = family

        pad_types = {}
        for pad in doc.get("pads", []):
            name = self._norm(pad.get("ball_name"))
            if not name:
                continue
            entry = {}
            cell = (pad.get("buffer_type") or "").replace(" ", "")
            if cell:
                entry["pad_type"] = cell
                pad_types.setdefault(cell, {"desc": self._describe(cell.upper())})
                if cell.upper() in family_of:
                    entry["dc_family"] = family_of[cell.upper()]
            for src, dst in (("direction", "direction"),
                             ("pupd_reset", "pupd_reset"),
                             ("drive", "drive"),
                             ("power_domain", "domain")):
                if pad.get(src):
                    entry[dst] = pad[src]
            if pad.get("open_drain"):
                entry["open_drain"] = True
            if pad.get("tolerant_5v"):
                entry["tolerant_5v"] = True
            self.pads[name] = entry

        # Every VDDIO domain is the same silicon rail run in LV or HV mode, so
        # each one offers both operating points rather than a fixed voltage.
        roc = elec.get("recommended_operating_conditions") or {}
        lv, hv = roc.get("VDDIO_LV"), roc.get("VDDIO_HV")
        rails = {}
        if lv or hv:
            for domain in sorted({p.get("power_domain") for p in doc.get("pads", [])
                                  if (p.get("power_domain") or "").startswith("VDDIO")}):
                rail = {"select": [s for s, r in (("3.3", hv), ("1.8", lv)) if r]}
                if hv:
                    rail["3.3"] = {k: hv.get(k, "") for k in ("min", "typ", "max")}
                if lv:
                    rail["1.8"] = {k: lv.get(k, "") for k in ("min", "typ", "max")}
                rails[domain] = rail

        dc, units = {}, {}
        for family, rows in dc_families.items():
            dc[family] = {}
            for supply, mapping in self.ROWS_BY_SUPPLY.items():
                table = {}
                for sym, candidates in mapping.items():
                    row = next((rows[c] for c in candidates if isinstance(rows.get(c), dict)),
                               None)
                    if not row:
                        continue
                    table[sym] = {k: row.get(k, "") for k in ("min", "typ", "max")}
                    if row.get("unit"):
                        units[sym] = row["unit"].replace("ohm", "Ω")
                if table:
                    dc[family][supply] = table

        self._board = {
            "source": elec.get("source", "") or doc.get("source_pdf", ""),
            "pad_types": pad_types or self.PAD_TYPES,
            "rails": rails,
            "dc": dc,
            "units": units,
            "dc_note": self.DC_NOTE,
        }

    @staticmethod
    def _norm(name):
        """Map names carry footnote markers the datasheet does not: the Potato
        map spells these GPIOAO_8* and TEST_N**."""
        return re.sub(r"[^A-Z0-9_]", "", (name or "").upper())

    @staticmethod
    def _describe(cell):
        if cell.startswith("OD"):
            return ("Open-drain" + (", 5 V-tolerant" if "5V" in cell else "") +
                    " — needs an external pull-up, and will not drive high on its own")
        if cell == "DIO":
            return "Push-pull digital IO, drive strength register-selectable"
        m = re.match(r"^DIO_(\d+)MA$", cell)
        if m:
            return f"Push-pull digital IO, drive fixed at {m.group(1)} mA by the pad cell"
        return "Digital IO"

    def board(self):
        return self._board

    def lookup(self, chip, line, name=None):
        return self.pads.get(self._norm(name))


class SunxiElectrical:
    """H3 / H5 pad electricals, from allwinner/<soc>/gpio_electrical.json.

    Also keyed by pad name (PA12). The DC table is stated once, as fractions
    of the pad's OWN rail ("0.7 * VCC-IO"), so one set of thresholds is
    published per SoC and read against whichever rail supplies the pad -- the
    opposite of RK3328, where each rail voltage has its own numbers. The rail
    key is therefore a name (VCC-PC), not a voltage.

    H3 names a rail per port BLOCK -- a POWER row ends the block (A -> VCC_IO,
    D -> VCC_PD, G -> VCC_PG) -- where H5 names one per pad. The extract
    resolves that row onto the block's pads, so H3 pads do carry a domain;
    ports C/E/F/L end in no POWER row and H3 has no VCC_PC symbol, so those
    stay empty rather than borrowed from H5. On all-h3-cc-h3 that is 26 of 30
    header pins, the 4 gaps being PC0-PC3.
    """

    DC_MAP = {"VIH": "vih", "VIL": "vil", "VOH": "voh", "VOL": "vol",
              "RPU": "rpu", "RPD": "rpd"}

    def __init__(self, path):
        self.pads = {}
        self._board = None
        p = Path(path) if path else None
        if not p or not p.is_file():
            return
        doc = json.loads(p.read_text())
        elec = doc.get("electrical") or {}

        rails, units = {}, {}
        dc_rows = {}
        for sym, entries in (elec.get("dc") or {}).items():
            key = self.DC_MAP.get(sym)
            if not key or not entries:
                continue
            row = entries[0]
            dc_rows[key] = {"min": row.get("min", ""), "typ": row.get("typ", ""),
                            "max": row.get("max", "")}
            units[key] = row.get("unit", "")

        for name, entries in (elec.get("recommended_operating_conditions") or {}).items():
            if not name.upper().startswith("VCC") or not entries:
                continue
            row = entries[0]
            rails[name] = {"select": [name], "min": row.get("min", ""),
                           "typ": row.get("typ", ""), "max": row.get("max", ""),
                           "unit": row.get("unit", "V")}

        for pad in doc.get("pads", []):
            name = (pad.get("ball_name") or "").upper()
            if not re.fullmatch(r"P[A-Z]\d+", name):
                continue          # DRAM/analog balls are not header pads
            entry = {}
            if pad.get("direction"):
                entry["direction"] = pad["direction"]
            if pad.get("reset_state"):
                entry["io_reset"] = pad["reset_state"]
            if pad.get("pull_capability") and pad["pull_capability"] != "NA":
                # capability, NOT the state at reset -- kept as its own field
                entry["pull_capability"] = pad["pull_capability"]
            if pad.get("drive_ma") and pad["drive_ma"] != "NA":
                entry["drive"] = f"{pad['drive_ma']} mA"
            if pad.get("power_supply"):
                entry["domain"] = pad["power_supply"]
            if entry:
                self.pads[name] = entry

        self._board = {
            "source": elec.get("source", ""),
            "applies_to": elec.get("applies_to", ""),
            "rails": rails,
            "dc": {name: dc_rows for name in rails} if dc_rows else {},
            "units": units,
            "pad_types": {},
        }

    def board(self):
        return self._board

    def lookup(self, chip, line, name=None):
        # The map carries the datasheet's footnote markers on the pad name --
        # TEST_N** -- and the extract keys on the name without them, so an
        # asterisked pad silently had no electrical data at all. Same class of
        # miss as the one that hid I2SOUT_CH23 from the mux audit.
        return self.pads.get((name or "").upper().rstrip("*"))


# What the BOARD actually feeds each selectable VCCIO rail. The SoC datasheet
# says vccio4 and vccio6 may be 3.3 V or 1.8 V; only the schematic says which,
# and the two Renegade revisions differ -- which is exactly why this is keyed
# by board and not by SoC.
#
#   V1 (roc-rk3328-cc)     BUCK4 VCC_IO 3.3 V -> VCCIO_PMU, 1, 3, 4, 5, 6
#   V2 (roc-rk3328-cc-v2)  BUCK4 drops VCCIO4/6; LDO1 VCC_18 1.8 V takes them
#
# Source: rockchip/rk3328/schematics/rk3328-v1-v2-differences.md (PMIC rail
# table + "VCCIO4 and VCCIO6 must be the same voltage level"). vccio2 is left
# out on purpose: no rail assignment for it was read, and a guess here puts a
# wrong Vih on a page people wire hardware from.
BOARD_RAILS = {
    "roc-rk3328-cc": {
        "vccio_pmu": "3.3", "vccio1": "3.3", "vccio3": "3.3",
        "vccio4": "3.3", "vccio5": "3.3", "vccio6": "3.3",
    },
    "roc-rk3328-cc-v2": {
        "vccio_pmu": "3.3", "vccio1": "3.3", "vccio3": "3.3",
        "vccio4": "1.8", "vccio5": "3.3", "vccio6": "1.8",
    },
}

ELEC_FOR_SOC = {
    "RK3328": lambda args: Rk3328Electrical(args.rk_pinmux, args.rk_datasheet),
    "RK3399": lambda args: Rk3399Electrical(
        Path(args.docs_repo) / "rockchip/rk3399/gpio_pinmux.json",
        Path(args.docs_repo) / "rockchip/rk3399/gpio_pinmux_datasheet.json"),
    "S905X": lambda args: AmlogicElectrical(Path(args.docs_repo) / "amlogic/gxl/s905x/gpio_electrical.json"),
    "S805X": lambda args: AmlogicElectrical(Path(args.docs_repo) / "amlogic/gxl/s805x/gpio_electrical.json"),
    "A311D": lambda args: AmlogicElectrical(Path(args.docs_repo) / "amlogic/g12sm1/a311d/gpio_electrical.json"),
    "S905D3": lambda args: AmlogicElectrical(Path(args.docs_repo) / "amlogic/g12sm1/s905d3/gpio_electrical.json"),
    "H3": lambda args: SunxiElectrical(Path(args.docs_repo) / "allwinner/h3/gpio_electrical.json"),
    "H5": lambda args: SunxiElectrical(Path(args.docs_repo) / "allwinner/h5/gpio_electrical.json"),
}

# Analog header pins. The LWT map's Chip column says ADC or DAC (Renegade J21
# SARADC_IN0/IN1, La Frite 9J5 LOLN/LORN): those pads are not digital GPIO, so
# the digital thresholds and the pull/drive controls simply do not apply to
# them and the panel must not read as if they did.
ANALOG_NOTE = {
    "ADC": "Analog input to the SoC's SAR ADC — not a digital GPIO pad, so the "
           "digital thresholds, pull and drive settings do not apply.",
    "DAC": "Analog output from the SoC's audio DAC — not a digital GPIO pad, so "
           "the digital thresholds, pull and drive settings do not apply.",
}


MUX_FOR_SOC = {
    "S905X": lambda linux, rk_json, docs: MesonGxlMux(linux),
    "S805X": lambda linux, rk_json, docs: MesonGxlMux(linux),
    "A311D": lambda linux, rk_json, docs: MesonG12aMux(linux),
    "S905D3": lambda linux, rk_json, docs: MesonG12aMux(linux),
    "RK3328": lambda linux, rk_json, docs: RockchipMux(linux, rk_json),
    "RK3399": lambda linux, rk_json, docs: Rk3399Mux(docs),
    "H3": lambda linux, rk_json, docs: SunxiMux(linux, "8i-h3"),
    "H5": lambda linux, rk_json, docs: SunxiMux(linux, "50i-h5"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lwt", default=str(REPO_ROOT.parent / "libretech-wiring-tool"),
                    help="path to libretech-wiring-tool checkout")
    ap.add_argument("--linux", default=str(REPO_ROOT.parent / "libretech-builder" / "linux"),
                    help="path to libretech-builder/linux checkout (pinctrl cross-reference)")
    ap.add_argument("--out", default=str(REPO_ROOT / "data"),
                    help="output directory (default: data/; every *.json in it is replaced)")
    ap.add_argument("--docs-repo", default=str(Path.home() / "git" / "claude"),
                    help="internal hardware-documentation repo holding the "
                         "datasheet extracts (per-SoC gpio_electrical.json)")
    ap.add_argument("--rk-pinmux",
                    default=str(Path.home() / "git" / "claude" / "rockchip" /
                                "rk3328" / "gpio_pinmux.json"),
                    help="RK3328 TRM mux extract (tools/gpio_extract.py --soc "
                         "rk3328); supplies mux values the kernel cannot")
    ap.add_argument("--rk-datasheet",
                    default=str(Path.home() / "git" / "claude" / "rockchip" /
                                "rk3328" / "gpio_pinmux_datasheet.json"),
                    help="RK3328 datasheet Table 2-3 extract; supplies per-pad "
                         "direction, reset state/pull, drive and interrupt")
    ap.add_argument("--allow-unplaced", action="store_true",
                    help="emit a board PCB_LAYOUT names even when its layout "
                         "source cannot be read here (e.g. no `unrar` for the "
                         "fab packages). Off by default: the board file would "
                         "otherwise be rewritten WITHOUT its layout block and "
                         "nothing in the output would say so")
    args = ap.parse_args()
    lwt = Path(args.lwt)
    linux = Path(args.linux)
    rk_pinmux = args.rk_pinmux

    out = Path(args.out)

    # Nothing is written until every board has been built. Each sys.exit in this
    # generator -- an unmapped Chip value, an arrangement naming a header the
    # board does not have, a driver the parser cannot read -- is a refusal to
    # emit wrong data, and a refusal that has already deleted half of data/ is
    # not a refusal. Buffering makes the whole run atomic for free.
    written = {}

    mux_cache = {}
    elec_cache = {}
    ds_mux = DatasheetMux(args.docs_repo)
    unmatched = []
    unbound = []
    index = []
    elec_stats = {}
    for board, (model, name, soc, vendor, status) in sorted(BOARDS.items()):
        path = lwt / "libre-computer" / board / "gpio.map"
        if not path.is_file():
            sys.exit(f"missing {path}")
        headers = parse_map(path, board)

        factory = MUX_FOR_SOC[soc]
        if soc not in mux_cache:
            mux_cache[soc] = factory(linux, rk_pinmux, Path(args.docs_repo))
        mux = mux_cache[soc]
        meta = mux.meta()

        if soc not in elec_cache:
            factory = ELEC_FOR_SOC.get(soc)
            elec_cache[soc] = factory(args) if factory else None
        elec = elec_cache[soc]

        n_gpio = n_elec = n_domain = n_analog = 0
        for h in headers:
            for p in h["pins"]:
                if p["type"] in ANALOG_NOTE:
                    p["elec"] = {"pad_type": "analog",
                                 "note": ANALOG_NOTE[p["type"]]}
                    n_analog += 1
                if p["type"] != "gpio":
                    continue
                n_gpio += 1
                if elec:
                    e = elec.lookup(p["chip"], p["line"], p["name"])
                    if e:
                        p["elec"] = e
                        n_elec += 1
                        if e.get("domain"):
                            n_domain += 1
                muxes = []
                for token in p["funcs"]:
                    entry = mux.lookup(p["chip"], p["line"], token, p["name"])
                    if entry is None:
                        # The driver models a subset of the silicon, so a real
                        # function it never gained a group for arrives here with
                        # no way to select it. The vendor's own table has the
                        # register, field and value; prefer having the answer
                        # from the datasheet over rendering a bare name.
                        entry = ds_mux.lookup(board, p["name"], token)
                    if entry is None:
                        unmatched.append(f"{board} pin {p['pin']}: {token}")
                        continue
                    muxes.append(entry)
                if muxes:
                    p["muxes"] = muxes

        # One HEADER POSITION, one entry -- even when the board ties two SoC
        # balls to it. Renegade J1 pin 33 is GPIO2_C0 (ball V15) and GPIO2_C1
        # (ball P18) shorted together as the shared I2S1 LRCK, and the map has
        # to spell that as two rows because its schema is one line per GPIO
        # line. Two rows is a fact about the map, not about the connector, and
        # rendering them as two stacked pins says the header has 41 positions
        # when it has 40.
        #
        # The merge happens AFTER mux resolution because each line's muxes have
        # to be looked up against ITS OWN chip/line -- GPIO2_C1's SPDIF_TX_M1
        # is not reachable through GPIO2_C0's register field.
        for h in headers:
            merged, by_pin, origname = [], {}, {}
            for p in h["pins"]:
                first = by_pin.get(p["pin"])
                if first is None:
                    by_pin[p["pin"]] = p
                    origname[p["pin"]] = p["name"]
                    merged.append(p)
                    continue
                # Once a position carries two lines, every mux on it has to say
                # WHICH one it belongs to -- otherwise the list is seven
                # functions and no way to tell that I2S1_LRCK_TX needs line 17
                # while I2S1_LRCK_RX needs line 16. Tagged only here, so an
                # ordinary pin carries no redundant field.
                for m in first.get("muxes") or []:
                    m.setdefault("owner", origname[p["pin"]])
                for m in p.get("muxes") or []:
                    m.setdefault("owner", p["name"])
                # Both balls are real and both must be configured to use the
                # pin, so nothing is dropped -- the second line moves into
                # `also`, and the names and balls read as the pair they are.
                first.setdefault("also", []).append(
                    {k: p[k] for k in ("chip", "line", "sysfs", "name", "pad",
                                       "ref") if p.get(k) is not None})
                first["name"] = f"{first['name']}/{p['name']}"
                first["pad"] = f"{first['pad']}/{p['pad']}"
                for f in p["funcs"]:
                    if f not in first["funcs"]:
                        first["funcs"].append(f)
                if p.get("muxes"):
                    first.setdefault("muxes", []).extend(p["muxes"])
            h["pins"] = merged

        headers = order_headers(headers)
        npins = sum(len(h["pins"]) for h in headers)
        doc = {
            "id": board, "model": model, "name": name, "soc": soc,
            "vendor": vendor, "status": status, "mux": meta, "headers": headers,
        }
        # Thresholds travel with the pins that reference them, so a board file
        # is self-contained: the panel resolves a pad's power domain against
        # this block without a second fetch.
        if elec and elec.board():
            doc["electrical"] = elec.board()
            if BOARD_RAILS.get(board):
                doc["electrical"]["board_rails"] = BOARD_RAILS[board]
        # Placement travels with the board file for the same reason the
        # thresholds do: the drawing resolves it without a second fetch, and a
        # board with no layout data simply has no key, which is what makes the
        # frontend's fallback the absence of a branch rather than a flag.
        try:
            layout = board_layout(board, headers, args.docs_repo)
        except Unplaced as exc:
            if not args.allow_unplaced:
                sys.exit(f"{board}: {exc} -- this board's committed file "
                         "carries a layout block and this run would rewrite it "
                         "without one. Regenerate on a host that can read the "
                         "source, or pass --allow-unplaced to accept the loss "
                         "deliberately. Nothing has been written.")
            print(f"  {board}: {exc} -- board left unplaced (--allow-unplaced)")
            layout = None
        if layout:
            doc["layout"] = layout
        # BOTH is allowed. The old rule here was "never both", on the reasoning
        # that carrying two claims would leave the drawing to decide which one
        # wins -- but the fix for that is to DECIDE, once, in the open, not to
        # drop one of them. The decision is in boardGrid() in js/app.js, and it
        # now demotes the millimetres twice over: below a direction naming this
        # board's connectors, and below the owner's rule for boards of its
        # shape. Both of those are about how to READ the page; a coordinate is
        # about where the copper is, and this page is a pinout.
        #
        # So on the two measured boards -- La Frite and Le Potato -- the layout
        # block is emitted and is currently drawn on neither. Dropping it
        # instead would be the destructive way to say the same thing, and it
        # would cost the fact: these exports are the only record here of where
        # those connectors actually sit, they are what the drawing's own note
        # cites when it says it departs from the board, and a later placement
        # feature is entitled to them. So both keys are emitted, each saying
        # what kind of claim it is.
        arrangement = board_arrangement(board, headers)
        if arrangement:
            doc["arrangement"] = arrangement
        elec_stats[board] = (n_gpio, n_elec, n_domain, n_analog)
        # A pad whose power domain is not a rail the board block carries resolves
        # to no rail, so the panel shows the domain's name and NO thresholds --
        # which looks exactly like a pad the vendor never documented. It is not:
        # it is a name the two extracts spell differently. Said out loud here
        # because it is silent everywhere else.
        rails = ((doc.get("electrical") or {}).get("rails") or {})
        for h in headers:
            for p in h["pins"]:
                dom = (p.get("elec") or {}).get("domain")
                if dom and rails and dom not in rails:
                    unbound.append(f"{board} {h['id']}.{p['pin']} {p['name']}: "
                                   f"domain {dom!r} is not a rail in this "
                                   "board's electrical block")
        written[f"{board}.json"] = json.dumps(doc, indent=1) + "\n"
        index.append({
            "id": board, "model": model, "name": name, "soc": soc,
            "vendor": vendor, "status": status, "hidden": status != "production",
            "npins": npins,
            "headers": [{"id": h["id"], "pins": len(h["pins"])} for h in headers],
        })
        print(f"{board:22s} {name:20s} {len(headers)} headers, {npins} pins")

    # Catalogue order: model, not product name -- AML-S905X-CC before its -V2
    # and -V3, and each SoC family contiguous.
    index.sort(key=lambda b: b["model"])
    written["boards.json"] = json.dumps({"boards": index}, indent=1) + "\n"

    # Every board survived, so data/ can be replaced.
    out.mkdir(exist_ok=True)
    for stale in out.glob("*.json"):
        stale.unlink()
    for fname, text in written.items():
        (out / fname).write_text(text)

    print(f"\n{len(index)} boards -> {out}/")
    print("\nelectrical coverage (gpio rows / with pad data / with power "
          "domain / analog rows):")
    for board, (n_gpio, n_elec, n_domain, n_analog) in sorted(elec_stats.items()):
        print(f"  {board:22s} {n_gpio:3d} / {n_elec:3d} / {n_domain:3d} / {n_analog:d}")
    if unmatched:
        print(f"\n{len(unmatched)} unmatched mux tokens (kept without offsets):")
        for u in unmatched:
            print(f"  {u}")
    if unbound:
        print(f"\n{len(unbound)} pads whose power domain names no rail "
              "(panel shows the domain and no thresholds):")
        for u in unbound:
            print(f"  {u}")


if __name__ == "__main__":
    main()
