from neo4j import GraphDatabase
from dotenv import load_dotenv
import os
import pandas as pd

load_dotenv()

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"),
          os.getenv("NEO4J_PASSWORD"))
)

# ─────────────────────────────────────────
# VOB/C DIN 18363 RULES
# ─────────────────────────────────────────
VOB_DEDUCTION_LIMIT   = 2.5   # m² — openings only deducted if > 2.5 m²
VOB_NICHE_LIMIT       = 2.5   # m² — niches only added if > 2.5 m²
VOB_REVEAL_ENABLED    = True  # add door/window reveal areas
BASEBOARD_HEIGHT      = 0.10  # m  — standard Sockelleiste height


# ─────────────────────────────────────────
# HELPER — wall thickness from name
# ─────────────────────────────────────────
def get_wall_thickness(wall_name):
    """
    Extract wall thickness in meters from wall name.
    Revit names like 'Basiswand:GK 100' → 0.10m
    'Basiswand:Ziegel+WD hart 200+200' → 0.40m
    'Basiswand:Ceramic 10' → 0.01m
    """
    import re
    name = wall_name or ""
    numbers = re.findall(r'\d+', name)
    if not numbers:
        return 0.20  # default 20cm
    # Take largest number as combined thickness
    total = sum(int(n) for n in numbers
                if 5 <= int(n) <= 500)
    return round(total / 1000, 3) if total else 0.20


# ─────────────────────────────────────────
# HELPER — reveal area (Laibungsfläche)
# VOB: add side surfaces of openings
# reveal = wall_thickness × perimeter
# ─────────────────────────────────────────
def calc_reveal_area(width_m, height_m, wall_thickness_m):
    """
    Calculate reveal area for a door or window.
    Reveals = the side surfaces inside the wall opening.
    Perimeter of opening × wall thickness.
    For windows: all 4 sides (top, bottom, left, right)
    For doors:   3 sides (top, left, right — no floor reveal)
    """
    if not width_m or not height_m or not wall_thickness_m:
        return 0.0
    # 2 vertical sides + 1 horizontal top
    perimeter_3sides = (2 * height_m) + width_m
    return round(perimeter_3sides * wall_thickness_m, 2)


