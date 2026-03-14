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

VOB_DEDUCTION_LIMIT = 2.5  # m² — VOB rule


def generate_raumbuch():
    rooms = []

    with driver.session() as session:

        # Get all spaces
        spaces = session.run("""
            MATCH (f:Floor)-[:CONTAINS]->(s:Space)
            RETURN s.name AS id,
                   s.long_name AS name,
                   f.name AS floor,
                   s.area AS area,
                   s.height AS height,
                   s.volume AS volume
            ORDER BY s.name
        """).data()

        for space in spaces:
            space_id   = space["id"]
            space_name = space["name"]

            # --- WALLS per type ---
            walls = session.run("""
                MATCH (w:Wall)-[b:BOUNDS]->(s:Space {name: $id})
                RETURN w.wall_type AS type,
                       w.name AS name,
                       b.area AS area,
                       b.length AS length,
                       b.height AS height
            """, id=space_id).data()

            # Classify wall areas
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
                MATCH (d:Door)-[r:OPENS_INTO]->(s:Space {name: $id})
                RETURN d.name AS name,
                       d.width AS width,
                       d.height AS height,
                       r.area AS area
            """, id=space_id).data()

            door_count      = len(doors)
            door_deductions = sum(
                d["area"] for d in doors
                if d["area"] and d["area"] > VOB_DEDUCTION_LIMIT
            )

            # --- WINDOWS ---
            windows = session.run("""
                MATCH (w:Window)-[r:BELONGS_TO]->(s:Space {name: $id})
                RETURN w.name AS name,
                       w.width AS width,
                       w.height AS height,
                       r.area AS area
            """, id=space_id).data()

            window_count      = len(windows)
            window_deductions = sum(
                w["area"] for w in windows
                if w["area"] and w["area"] > VOB_DEDUCTION_LIMIT
            )

            # --- FURNITURE ---
            furniture = session.run("""
                MATCH (s:Space {long_name: $name})-[:HAS_FURNITURE]->(f:Furniture)
                RETURN f.name AS name
            """, name=space_name).data()

            furniture_count = len(furniture)
            furniture_names = ", ".join([f["name"] for f in furniture])

            # --- CALCULATIONS ---
            floor_area   = space["area"]  or 0
            height       = space["height"] or 0
            volume       = round(floor_area * height, 2) if floor_area and height else 0
            ceiling_area = floor_area

            # Net painting area (VOB deductions)
            net_paint_area = round(
                structural_area - door_deductions - window_deductions, 2
            )

            # Total wall area gross
            total_deductions = round(door_deductions + window_deductions, 2)

            rooms.append({
                "Nr":               space_id,
                "Raum":             space_name,
                "Ebene":            space["floor"],
                "NGF (m²)":         floor_area,
                "Höhe (m)":         height,
                "Volumen (m³)":     volume,
                "Wand Brutto (m²)": round(gross_wall, 2),
                "Abzüge (m²)":      total_deductions,
                "Anstrich (m²)":    net_paint_area,
                "Fliesen (m²)":     round(ceramic_area, 2),
                "Glas (m²)":        round(glass_area, 2),
                "Decke (m²)":       ceiling_area,
                "Türen":            door_count,
                "Fenster":          window_count,
                "Möbel":            furniture_count,
                "Ausstattung":      furniture_names
            })

    return rooms


def print_raumbuch(rooms):
    print("\n" + "="*80)
    print("RAUMBUCH — BIM NEXUS BUILDING")
    print("="*80)

    total_ngf    = 0
    total_paint  = 0
    total_ceramic = 0
    total_glass  = 0

    for r in rooms:
        print(f"\n┌─ Raum {r['Nr']}: {r['Raum']} ({r['Ebene']})")
        print(f"│  NGF: {r['NGF (m²)']} m²  │  Höhe: {r['Höhe (m)']} m  │  Volumen: {r['Volumen (m³)']} m³")
        print(f"│")
        print(f"│  BODEN + DECKE")
        print(f"│    Bodenfläche:  {r['NGF (m²)']} m²")
        print(f"│    Deckenfläche: {r['Decke (m²)']} m²")
        print(f"│")
        print(f"│  WANDFLÄCHEN")
        print(f"│    Brutto:       {r['Wand Brutto (m²)']} m²")
        print(f"│    Abzüge (VOB): {r['Abzüge (m²)']} m²")
        print(f"│    Anstrich:     {r['Anstrich (m²)']} m²")
        print(f"│    Fliesen:      {r['Fliesen (m²)']} m²")
        print(f"│    Glasfläche:   {r['Glas (m²)']} m²")
        print(f"│")
        print(f"│  ÖFFNUNGEN")
        print(f"│    Türen:        {r['Türen']}")
        print(f"│    Fenster:      {r['Fenster']}")
        print(f"│")
        print(f"│  AUSSTATTUNG")
        print(f"│    Möbel:        {r['Möbel']} items")
        if r['Ausstattung']:
            print(f"│    Details:      {r['Ausstattung']}")
        print(f"└{'─'*50}")

        total_ngf     += r["NGF (m²)"]     or 0
        total_paint   += r["Anstrich (m²)"] or 0
        total_ceramic += r["Fliesen (m²)"]  or 0
        total_glass   += r["Glas (m²)"]     or 0

    print(f"\n{'='*80}")
    print(f"GESAMT (TOTAL)")
    print(f"  Gesamtfläche NGF:  {round(total_ngf,2)} m²")
    print(f"  Anstrich gesamt:   {round(total_paint,2)} m²")
    print(f"  Fliesen gesamt:    {round(total_ceramic,2)} m²")
    print(f"  Glasfläche gesamt: {round(total_glass,2)} m²")
    print(f"{'='*80}")


def export_to_excel(rooms):
    df = pd.DataFrame(rooms)
    output_path = "sample_data/raumbuch.xlsx"
    df.to_excel(output_path, index=False)
    print(f"\n✅ Raumbuch exported to: {output_path}")
    return output_path


if __name__ == "__main__":
    print("Generating Raumbuch...")
    rooms = generate_raumbuch()
    print_raumbuch(rooms)
    export_to_excel(rooms)