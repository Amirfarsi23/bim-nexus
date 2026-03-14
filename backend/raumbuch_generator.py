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

VOB_DEDUCTION_LIMIT = 2.5  # m²


def generate_raumbuch():
    rooms = []

    with driver.session() as session:

        spaces = session.run("""
            MATCH (f:Floor)-[:CONTAINS]->(s:Space)
            RETURN s.name    AS id,
                   s.long_name AS name,
                   f.name    AS floor,
                   s.area    AS area,
                   s.height  AS height,
                   s.volume  AS volume
            ORDER BY s.name
        """).data()

        for space in spaces:
            space_id   = space["id"]
            space_name = space["name"]

            # Define floor_area FIRST
            floor_area   = space["area"]  or 0
            height       = space["height"] or 0
            volume       = round(floor_area * height, 2)
            ceiling_area = floor_area

            # --- WALLS ---
            walls = session.run("""
                MATCH (w:Wall)-[b:BOUNDS]->(s:Space {name: $id})
                RETURN w.wall_type AS type,
                       w.name     AS name,
                       b.area     AS area
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

            # --- DOORS ---
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
                # Convert mm to m if needed
                if w > 100:
                    width_m  = round(w / 1000, 2)
                    height_m = round(h / 1000, 2)
                else:
                    width_m  = round(w, 2)
                    height_m = round(h, 2)
                area = round(width_m * height_m, 2)

                # Check if current room is corridor
                # (bigger room = corridor side = no deduction)
                other_spaces = session.run("""
                    MATCH (d:Door {guid: $guid})
                          -[:OPENS_INTO]->(s:Space)
                    WHERE s.name <> $current_id
                    RETURN s.area AS other_area
                """, guid=d["guid"],
                    current_id=space_id).data()

                is_corridor = False
                for other in other_spaces:
                    other_area = other["other_area"] or 0
                    if floor_area > other_area:
                        is_corridor = True
                        break

                door_list.append({
                    "name":        d["name"],
                    "width_m":     width_m,
                    "height_m":    height_m,
                    "area":        area,
                    "is_corridor": is_corridor
                })

            door_count      = len(door_list)
            door_deductions = sum(
                d["area"] for d in door_list
                if d["area"] > VOB_DEDUCTION_LIMIT
                and not d["is_corridor"]
            )

            # --- WINDOWS ---
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
                    width_m  = round(w / 1000, 2)
                    height_m = round(h / 1000, 2)
                else:
                    width_m  = round(w, 2)
                    height_m = round(h, 2)
                area = round(width_m * height_m, 2)
                window_list.append({
                    "name":     win["name"],
                    "width_m":  width_m,
                    "height_m": height_m,
                    "area":     area
                })

            window_count      = len(window_list)
            window_deductions = sum(
                w["area"] for w in window_list
                if w["area"] > VOB_DEDUCTION_LIMIT
            )

            # --- FURNITURE ---
            furniture = session.run("""
                MATCH (s:Space {long_name: $name})
                      -[:HAS_FURNITURE]->(f:Furniture)
                RETURN f.name AS name
            """, name=space_name).data()

            furniture_count = len(furniture)
            furniture_names = ", ".join([
                f["name"] for f in furniture
            ])

            # --- FINAL CALCULATIONS ---
            total_deductions = round(
                door_deductions + window_deductions, 2
            )
            net_paint_area = round(
                structural_area - total_deductions, 2
            )

            # Door details
            door_details = ", ".join([
                f"{d['name'][-15:]} "
                f"({d['width_m']}×{d['height_m']}m"
                f"={d['area']}m²"
                f"{' [Korridor]' if d['is_corridor'] else ' [Abzug]'})"
                for d in door_list
            ])

            # Window details
            window_details = ", ".join([
                f"{w['name'][-15:]} "
                f"({w['width_m']}×{w['height_m']}m={w['area']}m²)"
                for w in window_list
            ])

            rooms.append({
                "Nr":               space_id,
                "Raum":             space_name,
                "Ebene":            space["floor"],
                "NGF (m²)":         floor_area,
                "Höhe (m)":         height,
                "Volumen (m³)":     volume,
                "Wand Brutto (m²)": round(gross_wall, 2),
                "Abzüge VOB (m²)":  total_deductions,
                "Anstrich (m²)":    net_paint_area,
                "Fliesen (m²)":     round(ceramic_area, 2),
                "Glas (m²)":        round(glass_area, 2),
                "Decke (m²)":       ceiling_area,
                "Türen Anz.":       door_count,
                "Türen Details":    door_details,
                "Fenster Anz.":     window_count,
                "Fenster Details":  window_details,
                "Möbel Anz.":       furniture_count,
                "Möbel Details":    furniture_names
            })

    return rooms


def print_raumbuch(rooms):
    print("\n" + "="*80)
    print("RAUMBUCH — BIM NEXUS BUILDING")
    print("="*80)

    total_ngf     = 0
    total_paint   = 0
    total_ceramic = 0
    total_glass   = 0
    total_deduct  = 0

    for r in rooms:
        print(f"\n┌─ Raum {r['Nr']}: {r['Raum']} ({r['Ebene']})")
        print(f"│  NGF: {r['NGF (m²)']} m²  │  "
              f"Höhe: {r['Höhe (m)']} m  │  "
              f"Volumen: {r['Volumen (m³)']} m³")
        print(f"│")
        print(f"│  BODEN + DECKE")
        print(f"│    Bodenfläche:  {r['NGF (m²)']} m²")
        print(f"│    Deckenfläche: {r['Decke (m²)']} m²")
        print(f"│")
        print(f"│  WANDFLÄCHEN")
        print(f"│    Brutto:       {r['Wand Brutto (m²)']} m²")
        print(f"│    Abzüge (VOB): {r['Abzüge VOB (m²)']} m²")
        print(f"│    Anstrich:     {r['Anstrich (m²)']} m²")
        print(f"│    Fliesen:      {r['Fliesen (m²)']} m²")
        print(f"│    Glasfläche:   {r['Glas (m²)']} m²")
        print(f"│")
        print(f"│  ÖFFNUNGEN")
        print(f"│    Türen ({r['Türen Anz.']}):   {r['Türen Details']}")
        print(f"│    Fenster ({r['Fenster Anz.']}): {r['Fenster Details']}")
        print(f"│")
        print(f"│  AUSSTATTUNG")
        print(f"│    Möbel: {r['Möbel Anz.']} items")
        if r["Möbel Details"]:
            print(f"│    Details: {r['Möbel Details']}")
        print(f"└{'─'*60}")

        total_ngf     += r["NGF (m²)"]        or 0
        total_paint   += r["Anstrich (m²)"]   or 0
        total_ceramic += r["Fliesen (m²)"]    or 0
        total_glass   += r["Glas (m²)"]       or 0
        total_deduct  += r["Abzüge VOB (m²)"] or 0

    print(f"\n{'='*80}")
    print(f"GESAMT (TOTAL)")
    print(f"  Gesamtfläche NGF:  {round(total_ngf,2)} m²")
    print(f"  Anstrich gesamt:   {round(total_paint,2)} m²")
    print(f"  VOB Abzüge:        {round(total_deduct,2)} m²")
    print(f"  Fliesen gesamt:    {round(total_ceramic,2)} m²")
    print(f"  Glasfläche gesamt: {round(total_glass,2)} m²")
    print(f"{'='*80}")


def export_to_excel(rooms):
    df          = pd.DataFrame(rooms)
    output_path = "sample_data/raumbuch.xlsx"
    df.to_excel(output_path, index=False)
    print(f"\n✅ Raumbuch exported: {output_path}")
    return output_path


if __name__ == "__main__":
    print("Generating Raumbuch...")
    rooms = generate_raumbuch()
    print_raumbuch(rooms)
    export_to_excel(rooms)