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

Two kinds of input are supported, because the tree holds two kinds of export.

The first is the PADS / PowerPCB DXF, which is what the vendor mechanical
models in the hardware-documentation repo are. Its structure:

    ENTITIES  INSERT  -> BLOCK PART_TOP_n     one placed part
                          TEXT on PART_NAME*  its reference designator
                          INSERT -> SYM_TOP_n  the footprint
                                     INSERT -> STK_TOP_n   one pad, at its own
                                                           insertion point
    BLOCK BOARD_n
      POLYLINE on BOARD_OUTLINE_*             the board edge

so a designator's board position is its INSERT's point, and the extent of the
connector is the bounding box of the pads underneath it, rotated with it.

The second is a FAB PACKAGE -- a pick-and-place spreadsheet beside the gerbers
the boards were made from. Neither half places a connector alone (the P&P names
the designator but gives a point; the gerber has the pads but no designator),
and together they give the same thing the DXF does. See `fab_parts` and the
comment block above it.

Run it directly against a DXF to see what it found before trusting it:

    tools/pcb_layout.py <file.dxf> [designator ...]
"""

import io
import math
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Fab package: pick-and-place spreadsheet + soldermask gerber
#
# The other kind of layout export in the tree is not a mechanical DXF but the
# package a board was MADE from: a pick-and-place spreadsheet next to the
# gerbers. Neither half places a connector on its own, and that is the point --
#
#   * the P&P names the reference designator, and gives its origin, rotation
#     and PIN COUNT -- but a single point, not an extent;
#   * the gerber has every pad at full precision -- and no designator anywhere,
#     which is exactly why the Gerber-only archives in the tree stay unplaced.
#
# Together they are what a DXF gives: an identified connector with a measured
# extent. The identification still comes from the board's own files -- the P&P
# writes "7J1" itself -- so this meets the same standard as the DXF reader, and
# adds a check the DXF reader cannot make: the pad array grown out of the
# gerber has to come to exactly the pin count the P&P states, independently, or
# the header is not placed.
#
# Two facts about the pair have to be supplied per board, because they are
# properties of that export and cannot be read out of either file:
#
#   frame  The P&P is in the design's frame; the gerber is in the frame of the
#          PANEL the boards were made in, where a board may be rotated. `frame`
#          is the (X, Y) of the 180-degree map panel = frame - pnp, verified
#          below by requiring every part's origin to land on a pad.
#   board  The board rectangle inside that panel, read off the outline layer.
#
# Both are quoted in the generator's PCB_LAYOUT entry with the file they came
# from, and both are CHECKED here rather than trusted: a wrong `frame` puts the
# origins on bare laminate and every header fails to seed.

MASK_MOVE = re.compile(r"^(?:X(-?\d+))?(?:Y(-?\d+))?"
                       r"(?:I(-?\d+))?(?:J(-?\d+))?D0?([123])\*$")

# How far a part origin may sit from the nearest pad before the pair is treated
# as unaligned. It is not zero because a decal's origin is not always a pad: on
# Le Potato 2J1 and 9J1 place their origin ON a pin (to a thousandth of a
# millimetre) while 7J1 places its at the CENTRE of a 2x20, which is half a
# pitch from any pad. So this only has to be tight enough that a wrong frame
# finds nothing; what actually proves the match is the containment and pin-count
# checks in `fab_parts`.
SEED_REACH_MM = 3.0
INSIDE_EPSILON_MM = 0.05

# Two openings belong to one connector when they are within this of each other
# AND share a pad size (see `_grow`). A 2.54 mm header needs more than its own
# pitch; the clearance to the next part is larger than this everywhere seen.
PAD_REACH_MM = 3.0
PAD_SIZE_TOLERANCE = 0.15


def archive_member(spec):
    """Bytes of a member of a (possibly nested) RAR: "a.rar!inner.rar!x.gts".

    The fab packages in the tree are RARs holding a second RAR of gerbers, so
    the path to the file that actually carries the pads is a chain. Nothing is
    unpacked to the working tree -- extraction is to a temporary directory that
    goes away with the call."""
    path, *members = spec.split("!")
    data = Path(path).read_bytes()
    for member in members:
        with tempfile.TemporaryDirectory() as tmp:
            arc = Path(tmp) / "archive.rar"
            arc.write_bytes(data)
            out = subprocess.run(["unrar", "p", "-inul", str(arc), member],
                                 stdout=subprocess.PIPE, check=True)
            data = out.stdout
    return data


def placements(data):
    """-> {designator: {"x","y","rot","pins","layer"}} from a PADS pick-and-place
    .xlsx. Read straight out of the OOXML (a zip of XML) so the generator needs
    no spreadsheet library: columns are found by their own header row rather
    than by position, since that is what the file states."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{ns}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))

    def cell(c):
        v = c.find(f"{ns}v")
        if c.get("t") == "s" and v is not None:
            return shared[int(v.text)]
        inline = c.find(f"{ns}is")
        if inline is not None:
            return "".join(t.text or "" for t in inline.iter(f"{ns}t"))
        return v.text if v is not None else ""

    def column(ref):
        n = 0
        for ch in re.match(r"([A-Z]+)", ref).group(1):
            n = n * 26 + ord(ch) - 64
        return n - 1

    rows = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{ns}row"):
        cells = {}
        for c in row.findall(f"{ns}c"):
            cells[column(c.get("r", "A1"))] = cell(c)
        if cells:
            rows.append(cells)
    if not rows:
        return {}
    head = {v.strip().rstrip("."): k for k, v in rows[0].items() if v}
    need = ("RefDes", "X", "Y")
    if not all(k in head for k in need):
        return {}
    found = {}
    for r in rows[1:]:
        des = (r.get(head["RefDes"]) or "").strip()
        try:
            x, y = float(r[head["X"]]), float(r[head["Y"]])
        except (KeyError, TypeError, ValueError):
            continue
        if not des:
            continue
        found[des] = {
            "x": x, "y": y,
            "rot": float(r.get(head.get("Orient", -1), 0) or 0),
            "pins": int(float(r.get(head.get("Pins", -1), 0) or 0)),
            "layer": (r.get(head.get("Layer", -1)) or "").strip(),
        }
    return found


