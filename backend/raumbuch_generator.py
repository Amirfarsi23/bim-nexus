from neo4j import GraphDatabase
from dotenv import load_dotenv
import os
import pandas as pd

load_dotenv()

# ─────────────────────────────────────
# VOB/C DIN 18363 RULES
# ─────────────────────────────────────
VOB_DEDUCTION_LIMIT = 2.5
VOB_NICHE_LIMIT     = 2.5
VOB_REVEAL_ENABLED  = True
BASEBOARD_HEIGHT    = 0.10


# ─────────────────────────────────────
# FALLBACK DRIVER — standalone use only
# ─────────────────────────────────────
def _get_fallback_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    )


# ─────────────────────────────────────
# HELPER — wall thickness from name
# ─────────────────────────────────────
def get_wall_thickness(wall_name):
    import re
    name    = wall_name or ""
    numbers = re.findall(r'\d+', name)
    if not numbers:
        return 0.20
    total = sum(int(n) for n in numbers if 5 <= int(n) <= 500)
    return round(total / 1000, 3) if total else 0.20


# ─────────────────────────────────────
# HELPER — reveal area
# ─────────────────────────────────────
def calc_reveal_area(width_m, height_m, wall_thickness_m):
    if not width_m or not height_m or not wall_thickness_m:
        return 0.0
    perimeter_3sides = (2 * height_m) + width_m
    return round(perimeter_3sides * wall_thickness_m, 2)


