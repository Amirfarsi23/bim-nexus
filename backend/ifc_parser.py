import ifcopenshell
import ifcopenshell.util.element as util


def parse_ifc(file_path):
    print(f"Opening IFC file: {file_path}")
    model = ifcopenshell.open(file_path)

    data = {
        "floors":            extract_floors(model),
        "spaces":            extract_spaces(model),
        "walls":             extract_walls(model),
        "doors":             extract_doors(model),
        "windows":           extract_windows(model),
        "boundaries":        extract_wall_boundaries(model),
        "door_boundaries":   extract_door_boundaries(model),
        "window_boundaries": extract_window_boundaries(model),
    }

    print(f"✅ Found {len(data['floors'])} floors")
    print(f"✅ Found {len(data['spaces'])} spaces")
    print(f"✅ Found {len(data['walls'])} walls")
    print(f"✅ Found {len(data['doors'])} doors")
    print(f"✅ Found {len(data['windows'])} windows")
    print(f"✅ Found {len(data['boundaries'])} wall-space boundaries")
    print(f"✅ Found {len(data['door_boundaries'])} door-space boundaries")
    print(f"✅ Found {len(data['window_boundaries'])} window-space boundaries")
    return data


def extract_floors(model):
    floors = []
    for floor in model.by_type("IfcBuildingStorey"):
        floors.append({
            "guid":  floor.GlobalId,
            "name":  floor.Name,
            "level": floor.Elevation if floor.Elevation else 0
        })
    return floors


def extract_spaces(model):
    spaces = []
    for space in model.by_type("IfcSpace"):
        psets = util.get_psets(space)
        area = None
        for pset in psets.values():
            if "NetFloorArea" in pset:
                area = pset["NetFloorArea"]
        spaces.append({
            "guid":      space.GlobalId,
            "name":      space.Name,
            "long_name": space.LongName if space.LongName else space.Name,
            "area":      area
        })
    return spaces


def extract_walls(model):
    walls = []
    seen = set()
    for wall in model.by_type("IfcWallStandardCase"):
        if wall.GlobalId in seen:
            continue
        seen.add(wall.GlobalId)
        psets = util.get_psets(wall)
        is_external = False
        for pset in psets.values():
            if "IsExternal" in pset:
                is_external = pset["IsExternal"]
        walls.append({
            "guid":        wall.GlobalId,
            "name":        wall.Name,
            "is_external": is_external
        })
    return walls


def extract_doors(model):
    doors = []
    for door in model.by_type("IfcDoor"):
        doors.append({
            "guid":   door.GlobalId,
            "name":   door.Name,
            "width":  door.OverallWidth,
            "height": door.OverallHeight
        })
    return doors


def extract_windows(model):
    windows = []
    for window in model.by_type("IfcWindow"):
        windows.append({
            "guid":   window.GlobalId,
            "name":   window.Name,
            "width":  window.OverallWidth,
            "height": window.OverallHeight
        })
    return windows


def extract_wall_boundaries(model):
    bounds = []
    seen = set()
    for b in model.by_type("IfcRelSpaceBoundary"):
        elem = b.RelatedBuildingElement
        space = b.RelatingSpace
        if not elem or not space:
            continue
        if not elem.is_a("IfcWallStandardCase"):
            continue
        key = (elem.GlobalId, space.Name)
        if key in seen:
            continue
        seen.add(key)
        bounds.append({
            "wall_guid":  elem.GlobalId,
            "space_name": space.Name
        })
    return bounds


def extract_door_boundaries(model):
    bounds = []
    seen = set()
    for b in model.by_type("IfcRelSpaceBoundary"):
        elem = b.RelatedBuildingElement
        space = b.RelatingSpace
        if not elem or not space:
            continue
        if not elem.is_a("IfcDoor"):
            continue
        key = (elem.GlobalId, space.Name)
        if key in seen:
            continue
        seen.add(key)
        bounds.append({
            "door_guid":  elem.GlobalId,
            "space_name": space.Name
        })
    return bounds


def extract_window_boundaries(model):
    bounds = []
    seen = set()
    for b in model.by_type("IfcRelSpaceBoundary"):
        elem = b.RelatedBuildingElement
        space = b.RelatingSpace
        if not elem or not space:
            continue
        if not elem.is_a("IfcWindow"):
            continue
        key = (elem.GlobalId, space.Name)
        if key in seen:
            continue
        seen.add(key)
        bounds.append({
            "window_guid": elem.GlobalId,
            "space_name":  space.Name
        })
    return bounds


if __name__ == "__main__":
    data = parse_ifc("sample_data/bimnexus.ifc")
    print("\n✅ IFC Parsing Complete!")