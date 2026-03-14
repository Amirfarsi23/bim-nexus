import ifcopenshell
import ifcopenshell.util.element as util
import math


def parse_ifc(file_path):
    print(f"Opening IFC file: {file_path}")
    model = ifcopenshell.open(file_path)

    data = {
        "floors":            extract_floors(model),
        "spaces":            extract_spaces(model),
        "walls":             extract_walls(model),
        "doors":             extract_doors(model),
        "windows":           extract_windows(model),
        "furniture":         extract_furniture(model),
        "boundaries":        extract_wall_boundaries(model),
        "door_boundaries":   extract_door_boundaries(model),
        "window_boundaries": extract_window_boundaries(model),
    }

    print(f"✅ Found {len(data['floors'])} floors")
    print(f"✅ Found {len(data['spaces'])} spaces")
    print(f"✅ Found {len(data['walls'])} walls")
    print(f"✅ Found {len(data['doors'])} doors")
    print(f"✅ Found {len(data['windows'])} windows")
    print(f"✅ Found {len(data['furniture'])} furniture items")
    print(f"✅ Found {len(data['boundaries'])} wall-space boundaries")
    print(f"✅ Found {len(data['door_boundaries'])} door-space boundaries")
    print(f"✅ Found {len(data['window_boundaries'])} window-space boundaries")
    return data


def extract_floors(model):
    floors = []
    for floor in model.by_type("IfcBuildingStorey"):
        floors.append({
            "guid":      floor.GlobalId,
            "name":      floor.Name,
            "level":     floor.Elevation if floor.Elevation else 0
        })
    return floors


def extract_spaces(model):
    spaces = []
    for space in model.by_type("IfcSpace"):
        psets = util.get_psets(space)
        area   = None
        height = None
        for pset in psets.values():
            if "NetFloorArea"       in pset: area   = round(pset["NetFloorArea"], 2)
            if "FinishCeilingHeight" in pset: height = pset["FinishCeilingHeight"]
            if "Height"             in pset: height = pset["Height"]
        spaces.append({
            "guid":      space.GlobalId,
            "name":      space.Name,
            "long_name": space.LongName if space.LongName else space.Name,
            "area":      area,
            "height":    height
        })
    return spaces


def extract_walls(model):
    walls = []
    seen  = set()
    for wall in model.by_type("IfcWallStandardCase"):
        if wall.GlobalId in seen:
            continue
        seen.add(wall.GlobalId)
        psets       = util.get_psets(wall)
        is_external = False
        for pset in psets.values():
            if "IsExternal" in pset:
                is_external = pset["IsExternal"]

        # Get material
        mat      = util.get_material(wall)
        material = None
        if mat:
            if hasattr(mat, "Name"):
                material = mat.Name
            elif hasattr(mat, "ForLayerSet"):
                layers   = mat.ForLayerSet.MaterialLayers
                material = " | ".join([
                    f"{l.Material.Name}:{round(l.LayerThickness,1)}mm"
                    for l in layers if l.Material
                ])

        # Detect wall type from name
        wall_type = detect_wall_type(wall.Name)

        walls.append({
            "guid":        wall.GlobalId,
            "name":        wall.Name,
            "is_external": is_external,
            "material":    material,
            "wall_type":   wall_type
        })
    return walls


def detect_wall_type(wall_name):
    name = wall_name.lower()
    if "ceramic" in name or "fliese" in name or "tile" in name:
        return "ceramic"
    elif "glas"  in name or "glass" in name:
        return "glass"
    elif "paint" in name or "anstrich" in name or "farbe" in name:
        return "paint"
    elif "gk"    in name or "gips"   in name or "trockenbau" in name:
        return "drywall"
    elif "ziegel" in name or "beton" in name or "concrete" in name:
        return "structural"
    else:
        return "general"


def extract_doors(model):
    doors = []
    for door in model.by_type("IfcDoor"):
        width  = door.OverallWidth  if door.OverallWidth  else 0
        height = door.OverallHeight if door.OverallHeight else 0
        area   = round((width * height) / 1e6, 2) if width and height else 0
        doors.append({
            "guid":   door.GlobalId,
            "name":   door.Name,
            "width":  width,
            "height": height,
            "area":   area
        })
    return doors