# ─────────────────────────────────────
# MAIN GENERATOR
# ─────────────────────────────────────
def generate_raumbuch(driver=None, user_id="demo_user", project_id="default_project"):
    if driver is None:
        driver = _get_fallback_driver()

    rooms = []

    with driver.session() as session:

        # ── Spaces ──
        spaces = session.run("""
            MATCH (f:Floor {user_id: $uid, project_id: $pid})
                  -[:CONTAINS]->
                  (s:Space {user_id: $uid, project_id: $pid})
            RETURN s.name      AS id,
                   s.long_name AS name,
                   f.name      AS floor,
                   s.area      AS area,
                   s.height    AS height,
                   s.volume    AS volume
            ORDER BY s.name
        """, uid=user_id, pid=project_id).data()

        for space in spaces:
            space_id   = space["id"]
            space_name = space["name"]

            floor_area   = space["area"]   or 0
            height       = space["height"] or 0
            volume       = round(floor_area * height, 2)
            ceiling_area = floor_area
            din277_type  = classify_din277(space_name)

            # ── Walls ──
            walls = session.run("""
                MATCH (w:Wall {user_id: $uid, project_id: $pid})
                      -[b:BOUNDS]->
                      (s:Space {name: $id, user_id: $uid, project_id: $pid})
                RETURN w.wall_type AS type,
                       w.name      AS name,
                       b.area      AS area,
                       b.length    AS length,
                       b.height    AS height
            """, id=space_id, uid=user_id, pid=project_id).data()

            structural_area = sum(
                w["area"] for w in walls
                if w["type"] in ["structural", "drywall", "general"] and w["area"]
            )
            ceramic_area = sum(
                w["area"] for w in walls
                if w["type"] == "ceramic" and w["area"]
            )
            glass_area = sum(
                w["area"] for w in walls
                if w["type"] == "glass" and w["area"]
            )
            gross_wall = sum(w["area"] for w in walls if w["area"])

            wall_lengths = [
                w["length"] for w in walls
                if w["length"] and w["type"] in ["structural", "drywall", "general"]
            ]
            total_wall_length = sum(wall_lengths)
            baseboard_area    = round(total_wall_length * BASEBOARD_HEIGHT, 2)

            # ── Doors ──
            doors = session.run("""
                MATCH (d:Door {user_id: $uid, project_id: $pid})
                      -[:OPENS_INTO]->
                      (s:Space {name: $id, user_id: $uid, project_id: $pid})
                RETURN d.name   AS name,
                       d.width  AS width,
                       d.height AS height,
                       d.guid   AS guid
            """, id=space_id, uid=user_id, pid=project_id).data()

            door_list = []
            for d in doors:
                w = d["width"]  or 0
                h = d["height"] or 0
                if w > 100:
                    width_m  = round(w / 1000, 3)
                    height_m = round(h / 1000, 3)
                else:
                    width_m  = round(w, 3)
                    height_m = round(h, 3)

                opening_area = round(width_m * height_m, 2)

                other_spaces = session.run("""
                    MATCH (d:Door {guid: $guid, user_id: $uid, project_id: $pid})
                          -[:OPENS_INTO]->
                          (s:Space {user_id: $uid, project_id: $pid})
                    WHERE s.name <> $current_id
                    RETURN s.area AS other_area
                """, guid=d["guid"], current_id=space_id,
                    uid=user_id, pid=project_id).data()

                is_corridor = any(
                    floor_area > (o["other_area"] or 0)
                    for o in other_spaces
                )
                vob_deduct = opening_area > VOB_DEDUCTION_LIMIT and not is_corridor

                avg_thickness = 0.20
                if walls:
                    thicknesses = [
                        get_wall_thickness(w["name"])
                        for w in walls
                        if w["type"] in ["structural", "drywall"]
                    ]
                    if thicknesses:
                        avg_thickness = sum(thicknesses) / len(thicknesses)

                reveal = 0.0
                if VOB_REVEAL_ENABLED and not is_corridor:
                    reveal = calc_reveal_area(width_m, height_m, avg_thickness)

                door_list.append({
                    "name":         d["name"],
                    "width_m":      width_m,
                    "height_m":     height_m,
                    "opening_area": opening_area,
                    "is_corridor":  is_corridor,
                    "vob_deduct":   vob_deduct,
                    "reveal_area":  reveal
                })

            door_count      = len(door_list)
            door_deductions = sum(d["opening_area"] for d in door_list if d["vob_deduct"])
            door_reveals    = sum(d["reveal_area"]  for d in door_list if not d["is_corridor"])
            door_detail     = "; ".join([
                f"{d['name']} {d['width_m']}×{d['height_m']}m"
                for d in door_list
            ])

            # ── Windows ──
            windows = session.run("""
                MATCH (w:Window {user_id: $uid, project_id: $pid})
                      -[:BELONGS_TO]->
                      (s:Space {name: $id, user_id: $uid, project_id: $pid})
                RETURN w.name   AS name,
                       w.width  AS width,
                       w.height AS height,
                       w.guid   AS guid
            """, id=space_id, uid=user_id, pid=project_id).data()

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
                vob_deduct   = opening_area > VOB_DEDUCTION_LIMIT

                avg_thickness = 0.20
                if walls:
                    thicknesses = [
                        get_wall_thickness(w["name"])
                        for w in walls
                        if w["type"] in ["structural", "drywall"]
                    ]
                    if thicknesses:
                        avg_thickness = sum(thicknesses) / len(thicknesses)

                reveal = 0.0
                if VOB_REVEAL_ENABLED:
                    perimeter_4sides = (2 * height_m) + (2 * width_m)
                    reveal = round(perimeter_4sides * avg_thickness, 2)

                window_list.append({
                    "name":         win["name"],
                    "width_m":      width_m,
                    "height_m":     height_m,
                    "opening_area": opening_area,
                    "vob_deduct":   vob_deduct,
                    "reveal_area":  reveal
                })

            window_count      = len(window_list)
            window_deductions = sum(w["opening_area"] for w in window_list if w["vob_deduct"])
            window_reveals    = sum(w["reveal_area"]  for w in window_list)
            window_detail     = "; ".join([
                f"{w['name']} {w['width_m']}×{w['height_m']}m"
                for w in window_list
            ])

            # ── Furniture ──
            furniture = session.run("""
                MATCH (s:Space {name: $id, user_id: $uid, project_id: $pid})
                      -[:HAS_FURNITURE]->
                      (f:Furniture {user_id: $uid, project_id: $pid})
                RETURN f.name AS name
            """, id=space_id, uid=user_id, pid=project_id).data()

            furniture_count = len(furniture)
            furniture_names = ", ".join([f["name"] for f in furniture])

            # ── VOB net ──
            total_deductions = door_deductions + window_deductions
            total_reveals    = door_reveals    + window_reveals
            net_paint_area   = round(
                structural_area - total_deductions + total_reveals, 2
            )

            rooms.append({
                "Nr":                  space_id,
                "Raum":                space_name,
                "Ebene":               space["floor"],
                "DIN 277 Typ":         din277_type,
                "NGF (m²)":            round(floor_area, 2),
                "Höhe (m)":            round(height, 2),
                "Volumen (m³)":        round(volume, 2),
                "Decke (m²)":          round(ceiling_area, 2),
                "Wand Brutto (m²)":    round(gross_wall, 2),
                "Abzüge VOB (m²)":     round(total_deductions, 2),
                "Laibungen + (m²)":    round(total_reveals, 2),
                "Anstrich Netto (m²)": net_paint_area,
                "Fliesen (m²)":        round(ceramic_area, 2),
                "Glas (m²)":           round(glass_area, 2),
                "Boden (m²)":          floor_area,
                "Sockelleiste (m)":    round(total_wall_length, 2),
                "Sockelleiste (m²)":   baseboard_area,
                "Türen Anz.":          door_count,
                "Türen Details":       door_detail,
                "Fenster Anz.":        window_count,
                "Fenster Details":     window_detail,
                "Möbel Anz.":          furniture_count,
                "Möbel Details":       furniture_names
            })

    return rooms


