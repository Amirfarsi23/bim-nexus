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
        print("✅ Building node created")

        # 2 - Floors linked to Building
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
        print(f"✅ {len(data['floors'])} floors linked to Building")

        # 3 - Spaces linked to Floor
        for space in data["spaces"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (s:Space {
                    guid:      $guid,
                    name:      $name,
                    long_name: $long_name,
                    area:      $area
                })
                CREATE (f)-[:CONTAINS]->(s)
            """, guid=space["guid"],
                name=space["name"],
                long_name=space["long_name"],
                area=space["area"])
        print(f"✅ {len(data['spaces'])} spaces linked to Floor")

        # 4 - Walls linked to Floor
        for wall in data["walls"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (w:Wall {
                    guid:        $guid,
                    name:        $name,
                    is_external: $is_external
                })
                CREATE (f)-[:HAS_WALL]->(w)
            """, guid=wall["guid"],
                name=wall["name"],
                is_external=wall["is_external"])
        print(f"✅ {len(data['walls'])} walls linked to Floor")

        # 5 - Doors linked to Floor
        for door in data["doors"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (d:Door {
                    guid:   $guid,
                    name:   $name,
                    width:  $width,
                    height: $height
                })
                CREATE (f)-[:HAS_DOOR]->(d)
            """, guid=door["guid"],
                name=door["name"],
                width=door["width"],
                height=door["height"])
        print(f"✅ {len(data['doors'])} doors linked to Floor")

        # 6 - Windows linked to Floor
        for window in data["windows"]:
            session.run("""
                MATCH (f:Floor)
                CREATE (w:Window {
                    guid:   $guid,
                    name:   $name,
                    width:  $width,
                    height: $height
                })
                CREATE (f)-[:HAS_WINDOW]->(w)
            """, guid=window["guid"],
                name=window["name"],
                width=window["width"],
                height=window["height"])
        print(f"✅ {len(data['windows'])} windows linked to Floor")

        # 7 - Wall BOUNDS Space
        for b in data["boundaries"]:
            session.run("""
                MATCH (w:Wall {guid: $wall_guid})
                MATCH (s:Space {name: $space_name})
                MERGE (w)-[:BOUNDS]->(s)
            """, wall_guid=b["wall_guid"],
                space_name=b["space_name"])
        print(f"✅ {len(data['boundaries'])} wall-space boundaries created")

        # 8 - Door OPENS_INTO Space
        for b in data["door_boundaries"]:
            session.run("""
                MATCH (d:Door {guid: $door_guid})
                MATCH (s:Space {name: $space_name})
                MERGE (d)-[:OPENS_INTO]->(s)
            """, door_guid=b["door_guid"],
                space_name=b["space_name"])
        print(f"✅ {len(data['door_boundaries'])} door-space links created")

        # 9 - Window BELONGS_TO Space
        for b in data["window_boundaries"]:
            session.run("""
                MATCH (w:Window {guid: $window_guid})
                MATCH (s:Space {name: $space_name})
                MERGE (w)-[:BELONGS_TO]->(s)
            """, window_guid=b["window_guid"],
                space_name=b["space_name"])
        print(f"✅ {len(data['window_boundaries'])} window-space links created")

    print("\n✅ Full building graph with all relationships stored!")
    driver.close()


if __name__ == "__main__":
    from ifc_parser import parse_ifc
    data = parse_ifc("sample_data/bimnexus.ifc")
    store_building(data)