def mask_openings(text):
    """-> [(x0, y0, x1, y1)] in mm, every opening on a RS-274X soldermask layer.

    A pad reaches a CAM "working gerber" three ways, and a reader that sees only
    the first misses most of a board: an aperture FLASH (D03), a filled REGION
    (G36..G37), and a DRAWN stroke with a wide aperture (D01). Le Potato's 9J1
    uses two of the three in one three-pin header -- pin 1 is a flash and pins 2
    and 3 are strokes -- so all three are read.

    Reading the strokes as pads is only sound on the MASK, which is why this
    reads the mask and not the copper: a soldermask layer carries no traces, so
    every mark on it is an opening over a pad and a stroke is an oblong one. The
    same stroke on a copper layer is usually a track."""
    fmt = re.search(r"%FSLA?X(\d)(\d)Y(\d)(\d)\*%", text)
    unit = re.search(r"%MO(IN|MM)\*%", text)
    if not fmt or not unit:
        return []
    div = 10 ** int(fmt.group(2))
    scale = 25.4 if unit.group(1) == "IN" else 1.0
    aperture = {}
    for a in re.finditer(r"%ADD(\d+)([A-Z]),([^*]*)\*%", text):
        parms = [float(v) * scale for v in a.group(3).split("X") if v]
        aperture[int(a.group(1))] = (a.group(2), parms)

    def size(code):
        kind, parms = aperture.get(code, ("C", [0.0]))
        w = parms[0] if parms else 0.0
        return w, (parms[1] if kind == "R" and len(parms) > 1 else w)

    out = []
    x = y = 0.0
    current = None
    region = None
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("G36"):
            region = []
            line = line[3:].lstrip("*")
            if not line:
                continue
        if line.startswith("G37"):
            if region:
                out.append((min(p[0] for p in region), min(p[1] for p in region),
                            max(p[0] for p in region), max(p[1] for p in region)))
            region = None
            continue
        pick = re.match(r"^(?:G\d+)?D(\d{2,})\*$", line)
        if pick:
            current = int(pick.group(1))
            continue
        m = MASK_MOVE.match(re.sub(r"^G\d+", "", line))
        if not m:
            continue
        px, py = x, y
        if m.group(1) is not None:
            x = int(m.group(1)) / div * scale
        if m.group(2) is not None:
            y = int(m.group(2)) / div * scale
        if region is not None:
            region.append((x, y))
        elif m.group(5) == "3":
            w, h = size(current)
            out.append((x - w / 2, y - h / 2, x + w / 2, y + h / 2))
        elif m.group(5) == "1":
            # Swept box of the segment, widened by the aperture. An arc bulges
            # outside this, which makes the box slightly small -- never wrong
            # in kind, and no header here is drawn with an arc.
            w, h = size(current)
            out.append((min(px, x) - w / 2, min(py, y) - h / 2,
                        max(px, x) + w / 2, max(py, y) + h / 2))
    return out


