from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"),
          os.getenv("NEO4J_PASSWORD"))
)


def clear_user_project(user_id, project_id):
    """Delete ONLY this user's specific project. Never touches other users."""
    with driver.session() as session:
        session.run("""
            MATCH (n {user_id: $uid, project_id: $pid})
            DETACH DELETE n
        """, uid=user_id, pid=project_id)
    print(f"✅ Cleared project '{project_id}' for user '{user_id}'")


def store_building(data, user_id, project_id):
    clear_user_project(user_id, project_id)

    with driver.session() as session:

        # 1 — Building
        session.run("""
            CREATE (b:Building {
                name:       'BIM Nexus Building',
                user_id:    $uid,
                project_id: $pid
            })
        """, uid=user_id, pid=project_id)
        print("✅ Building created")

        # 2 — Floors
        for floor in data["floors"]:
            session.run("""
                MATCH (b:Building {user_id: $uid, project_id: $pid})
                CREATE (f:Floor {
                    guid:       $guid,
                    name:       $name,
                    level:      $level,
                    user_id:    $uid,
                    project_id: $pid
                })
                CREATE (b)-[:HAS_FLOOR]->(f)
            """, guid=floor["guid"], name=floor["name"],
                level=floor["level"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['floors'])} floors linked")

        # 3 — Spaces
        for space in data["spaces"]:
            volume = None
            if space["area"] and space["height"]:
                volume = round(space["area"] * space["height"], 2)
            session.run("""
                MATCH (f:Floor {user_id: $uid, project_id: $pid})
                CREATE (s:Space {
                    guid:       $guid,
                    name:       $name,
                    long_name:  $long_name,
                    area:       $area,
                    height:     $height,
                    volume:     $volume,
                    user_id:    $uid,
                    project_id: $pid
                })
                CREATE (f)-[:CONTAINS]->(s)
            """, guid=space["guid"], name=space["name"],
                long_name=space["long_name"], area=space["area"],
                height=space["height"], volume=volume,
                uid=user_id, pid=project_id)
        print(f"✅ {len(data['spaces'])} spaces linked")

        # 4 — Walls
        for wall in data["walls"]:
            session.run("""
                MATCH (f:Floor {user_id: $uid, project_id: $pid})
                CREATE (w:Wall {
                    guid:        $guid,
                    name:        $name,
                    is_external: $is_external,
                    material:    $material,
                    wall_type:   $wall_type,
                    user_id:     $uid,
                    project_id:  $pid
                })
                CREATE (f)-[:HAS_WALL]->(w)
            """, guid=wall["guid"], name=wall["name"],
                is_external=wall["is_external"], material=wall["material"],
                wall_type=wall["wall_type"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['walls'])} walls linked")

        # 5 — Doors
        for door in data["doors"]:
            session.run("""
                MATCH (f:Floor {user_id: $uid, project_id: $pid})
                CREATE (d:Door {
                    guid:       $guid,
                    name:       $name,
                    width:      $width,
                    height:     $height,
                    area:       $area,
                    user_id:    $uid,
                    project_id: $pid
                })
                CREATE (f)-[:HAS_DOOR]->(d)
            """, guid=door["guid"], name=door["name"],
                width=door["width"], height=door["height"],
                area=door["area"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['doors'])} doors linked")

        # 6 — Windows
        for window in data["windows"]:
            session.run("""
                MATCH (f:Floor {user_id: $uid, project_id: $pid})
                CREATE (w:Window {
                    guid:       $guid,
                    name:       $name,
                    width:      $width,
                    height:     $height,
                    area:       $area,
                    user_id:    $uid,
                    project_id: $pid
                })
                CREATE (f)-[:HAS_WINDOW]->(w)
            """, guid=window["guid"], name=window["name"],
                width=window["width"], height=window["height"],
                area=window["area"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['windows'])} windows linked")

        # 7 — Furniture
        for item in data["furniture"]:
            if item["space_name"]:
                session.run("""
                    MATCH (s:Space {
                        long_name:  $space_name,
                        user_id:    $uid,
                        project_id: $pid
                    })
                    CREATE (furn:Furniture {
                        guid:       $guid,
                        name:       $name,
                        user_id:    $uid,
                        project_id: $pid
                    })
                    CREATE (s)-[:HAS_FURNITURE]->(furn)
                """, guid=item["guid"], name=item["name"],
                    space_name=item["space_name"],
                    uid=user_id, pid=project_id)
        print(f"✅ {len(data['furniture'])} furniture linked")

        # 8 — Wall BOUNDS Space
        for b in data["boundaries"]:
            session.run("""
                MATCH (w:Wall {guid: $wall_guid, user_id: $uid, project_id: $pid})
                MATCH (s:Space {name: $space_name, user_id: $uid, project_id: $pid})
                MERGE (w)-[:BOUNDS {
                    area:      $area,
                    length:    $length,
                    height:    $height,
                    wall_type: $wall_type
                }]->(s)
            """, wall_guid=b["wall_guid"], space_name=b["space_name"],
                area=b["area"], length=b["length"], height=b["height"],
                wall_type=b["wall_type"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['boundaries'])} wall boundaries created")

        # 9 — Door OPENS_INTO Space
        for b in data["door_boundaries"]:
            session.run("""
                MATCH (d:Door {guid: $door_guid, user_id: $uid, project_id: $pid})
                MATCH (s:Space {name: $space_name, user_id: $uid, project_id: $pid})
                MERGE (d)-[:OPENS_INTO {area: $area}]->(s)
            """, door_guid=b["door_guid"], space_name=b["space_name"],
                area=b["area"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['door_boundaries'])} door links created")

        # 10 — Window BELONGS_TO Space
        for b in data["window_boundaries"]:
            session.run("""
                MATCH (w:Window {guid: $window_guid, user_id: $uid, project_id: $pid})
                MATCH (s:Space {name: $space_name, user_id: $uid, project_id: $pid})
                MERGE (w)-[:BELONGS_TO {area: $area}]->(s)
            """, window_guid=b["window_guid"], space_name=b["space_name"],
                area=b["area"], uid=user_id, pid=project_id)
        print(f"✅ {len(data['window_boundaries'])} window links created")

    # NOTE: do NOT call driver.close() here — driver stays open for app lifetime
    print(f"\n✅ Building stored for user='{user_id}', project='{project_id}'")


def get_user_projects(user_id):
    """Return all projects belonging to a user."""
    with driver.session() as session:
        result = session.run("""
            MATCH (b:Building {user_id: $uid})
            RETURN b.project_id AS project_id,
                   b.name       AS name
        """, uid=user_id).data()
    return result


def delete_user_project(user_id, project_id):
    """Fully delete one project for a user."""
    clear_user_project(user_id, project_id)


if __name__ == "__main__":
    from ifc_parser import parse_ifc
    data = parse_ifc("sample_data/bimnexus.ifc")
    store_building(data, user_id="test_user", project_id="test_project")