# ─────────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────────
def generate_raumbuch():
    rooms = []

    with driver.session() as session:

        # Get all spaces
        spaces = session.run("""
            MATCH (f:Floor)-[:CONTAINS]->(s:Space)
            RETURN s.name     AS id,
                   s.long_name AS name,
                   f.name     AS floor,
                   s.area     AS area,
                   s.height   AS height,
                   s.volume   AS volume
            ORDER BY s.name
        """).data()

        for space in spaces:
            space_id   = space["id"]
            space_name = space["name"]

            # ── Floor area + dimensions ──────────
            floor_area   = space["area"]   or 0
            height       = space["height"] or 0
            volume       = round(floor_area * height, 2)
            ceiling_area = floor_area

            # ── DIN 277 area classification ──────
            # Classify room type based on name
            din277_type = classify_din277(space_name)

            # ── WALLS ────────────────────────────
            walls = session.run("""
                MATCH (w:Wall)-[b:BOUNDS]->(s:Space {name: $id})
                RETURN w.wall_type AS type,
                       w.name     AS name,
                       b.area     AS area,
                       b.length   AS length,
                       b.height   AS height
            """, id=space_id).data()

            structural_area = sum(
                w["area"] for w in walls
                if w["type"] in ["structural","drywall","general"]
                and w["area"]
            )
            ceramic_area = sum(
                w["area"] for w in walls
                if w["type"] == "ceramic"
                and w["area"]
            )
            glass_area = sum(
                w["area"] for w in walls
                if w["type"] == "glass"
                and w["area"]
            )
            gross_wall = sum(
                w["area"] for w in walls
                if w["area"]
            )

            # ── Baseboard (Sockelleiste) ──────────
            # VOB: baseboard area = room perimeter × baseboard height
            # We approximate perimeter from wall lengths
            wall_lengths = [w["length"] for w in walls
                           if w["length"] and
                           w["type"] in ["structural","drywall","general"]]
            # Each wall appears once per side — divide by 2 for perimeter
            total_wall_length = sum(wall_lengths)
            baseboard_area = round(
                total_wall_length * BASEBOARD_HEIGHT, 2
            )

            # ── DOORS ────────────────────────────
            doors = session.run("""
                MATCH (d:Door)-[:OPENS_INTO]->(s:Space {name: $id})
                RETURN d.name   AS name,
                       d.width  AS width,
                       d.height AS height,
                       d.guid   AS guid
            """, id=space_id).data()

            door_list = []
            for d in doors:
                w = d["width"]  or 0
                h = d["height"] or 0

                # Convert mm → m if needed
                if w > 100:
                    width_m  = round(w / 1000, 3)
                    height_m = round(h / 1000, 3)
                else:
                    width_m  = round(w, 3)
                    height_m = round(h, 3)

                opening_area = round(width_m * height_m, 2)

                # Corridor detection
                other_spaces = session.run("""
                    MATCH (d:Door {guid: $guid})
                          -[:OPENS_INTO]->(s:Space)
                    WHERE s.name <> $current_id
                    RETURN s.area AS other_area
                """, guid=d["guid"],
                    current_id=space_id).data()

                is_corridor = any(
                    floor_area > (o["other_area"] or 0)
                    for o in other_spaces
                )

                # VOB: deduct if > 2.5m² AND not corridor
                vob_deduct = (
                    opening_area > VOB_DEDUCTION_LIMIT
                    and not is_corridor
                )

                # Reveal area (Laibung)
                # Get wall thickness from walls around this door
                avg_thickness = 0.20  # default
                if walls:
                    thicknesses = [
                        get_wall_thickness(w["name"])
                        for w in walls
                        if w["type"] in ["structural","drywall"]
                    ]
                    if thicknesses:
                        avg_thickness = sum(thicknesses) / len(thicknesses)

                reveal = 0.0
                if VOB_REVEAL_ENABLED and not is_corridor:
                    reveal = calc_reveal_area(
                        width_m, height_m, avg_thickness
                    )

                door_list.append({
                    "name":         d["name"],
                    "width_m":      width_m,
                    "height_m":     height_m,
                    "opening_area": opening_area,
                    "is_corridor":  is_corridor,
                    "vob_deduct":   vob_deduct,
                    "reveal_area":  reveal
                })

            door_count       = len(door_list)
            door_deductions  = sum(
                d["opening_area"] for d in door_list
                if d["vob_deduct"]
            )
            door_reveals     = sum(
                d["reveal_area"] for d in door_list
                if not d["is_corridor"]
            )

            # ── WINDOWS ──────────────────────────
            windows = session.run("""
                MATCH (w:Window)-[:BELONGS_TO]->(s:Space {name: $id})
                RETURN w.name   AS name,
                       w.width  AS width,
                       w.height AS height
            """, id=space_id).data()

            window_list = []
            for win in windows:
                w = win["width"]  or 0
                h = win["height"] or 0

                if w > 100:
                    width_m  = round(w / 1000, 3)
                    height_m = round(h / 1000, 3)
                else:
                    width_m  = round(w, 3)
                    height_m = round(h, 3)

                opening_area = round(width_m * height_m, 2)

                # VOB: deduct if > 2.5m²
                vob_deduct = opening_area > VOB_DEDUCTION_LIMIT

                # Reveal area — windows have 4 sides
                # (top + bottom + left + right)
                reveal = 0.0
                if VOB_REVEAL_ENABLED:
                    # External wall thickness for windows
                    ext_walls = [w for w in walls
                                 if w["type"] == "structural"]
                    if ext_walls:
                        thickness = get_wall_thickness(
                            ext_walls[0]["name"]
                        )
                    else:
                        thickness = 0.40  # default external wall

                    # 4 sides: 2 vertical + top + bottom
                    perimeter_4sides = (2 * height_m) + (2 * width_m)
                    reveal = round(
                        perimeter_4sides * thickness, 2
                    )

                window_list.append({
                    "name":         win["name"],
                    "width_m":      width_m,
                    "height_m":     height_m,
                    "opening_area": opening_area,
                    "vob_deduct":   vob_deduct,
                    "reveal_area":  reveal
                })

            window_count      = len(window_list)
            window_deductions = sum(
                w["opening_area"] for w in window_list
                if w["vob_deduct"]
            )
            window_reveals    = sum(
                w["reveal_area"] for w in window_list
            )

            # ── FURNITURE ────────────────────────
            furniture = session.run("""
                MATCH (s:Space {long_name: $name})
                      -[:HAS_FURNITURE]->(f:Furniture)
                RETURN f.name AS name
            """, name=space_name).data()

            furniture_count = len(furniture)
            furniture_names = ", ".join(
                [f["name"] for f in furniture]
            )

            # ── FINAL CALCULATIONS ────────────────
            # VOB Net painting area:
            # Gross structural walls
            # - VOB door deductions (if > 2.5m² and not corridor)
            # - VOB window deductions (if > 2.5m²)
            # + door reveals (Laibungen)
            # + window reveals (Laibungen)
            total_deductions = round(
                door_deductions + window_deductions, 2
            )
            total_reveals = round(
                door_reveals + window_reveals, 2
            )
            net_paint_area = round(
                structural_area
                - total_deductions
                + total_reveals,
                2
            )

            # Opening deduction detail string
            door_detail = ", ".join([
                f"{d['name'][-15:]} "
                f"({d['width_m']}x{d['height_m']}m"
                f"={d['opening_area']}m²"
                f"{' [corridor]' if d['is_corridor'] else ' [deducted]' if d['vob_deduct'] else ' [<2.5m²]'})"
                for d in door_list
            ])

            window_detail = ", ".join([
                f"{w['name'][-15:]} "
                f"({w['width_m']}x{w['height_m']}m"
                f"={w['opening_area']}m²"
                f"{' [deducted]' if w['vob_deduct'] else ' [<2.5m²]'})"
                for w in window_list
            ])

            rooms.append({
                # ── Identification ──
                "Nr":                  space_id,
                "Raum":                space_name,
                "Ebene":               space["floor"],
                "DIN 277 Typ":         din277_type,

                # ── DIN 277 Areas ──
                "NGF (m²)":            floor_area,
                "Höhe (m)":            height,
                "Volumen (m³)":        volume,

                # ── Walls ──
                "Wand Brutto (m²)":    round(gross_wall, 2),
                "Abzüge VOB (m²)":     total_deductions,
                "Laibungen + (m²)":    total_reveals,
                "Anstrich Netto (m²)": net_paint_area,
                "Fliesen (m²)":        round(ceramic_area, 2),
                "Glas (m²)":           round(glass_area, 2),

                # ── Ceiling + Floor ──
                "Decke (m²)":          ceiling_area,
                "Boden (m²)":          floor_area,

                # ── Baseboard ──
                "Sockelleiste (m)":    round(total_wall_length, 2),
                "Sockelleiste (m²)":   baseboard_area,

                # ── Openings ──
                "Türen Anz.":          door_count,
                "Türen Details":       door_detail,
                "Fenster Anz.":        window_count,
                "Fenster Details":     window_detail,

                # ── Furniture ──
                "Möbel Anz.":          furniture_count,
                "Möbel Details":       furniture_names
            })

    return rooms