# ─────────────────────────────────────
# DIN 277 CLASSIFICATION
# ─────────────────────────────────────
def classify_din277(room_name):
    name = (room_name or "").lower()
    if any(x in name for x in ["bed", "schlaf", "wohn", "living", "kind", "gast", "zimmer"]):
        return "NUF 1 — Wohnen"
    elif any(x in name for x in ["kitchen", "küche", "kochen"]):
        return "NUF 6 — Kochen/Versorgen"
    elif any(x in name for x in ["bath", "bad", "dusch", "shower", "wc", "toilet", "sanitär"]):
        return "NUF 3 — Sanitär"
    elif any(x in name for x in ["flur", "korridor", "corridor", "hall", "diele", "foyer", "eingang"]):
        return "VF 1 — Verkehrsfläche"
    elif any(x in name for x in ["keller", "lager", "storage", "abstellraum"]):
        return "NUF 5 — Lagern"
    elif any(x in name for x in ["heizung", "technik", "hausan", "utility", "mechanical"]):
        return "TF 1 — Technik"
    else:
        return "NUF 1 — Wohnen"


# ─────────────────────────────────────
# PRINT RAUMBUCH
# ─────────────────────────────────────
def print_raumbuch(rooms):
    print("\n" + "=" * 80)
    print("RAUMBUCH — BIM NEXUS BUILDING")
    print("DIN 277 + VOB/C DIN 18363 (with reveals)")
    print("=" * 80)

    totals = {k: 0 for k in [
        "NGF (m²)", "Anstrich Netto (m²)", "Fliesen (m²)",
        "Glas (m²)", "Abzüge VOB (m²)", "Laibungen + (m²)", "Sockelleiste (m²)"
    ]}

    for r in rooms:
        print(f"\n┌─ Raum {r['Nr']}: {r['Raum']} ({r['Ebene']}) — {r['DIN 277 Typ']}")
        print(f"│  NGF: {r['NGF (m²)']} m²  Höhe: {r['Höhe (m)']} m  Vol: {r['Volumen (m³)']} m³")
        print(f"│  Wand Brutto: {r['Wand Brutto (m²)']} m²  "
              f"Abzüge: -{r['Abzüge VOB (m²)']} m²  "
              f"Laibungen: +{r['Laibungen + (m²)']} m²")
        print(f"│  Anstrich: {r['Anstrich Netto (m²)']} m²  "
              f"Fliesen: {r['Fliesen (m²)']} m²  "
              f"Glas: {r['Glas (m²)']} m²")
        print(f"│  Türen ({r['Türen Anz.']}): {r['Türen Details']}")
        print(f"│  Fenster ({r['Fenster Anz.']}): {r['Fenster Details']}")
        print(f"│  Möbel: {r['Möbel Anz.']} — {r['Möbel Details']}")
        print(f"└{'─' * 60}")
        for k in totals:
            totals[k] += r[k] or 0

    print(f"\n{'=' * 80}")
    print("GESAMT")
    for k, v in totals.items():
        print(f"  {k}: {round(v, 2)}")
    print("=" * 80)


# ─────────────────────────────────────
# EXPORT TO EXCEL
# ─────────────────────────────────────
def export_to_excel(rooms):
    df          = pd.DataFrame(rooms)
    output_path = "sample_data/raumbuch.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Raumbuch", index=False)

        summary = df.groupby("DIN 277 Typ").agg({
            "NGF (m²)":            "sum",
            "Anstrich Netto (m²)": "sum",
            "Fliesen (m²)":        "sum",
            "Glas (m²)":           "sum",
            "Türen Anz.":          "sum",
            "Fenster Anz.":        "sum",
        }).round(2)
        summary.to_excel(writer, sheet_name="DIN 277 Summary")

        trades = pd.DataFrame([
            {"Gewerk (Trade)": "Maler (Painter)",     "Beschreibung": "Wandanstrich Netto", "Menge": round(df["Anstrich Netto (m²)"].sum(), 2), "Einheit": "m²"},
            {"Gewerk (Trade)": "Fliesenleger (Tiler)", "Beschreibung": "Wandfliesen",        "Menge": round(df["Fliesen (m²)"].sum(), 2),        "Einheit": "m²"},
            {"Gewerk (Trade)": "Bodenleger (Floor)",   "Beschreibung": "Bodenbelag NGF",     "Menge": round(df["Boden (m²)"].sum(), 2),          "Einheit": "m²"},
            {"Gewerk (Trade)": "Decke (Ceiling)",      "Beschreibung": "Deckenanstrich",     "Menge": round(df["Decke (m²)"].sum(), 2),          "Einheit": "m²"},
            {"Gewerk (Trade)": "Schreiner (Joiner)",   "Beschreibung": "Sockelleiste",       "Menge": round(df["Sockelleiste (m)"].sum(), 2),    "Einheit": "m"},
            {"Gewerk (Trade)": "Glaser (Glazier)",     "Beschreibung": "Glasfläche",         "Menge": round(df["Glas (m²)"].sum(), 2),           "Einheit": "m²"},
        ])
        trades.to_excel(writer, sheet_name="Gewerk Mengen", index=False)

    print(f"\n✅ Raumbuch exported: {output_path}")
    return output_path


# ─────────────────────────────────────
# STANDALONE RUN
# ─────────────────────────────────────
if __name__ == "__main__":
    print("Generating Raumbuch (DIN 277 + VOB)...")
    rooms = generate_raumbuch()
    print_raumbuch(rooms)
    export_to_excel(rooms)