def extract_windows(model):
    windows = []
    for window in model.by_type("IfcWindow"):
        width  = window.OverallWidth  if window.OverallWidth  else 0
        height = window.OverallHeight if window.OverallHeight else 0
        area   = round((width * height) / 1e6, 2) if width and height else 0
        windows.append({
            "guid":   window.GlobalId,
            "name":   window.Name,
            "width":  width,
            "height": height,
            "area":   area
        })
    return windows


def extract_furniture(model):
    furniture = []
    for item in model.by_type("IfcFurnishingElement"):
        # Find which space contains this furniture
        space_name = None
        for rel in model.by_type("IfcRelContainedInSpatialStructure"):
            if item in rel.RelatedElements:
                container = rel.RelatingStructure
                if container.is_a("IfcSpace"):
                    space_name = container.LongName or container.Name
        furniture.append({
            "guid":       item.GlobalId,
            "name":       item.Name,
            "space_name": space_name
        })
    return furniture


def extract_wall_boundaries(model):
    bounds = []
    seen   = set()
    for b in model.by_type("IfcRelSpaceBoundary"):
        elem  = b.RelatedBuildingElement
        space = b.RelatingSpace
        if not elem or not space:
            continue
        if not elem.is_a("IfcWallStandardCase"):
            continue
        key = (elem.GlobalId, space.Name)
        if key in seen:
            continue
        seen.add(key)

        # Calculate area
        area   = None
        length = None
        height = None
        try:
            surface = b.ConnectionGeometry.SurfaceOnRelatingElement
            height  = round(surface.Depth, 2)
            pts     = surface.SweptCurve.Curve.Points
            p1      = pts[0].Coordinates
            p2      = pts[1].Coordinates
            length  = round(math.sqrt(
                (p2[0]-p1[0])**2 + (p2[1]-p1[1])**2
            ), 2)
            area    = round(height * length, 2)
        except:
            pass

        wall_type = detect_wall_type(elem.Name)

        bounds.append({
            "wall_guid":  elem.GlobalId,
            "wall_name":  elem.Name,
            "wall_type":  wall_type,
            "space_name": space.Name,
            "space_long": space.LongName or space.Name,
            "area":       area,
            "length":     length,
            "height":     height
        })
    return bounds


def extract_door_boundaries(model):
    bounds = []
    seen   = set()
    for b in model.by_type("IfcRelSpaceBoundary"):
        elem  = b.RelatedBuildingElement
        space = b.RelatingSpace
        if not elem or not space:
            continue
        if not elem.is_a("IfcDoor"):
            continue
        key = (elem.GlobalId, space.Name)
        if key in seen:
            continue
        seen.add(key)
        width  = elem.OverallWidth  if elem.OverallWidth  else 0
        height = elem.OverallHeight if elem.OverallHeight else 0
        area   = round((width * height) / 1e6, 2) if width and height else 0
        bounds.append({
            "door_guid":  elem.GlobalId,
            "door_name":  elem.Name,
            "space_name": space.Name,
            "space_long": space.LongName or space.Name,
            "width":      width,
            "height":     height,
            "area":       area
        })
    return bounds


def extract_window_boundaries(model):
    bounds = []
    seen   = set()
    for b in model.by_type("IfcRelSpaceBoundary"):
        elem  = b.RelatedBuildingElement
        space = b.RelatingSpace
        if not elem or not space:
            continue
        if not elem.is_a("IfcWindow"):
            continue
        key = (elem.GlobalId, space.Name)
        if key in seen:
            continue
        seen.add(key)
        width  = elem.OverallWidth  if elem.OverallWidth  else 0
        height = elem.OverallHeight if elem.OverallHeight else 0
        area   = round((width * height) / 1e6, 2) if width and height else 0
        bounds.append({
            "window_guid": elem.GlobalId,
            "window_name": elem.Name,
            "space_name":  space.Name,
            "space_long":  space.LongName or space.Name,
            "width":       width,
            "height":      height,
            "area":        area
        })
    return bounds


if __name__ == "__main__":
    data = parse_ifc("sample_data/bimnexus.ifc")
    print("\n✅ IFC Parsing Complete!")