# ─────────────────────────────────────────
# DIN 277 ROOM CLASSIFICATION
# ─────────────────────────────────────────
def classify_din277(room_name):
    """
    Classify room into DIN 277 Nutzungsgruppe.
    NUF 1 = Wohnen und Aufenthalt
    NUF 3 = Pflege und Therapie
    NUF 4 = Bildung, Unterricht
    NUF 5 = Sammeln, Sichern
    NUF 6 = Bewirtschaften, Versorgen
    VF 1  = Verkehrserschliessung (corridor)
    TF 1  = Technische Anlagen
    """
    name = (room_name or "").lower()

    if any(x in name for x in [
        "bed", "schlaf", "wohn", "living",
        "kind", "gast", "zimmer"
    ]):
        return "NUF 1 — Wohnen"

    elif any(x in name for x in [
        "kitchen", "küche", "kochen"
    ]):
        return "NUF 6 — Kochen/Versorgen"

    elif any(x in name for x in [
        "bath", "bad", "dusch", "shower",
        "wc", "toilet", "sanitär"
    ]):
        return "NUF 3 — Sanitär"

    elif any(x in name for x in [
        "flur", "korridor", "corridor",
        "hall", "diele", "foyer", "eingang"
    ]):
        return "VF 1 — Verkehrsfläche"

    elif any(x in name for x in [
        "keller", "lager", "storage",
        "abstellraum"
    ]):
        return "NUF 5 — Lagern"

    elif any(x in name for x in [
        "heizung", "technik", "hausan",
        "utility", "mechanical"
    ]):
        return "TF 1 — Technik"

    else:
        return "NUF 1 — Wohnen"


