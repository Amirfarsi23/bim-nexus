from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"),
          os.getenv("NEO4J_PASSWORD"))
)


def clear_database():
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("✅ Database cleared")


def store_building(data):
    clear_database()

    with driver.session() as session:

        # 1 - Building
        session.run("""
            CREATE (b:Building {name: 'BIM Nexus Building'})
        """)
        print("✅ Building created")

        # 2 - Floor linked to Building
        for floor in data["floors"]:
            session.run("""
                MATCH (b:Building)
                CREATE (f:Floor {
                    guid:  $guid,
                    name:  $name,
                    level: $level
                })
                CREATE (b)-[:HAS_FLOOR]->(f)
            """, guid=floor["guid"],
                name=floor["name"],
                level=floor["level"])
        print(f"✅ {len(data['floors'])} floors linked")

        # 3 - Spaces linked to Floor
        for space in data["spaces"]:
            volume = None
            if space["area"] and space["height"]:
                volume = round(space["area"] * space["height"], 2)
            session.run("""
                MATCH (f:Floor)
                CREATE (s:Space {
                    guid:      $guid,
                    name:      $name,
                    long_name: $long_name,
                    area:      $area,
                    height:    $height,
                    volume:    $volume
                })
                CREATE (f)-[:CONTAINS]->(s)
            """, guid=space["guid"],
                name=space["name"],
                long_name=space["long_name"],
                area=space["area"],
                height=space["height"],
                volume=volume)
        print(f"✅ {len(data['spaces'])} spaces linked")

        # 4 - Walls linked to Floor
        for wall in data["walls"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (w:Wall {
                    guid:        $guid,
                    name:        $name,
                    is_external: $is_external,
                    material:    $material,
                    wall_type:   $wall_type
                })
                CREATE (f)-[:HAS_WALL]->(w)
            """, guid=wall["guid"],
                name=wall["name"],
                is_external=wall["is_external"],
                material=wall["material"],
                wall_type=wall["wall_type"])
        print(f"✅ {len(data['walls'])} walls linked")

        # 5 - Doors linked to Floor
        for door in data["doors"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (d:Door {
                    guid:   $guid,
                    name:   $name,
                    width:  $width,
                    height: $height,
                    area:   $area
                })
                CREATE (f)-[:HAS_DOOR]->(d)
            """, guid=door["guid"],
                name=door["name"],
                width=door["width"],
                height=door["height"],
                area=door["area"])
        print(f"✅ {len(data['doors'])} doors linked")

        # 6 - Windows linked to Floor
        for window in data["windows"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (w:Window {
                    guid:   $guid,
                    name:   $name,
                    width:  $width,
                    height: $height,
                    area:   $area
                })
                CREATE (f)-[:HAS_WINDOW]->(w)
            """, guid=window["guid"],
                name=window["name"],
                width=window["width"],
                height=window["height"],
                area=window["area"])
        print(f"✅ {len(data['windows'])} windows linked")

        # 7 - Furniture linked to Space
        for item in data["furniture"]:
            if item["space_name"]:
                session.run("""
                    MATCH (s:Space {long_name: $space_name})
                    CREATE (furn:Furniture {
                        guid: $guid,
                        name: $name
                    })
                    CREATE (s)-[:HAS_FURNITURE]->(furn)
                """, guid=item["guid"],
                    name=item["name"],
                    space_name=item["space_name"])
        print(f"✅ {len(data['furniture'])} furniture linked")

        # 8 - Wall BOUNDS Space with area
        for b in data["boundaries"]:
            session.run("""
                MATCH (w:Wall {guid: $wall_guid})
                MATCH (s:Space {name: $space_name})
                MERGE (w)-[:BOUNDS {
                    area:      $area,
                    length:    $length,
                    height:    $height,
                    wall_type: $wall_type
                }]->(s)
            """, wall_guid=b["wall_guid"],
                space_name=b["space_name"],
                area=b["area"],
                length=b["length"],
                height=b["height"],
                wall_type=b["wall_type"])
        print(f"✅ {len(data['boundaries'])} wall boundaries created")

        # 9 - Door OPENS_INTO Space
        for b in data["door_boundaries"]:
            session.run("""
                MATCH (d:Door {guid: $door_guid})
                MATCH (s:Space {name: $space_name})
                MERGE (d)-[:OPENS_INTO {area: $area}]->(s)
            """, door_guid=b["door_guid"],
                space_name=b["space_name"],
                area=b["area"])
        print(f"✅ {len(data['door_boundaries'])} door links created")


        # 10 - Window BELONGS_TO Space
        for b in data["window_boundaries"]:
            session.run("""
                        MATCH (w:Window {guid: $window_guid})
                        MATCH (s:Space {name: $space_name})
                        MERGE (w)-[:BELONGS_TO {area: $area}]->(s)
                    """, window_guid=b["window_guid"],
                        space_name=b["space_name"],
                        area=b["area"])
        print(f"✅ {len(data['window_boundaries'])} window links created")

    print("\n✅ Full building graph stored!")
    driver.close()


if __name__ == "__main__":
    from ifc_parser import parse_ifc
    data = parse_ifc("sample_data/bimnexus.ifc")
    store_building(data)