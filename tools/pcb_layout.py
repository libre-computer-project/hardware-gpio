#!/usr/bin/env python3
"""Where a connector physically sits on a board, read out of a PCB CAD export.

The pinout draws each header as a connector-shaped block. Which header is drawn
WHERE was, until this module, an artefact of map order and CSS column packing --
it told the reader nothing. This reads the real placement out of the board's own
layout data so the diagram can be arranged as a board view.

The standard of proof is the one `DUAL_ROW_HEADERS` in gen-pinout-data.py sets
for row count: a claim about a connector's physical arrangement is made only
from that board's own CAD data, never inferred. Drawing a 1xN as 2xN invents a
rail the board does not have; drawing a header at the wrong end of the board
invents a layout it does not have, and a reader with a jumper wire in hand is
misled in exactly the same way. So:

  * A position comes from the part's own INSERT in the layout export, keyed to
    the reference designator the export carries for it. Nothing is derived from
    a designator's NUMBER, from a product photo, or from a sibling revision.
  * A board is placed only when EVERY header the wiring map lists for it is
    found. A board view missing one header is worse than no board view: the
    reader cannot tell that the missing one is missing rather than absent from
    the hardware.

Supported input is the PADS / PowerPCB DXF export, which is what the vendor
mechanical models in the hardware-documentation repo are. Its structure:

    ENTITIES  INSERT  -> BLOCK PART_TOP_n     one placed part
                          TEXT on PART_NAME*  its reference designator
                          INSERT -> SYM_TOP_n  the footprint
                                     INSERT -> STK_TOP_n   one pad, at its own
                                                           insertion point
    BLOCK BOARD_n
      POLYLINE on BOARD_OUTLINE_*             the board edge

so a designator's board position is its INSERT's point, and the extent of the
connector is the bounding box of the pads underneath it, rotated with it.

Run it directly against a DXF to see what it found before trusting it:

    tools/pcb_layout.py <file.dxf> [designator ...]
"""

import math
import sys

# How deep an INSERT chain is followed. Part -> footprint -> pad is three, and
# the exports seen so far never go deeper; the cap is only here so a malformed
# file with a block that inserts itself cannot spin.
MAX_INSERT_DEPTH = 8

PAD_BLOCK_PREFIXES = ("STK_",)
NAME_LAYER_PREFIXES = ("PART_NAME", "SYM_PART_NAME")
OUTLINE_LAYER_PREFIX = "BOARD_OUTLINE"


def _pairs(path):
    """DXF is a flat stream of (group code, value) lines. Read as bytes and
    decode leniently: these exports carry stray NULs in the header block, which
    make a strict text read fail on a file that is otherwise perfectly good."""
    with open(path, "rb") as fh:
        data = fh.read().decode("utf-8", "replace")
    lines = data.replace("\r\n", "\n").split("\n")
    for i in range(0, len(lines) - 1, 2):
        yield lines[i].strip(), lines[i + 1]


class Entity(dict):
    pass


def parse(path):
    """-> (blocks, entities). Both hold Entity dicts; a POLYLINE carries its
    VERTEX points in `pts`, because in DXF those are separate entities that
    belong to whatever POLYLINE last opened."""
    blocks = {}
    entities = []
    section = None
    block = None
    target = entities
    ent = None
    poly = None

    def close():
        nonlocal ent
        if ent is not None and ent.get("type") != "VERTEX":
            target.append(ent)
        ent = None

    for code, val in _pairs(path):
        if code == "0":
            if val == "SECTION":
                close()
                section = None
                continue
            if val == "ENDSEC":
                close()
                section = None
                block = None
                target = entities
                continue
            if val == "BLOCK":
                close()
                block = {"name": None, "ents": []}
                ent = Entity(type="BLOCK", _blk=block)
                target = block["ents"]
                continue
            if val == "ENDBLK":
                close()
                if block and block["name"]:
                    blocks[block["name"]] = block
                block = None
                target = entities
                poly = None
                continue
            if val == "VERTEX":
                close()
                ent = Entity(type="VERTEX")
                continue
            close()
            ent = Entity(type=val)
            if val == "POLYLINE":
                poly = ent
                ent["pts"] = []
            continue

        if ent is None:
            if code == "2" and section is None:
                section = val
            continue

        if ent.get("type") == "BLOCK":
            if code == "2" and ent["_blk"]["name"] is None:
                ent["_blk"]["name"] = val
            continue

        if code == "8":
            ent["layer"] = val
        elif code == "2":
            ent["block"] = val
        elif code == "1":
            ent["text"] = val
        elif code == "10":
            ent["x"] = float(val)
        elif code == "20":
            ent["y"] = float(val)
        elif code == "50":
            ent["rot"] = float(val)
        elif code == "41":
            ent["sx"] = float(val)
        elif code == "42" and ent.get("type") != "VERTEX":
            # 42 on a VERTEX is the arc bulge, not a scale factor.
            ent["sy"] = float(val)

        if ent.get("type") == "VERTEX" and "x" in ent and "y" in ent and poly is not None:
            if not ent.get("_taken"):
                poly["pts"].append((ent["x"], ent["y"]))
                ent["_taken"] = True

    close()
    return blocks, entities