def _grow(boxes, seed):
    """The pad array a connector owns, grown out from one of its own pads.

    Which neighbouring openings belong to the SAME connector is answered by the
    board, not by a threshold on absolute size: a connector's pads come from one
    pad stack, so they share a size, and they sit on a pitch smaller than the
    clearance to the next part. So the array is the connected set of openings
    that are within reach of one already in it AND match its box. The caller
    then checks the count against the P&P's own Pins column, which is the part
    that makes this evidence rather than a guess."""
    centre = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    dim = [(b[2] - b[0], b[3] - b[1]) for b in boxes]
    w0, h0 = dim[seed]
    same = [i for i, (w, h) in enumerate(dim)
            if abs(w - w0) <= PAD_SIZE_TOLERANCE * max(w, w0)
            and abs(h - h0) <= PAD_SIZE_TOLERANCE * max(h, h0)]
    have = {seed}
    stack = [seed]
    while stack:
        j = stack.pop()
        for i in same:
            if i not in have and \
                    abs(centre[i][0] - centre[j][0]) <= PAD_REACH_MM and \
                    abs(centre[i][1] - centre[j][1]) <= PAD_REACH_MM:
                have.add(i)
                stack.append(i)
    return sorted(have)


def fab_parts(spec):
    """-> (outline, {designator: {"x","y","rot","pads","npads"}}) in the
    PLACEMENT file's frame, which is the design's own frame.

    `spec` names the two members and the two facts about the panel; see the
    comment block above. A header appears in the result only when its origin
    landed on a pad and the array grown from that pad came to the pin count the
    P&P states -- everything else is dropped, and the caller's completeness
    check turns that into an unplaced board."""
    fx, fy = spec["frame"]
    mask = archive_member(spec["mask"]).decode("utf-8", "replace")
    # Panel -> design frame: the board sits in the panel rotated 180 degrees,
    # so both axes mirror about the constants the spec quotes.
    boxes = [(fx - b[2], fy - b[3], fx - b[0], fy - b[1])
             for b in mask_openings(mask)]
    bx0, by0, bx1, by1 = spec["board"]
    outline = (fx - bx1, fy - by1, fx - bx0, fy - by0)
    if not boxes:
        return None, {}

    centre = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in boxes]
    found = {}
    for des, rec in placements(archive_member(spec["pnp"])).items():
        d, seed = min((abs(centre[i][0] - rec["x"]) + abs(centre[i][1] - rec["y"]), i)
                      for i in range(len(boxes)))
        if d > SEED_REACH_MM:
            continue
        comp = _grow(boxes, seed)
        xs = [c for i in comp for c in (boxes[i][0], boxes[i][2])]
        ys = [c for i in comp for c in (boxes[i][1], boxes[i][3])]
        box = (min(xs), min(ys), max(xs), max(ys))
        # Two checks the two files make of each other, and the reason this is
        # evidence rather than a nearest-neighbour guess: the part's origin has
        # to fall INSIDE the array grown from its seed, and the array has to
        # come to exactly the pin count the P&P states for that designator.
        if not (box[0] - INSIDE_EPSILON_MM <= rec["x"] <= box[2] + INSIDE_EPSILON_MM
                and box[1] - INSIDE_EPSILON_MM <= rec["y"] <= box[3] + INSIDE_EPSILON_MM):
            continue
        if rec["pins"] and len(comp) != rec["pins"]:
            continue
        found[des] = {"x": rec["x"], "y": rec["y"], "rot": rec["rot"],
                      "npads": len(comp), "pads": box}
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