# ─────────────────────────────────────────
# PRINT RAUMBUCH
# ─────────────────────────────────────────
def print_raumbuch(rooms):
    print("\n" + "=" * 80)
    print("RAUMBUCH — BIM NEXUS BUILDING")
    print("DIN 277 + VOB/C DIN 18363 (with reveals)")
    print("=" * 80)

    total_ngf       = 0
    total_paint     = 0
    total_ceramic   = 0
    total_glass     = 0
    total_deduct    = 0
    total_reveals   = 0
    total_baseboard = 0

    for r in rooms:
        print(f"\n┌─ Raum {r['Nr']}: {r['Raum']} "
              f"({r['Ebene']}) — {r['DIN 277 Typ']}")
        print(f"│")
        print(f"│  FLÄCHEN (DIN 277)")
        print(f"│    NGF:          {r['NGF (m²)']} m²")
        print(f"│    Höhe:         {r['Höhe (m)']} m")
        print(f"│    Volumen:       {r['Volumen (m³)']} m³")
        print(f"│")
        print(f"│  WANDFLÄCHEN (VOB/C DIN 18363)")
        print(f"│    Brutto:        {r['Wand Brutto (m²)']} m²")
        print(f"│    Abzüge:       -{r['Abzüge VOB (m²)']} m² "
              f"(Öffnungen > 2.5 m²)")
        print(f"│    Laibungen:    +{r['Laibungen + (m²)']} m² "
              f"(Reveals hinzugefügt)")
        print(f"│    Anstrich Netto:{r['Anstrich Netto (m²)']} m²")
        print(f"│    Fliesen:       {r['Fliesen (m²)']} m²")
        print(f"│    Glasfläche:    {r['Glas (m²)']} m²")
        print(f"│")
        print(f"│  BODEN + DECKE")
        print(f"│    Boden:         {r['Boden (m²)']} m²")
        print(f"│    Decke:         {r['Decke (m²)']} m²")
        print(f"│    Sockelleiste:  {r['Sockelleiste (m)']} m  "
              f"/ {r['Sockelleiste (m²)']} m²")
        print(f"│")
        print(f"│  ÖFFNUNGEN")
        print(f"│    Türen ({r['Türen Anz.']}):  {r['Türen Details']}")
        print(f"│    Fenster ({r['Fenster Anz.']}): {r['Fenster Details']}")
        print(f"│")
        print(f"│  AUSSTATTUNG")
        print(f"│    Möbel: {r['Möbel Anz.']} items")
        if r["Möbel Details"]:
            print(f"│    {r['Möbel Details']}")
        print(f"└{'─' * 60}")

        total_ngf       += r["NGF (m²)"]           or 0
        total_paint     += r["Anstrich Netto (m²)"] or 0
        total_ceramic   += r["Fliesen (m²)"]        or 0
        total_glass     += r["Glas (m²)"]           or 0
        total_deduct    += r["Abzüge VOB (m²)"]     or 0
        total_reveals   += r["Laibungen + (m²)"]    or 0
        total_baseboard += r["Sockelleiste (m²)"]   or 0

    print(f"\n{'=' * 80}")
    print(f"GESAMT (TOTAL)")
    print(f"  NGF gesamt:           {round(total_ngf, 2)} m²")
    print(f"  Anstrich gesamt:      {round(total_paint, 2)} m²")
    print(f"  VOB Abzüge:          -{round(total_deduct, 2)} m²")
    print(f"  Laibungen:           +{round(total_reveals, 2)} m²")
    print(f"  Fliesen gesamt:       {round(total_ceramic, 2)} m²")
    print(f"  Glasfläche gesamt:    {round(total_glass, 2)} m²")
    print(f"  Sockelleiste gesamt:  {round(total_baseboard, 2)} m²")
    print(f"{'=' * 80}")