def _place(pt, ins):
    """A point in block-local coordinates, moved into the frame the INSERT sits
    in. Mirrored parts (a connector on the underside) come through as a negative
    scale, so the sign has to be applied before the rotation."""
    sx = ins.get("sx", 1.0) or 1.0
    sy = ins.get("sy", 1.0) or 1.0
    a = math.radians(ins.get("rot", 0.0))
    c, s = math.cos(a), math.sin(a)
    x, y = pt[0] * sx, pt[1] * sy
    return (ins.get("x", 0.0) + x * c - y * s,
            ins.get("y", 0.0) + x * s + y * c)


def _compose(inner, outer):
    """One INSERT seen through another, so a nested block's own placement can be
    carried without transforming its whole point set at every level."""
    return {
        "x": _place((inner.get("x", 0.0), inner.get("y", 0.0)), outer)[0],
        "y": _place((inner.get("x", 0.0), inner.get("y", 0.0)), outer)[1],
        "rot": outer.get("rot", 0.0) + inner.get("rot", 0.0),
        "sx": (outer.get("sx", 1.0) or 1.0) * (inner.get("sx", 1.0) or 1.0),
        "sy": (outer.get("sy", 1.0) or 1.0) * (inner.get("sy", 1.0) or 1.0),
    }


def _walk(blocks, name, ins, depth, out_name, out_pads):
    """Collect, from one placed block and everything it inserts, the reference
    designator it declares and the board-frame position of every pad."""
    if depth > MAX_INSERT_DEPTH or name not in blocks:
        return
    for e in blocks[name]["ents"]:
        t = e.get("type")
        layer = e.get("layer", "")
        if t == "TEXT" and e.get("text") and \
                any(layer.startswith(p) for p in NAME_LAYER_PREFIXES):
            txt = e["text"].strip()
            if txt and out_name[0] is None:
                out_name[0] = txt
        elif t == "INSERT" and e.get("block"):
            child = _compose(e, ins)
            if any(e["block"].startswith(p) for p in PAD_BLOCK_PREFIXES):
                out_pads.append((child["x"], child["y"]))
            _walk(blocks, e["block"], child, depth + 1, out_name, out_pads)


def board_outline(blocks, entities):
    """Bounding box of the board edge, as (xmin, ymin, xmax, ymax), or None.

    The edge is a polyline inside a BOARD_* block, so it has to be placed by its
    INSERT like any other part rather than read where it is written."""
    pts = []

    def collect(name, ins, depth):
        if depth > MAX_INSERT_DEPTH or name not in blocks:
            return
        for e in blocks[name]["ents"]:
            if e.get("type") == "POLYLINE" and \
                    e.get("layer", "").startswith(OUTLINE_LAYER_PREFIX):
                pts.extend(_place(p, ins) for p in e["pts"])
            elif e.get("type") == "INSERT" and e.get("block"):
                collect(e["block"], _compose(e, ins), depth + 1)

    for e in entities:
        if e.get("type") == "INSERT" and e.get("block"):
            collect(e["block"], e, 0)
        elif e.get("type") == "POLYLINE" and \
                e.get("layer", "").startswith(OUTLINE_LAYER_PREFIX):
            pts.extend(e["pts"])
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def parts(path):
    """-> (outline, {designator: {"x","y","rot","pads",...}}) in the DXF's own
    millimetre frame. `pads` is the pad bounding box where the footprint carries
    one, so a header's EXTENT is measured rather than assumed from its pin
    count."""
    blocks, entities = parse(path)
    outline = board_outline(blocks, entities)
    found = {}
    for e in entities:
        if e.get("type") != "INSERT" or not e.get("block"):
            continue
        name = [None]
        pads = []
        _walk(blocks, e["block"], e, 0, name, pads)
        if not name[0]:
            continue
        rec = {"x": e.get("x", 0.0), "y": e.get("y", 0.0),
               "rot": e.get("rot", 0.0), "block": e["block"], "npads": len(pads)}
        if pads:
            xs = [p[0] for p in pads]
            ys = [p[1] for p in pads]
            rec["pads"] = (min(xs), min(ys), max(xs), max(ys))
        # A designator placed twice is a data problem, not a choice to make:
        # keep the first and let the caller's completeness check speak.
        found.setdefault(name[0], rec)
    return outline, found


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    outline, found = parts(argv[1])
    want = set(argv[2:])
    print(f"outline: {outline}")
    if outline:
        print(f"board: {outline[2] - outline[0]:.3f} x {outline[3] - outline[1]:.3f} mm")
    print(f"{len(found)} placed parts")
    for des in sorted(found):
        if want and des not in want:
            continue
        r = found[des]
        pads = r.get("pads")
        print(f"  {des:8s} ins=({r['x']:.4f},{r['y']:.4f}) rot={r['rot']:g} "
              f"pads={r['npads']}" +
              (f" box=({pads[0]:.4f},{pads[1]:.4f})..({pads[2]:.4f},{pads[3]:.4f})"
               if pads else ""))


if __name__ == "__main__":
    main(sys.argv)