# ─────────────────────────────────────────
# EXPORT TO EXCEL
# ─────────────────────────────────────────
def export_to_excel(rooms):
    df = pd.DataFrame(rooms)
    output_path = "sample_data/raumbuch.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

        # Sheet 1 — Full Raumbuch
        df.to_excel(writer, sheet_name="Raumbuch", index=False)

        # Sheet 2 — Summary by DIN 277 type
        summary = df.groupby("DIN 277 Typ").agg({
            "NGF (m²)":            "sum",
            "Anstrich Netto (m²)": "sum",
            "Fliesen (m²)":        "sum",
            "Glas (m²)":           "sum",
            "Türen Anz.":          "sum",
            "Fenster Anz.":        "sum",
        }).round(2)
        summary.to_excel(writer, sheet_name="DIN 277 Summary")

        # Sheet 3 — Trade quantities
        trades = pd.DataFrame([{
            "Gewerk (Trade)":  "Maler (Painter)",
            "Beschreibung":    "Wandanstrich Netto",
            "Menge":           round(df["Anstrich Netto (m²)"].sum(), 2),
            "Einheit":         "m²"
        }, {
            "Gewerk (Trade)":  "Fliesenleger (Tiler)",
            "Beschreibung":    "Wandfliesen",
            "Menge":           round(df["Fliesen (m²)"].sum(), 2),
            "Einheit":         "m²"
        }, {
            "Gewerk (Trade)":  "Bodenleger (Floor)",
            "Beschreibung":    "Bodenbelag NGF",
            "Menge":           round(df["Boden (m²)"].sum(), 2),
            "Einheit":         "m²"
        }, {
            "Gewerk (Trade)":  "Decke (Ceiling)",
            "Beschreibung":    "Deckenanstrich",
            "Menge":           round(df["Decke (m²)"].sum(), 2),
            "Einheit":         "m²"
        }, {
            "Gewerk (Trade)":  "Schreiner (Joiner)",
            "Beschreibung":    "Sockelleiste",
            "Menge":           round(df["Sockelleiste (m)"].sum(), 2),
            "Einheit":         "m"
        }, {
            "Gewerk (Trade)":  "Glaser (Glazier)",
            "Beschreibung":    "Glasfläche",
            "Menge":           round(df["Glas (m²)"].sum(), 2),
            "Einheit":         "m²"
        }])
        trades.to_excel(writer, sheet_name="Gewerk Mengen", index=False)

    print(f"\n✅ Raumbuch exported: {output_path}")
    print(f"   Sheet 1: Full Raumbuch")
    print(f"   Sheet 2: DIN 277 Summary by room type")
    print(f"   Sheet 3: Quantities per trade (Gewerk)")
    return output_path


# ─────────────────────────────────────────
# RUN
# ─────────────────────────────────────────
if __name__ == "__main__":
    print("Generating Raumbuch (DIN 277 + VOB)...")
    rooms = generate_raumbuch()
    print_raumbuch(rooms)
    export_to_excel(rooms)
