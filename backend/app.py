from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from neo4j import GraphDatabase
import os
import sys
from flask import send_file
import glob
# Add backend to path
sys.path.append(os.path.dirname(__file__))

from ifc_parser import parse_ifc
from neo4j_handler import store_building
from raumbuch_generator import generate_raumbuch
from ai_handler import answer_question

load_dotenv()

app = Flask(__name__)
CORS(app)

# Neo4j driver
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"),
          os.getenv("NEO4J_PASSWORD"))
)

# Upload folder
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ─────────────────────────────────────
# HOME
# ─────────────────────────────────────
@app.route("/")
def home():
    return open("frontend/index.html").read()

@app.route("/api")
def api_info():
    return jsonify({
        "message": "BIM Nexus API is running!",
        "version": "1.0"
    })


# ─────────────────────────────────────
# MODULE 1 — Upload IFC
# ─────────────────────────────────────
@app.route("/upload-ifc", methods=["POST"])
def upload_ifc():
    try:
        # Check file exists
        if "ifc" not in request.files:
            return jsonify({
                "status": "error",
                "message": "No IFC file provided"
            }), 400

        file = request.files["ifc"]

        if file.filename == "":
            return jsonify({
                "status": "error",
                "message": "Empty filename"
            }), 400

        # Save file
        file_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(file_path)
        print(f"✅ File saved: {file_path}")

        # Parse IFC
        print("Parsing IFC...")
        data = parse_ifc(file_path)

        # Store in Neo4j
        print("Storing in Neo4j...")
        store_building(data)

        # Generate Raumbuch
        print("Generating Raumbuch...")
        rooms = generate_raumbuch()

        return jsonify({
            "status":  "success",
            "message": "IFC processed successfully!",
            "summary": {
                "floors":    len(data["floors"]),
                "spaces":    len(data["spaces"]),
                "walls":     len(data["walls"]),
                "doors":     len(data["doors"]),
                "windows":   len(data["windows"]),
                "furniture": len(data["furniture"])
            },
            "raumbuch": rooms
        })

    except Exception as e:
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500


# ─────────────────────────────────────
# MODULE 1 — Get Raumbuch
# ─────────────────────────────────────
@app.route("/raumbuch", methods=["GET"])
def get_raumbuch():
    try:
        rooms = generate_raumbuch()
        return jsonify({
            "status":  "success",
            "rooms":   rooms,
            "total_ngf": sum(
                r["NGF (m²)"] for r in rooms
                if r["NGF (m²)"]
            )
        })
    except Exception as e:
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500


# ─────────────────────────────────────
# MODULE 2 — AI Chat
# ─────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        body     = request.get_json()
        question = body.get("question", "")

        if not question:
            return jsonify({
                "status":  "error",
                "message": "No question provided"
            }), 400

        answer = answer_question(question, driver)

        return jsonify({
            "status":   "success",
            "question": question,
            "answer":   answer
        })

    except Exception as e:
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500


# ─────────────────────────────────────
# MODULE 3 — Scheduler
# ─────────────────────────────────────
@app.route("/schedule", methods=["POST"])
def schedule():
    try:
        body = request.get_json()
        text = body.get("text", "")

        return jsonify({
            "status":  "success",
            "message": "Scheduler coming in Phase 4",
            "input":   text
        })

    except Exception as e:
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500


# ─────────────────────────────────────
# MODULE 4 — Procurement
# ─────────────────────────────────────
@app.route("/send-rfq", methods=["POST"])
def send_rfq():
    try:
        return jsonify({
            "status":  "success",
            "message": "Procurement coming in Phase 5"
        })

    except Exception as e:
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500

@app.route("/get-ifc")
def get_ifc():
    # Find the most recently uploaded IFC file
    files = glob.glob("uploads/*.ifc")
    if not files:
        # Fall back to sample data
        files = glob.glob("sample_data/*.ifc")
    if not files:
        return jsonify({"error": "No IFC file found"}), 404
    latest = max(files, key=os.path.getmtime)
    return send_file(
        os.path.abspath(latest),
        mimetype="application/octet-stream",
        as_attachment=False
    )

@app.route("/update-element", methods=["POST"])
def update_element():
    try:
        body      = request.get_json()
        space_id  = body.get("space_id")
        field     = body.get("field")
        new_value = body.get("value")

        allowed_fields = ["long_name", "area", "height"]
        if field not in allowed_fields:
            return jsonify({
                "status": "error",
                "message": f"Field '{field}' not editable"
            }), 400

        with driver.session() as session:
            session.run(f"""
                MATCH (s:Space {{name: $id}})
                SET s.{field} = $value
            """, id=space_id, value=new_value)

        return jsonify({
            "status":  "success",
            "message": f"Updated {field} for space {space_id}"
        })

    except Exception as e:
        return jsonify({
            "status":  "error",
            "message": str(e)
        }), 500
# ─────────────────────────────────────
# RUN
# ─────────────────────────────────────
@app.route("/viewer")
def viewer():
    return open("frontend/viewer.html").read()
@app.route("/element-info/<int:express_id>")
def element_info(express_id):
    """Get element data from Neo4j by Express ID"""
    try:
        with driver.session() as session:
            # Check if it is a wall
            result = session.run("""
                MATCH (w:Wall {guid: $guid})
                OPTIONAL MATCH (w)-[b:BOUNDS]->(s:Space)
                RETURN w.name AS name,
                       w.wall_type AS type,
                       w.is_external AS is_external,
                       w.material AS material,
                       collect({
                           room: s.long_name,
                           area: b.area
                       }) AS rooms
            """, guid=str(express_id)).data()

            if result:
                return jsonify({
                    "status":      "success",
                    "element_type":"Wall",
                    "data":        result[0]
                })

            # Check if it is a door
            result = session.run("""
                MATCH (d:Door)
                WHERE d.guid CONTAINS $guid
                OPTIONAL MATCH (d)-[r:OPENS_INTO]->(s:Space)
                RETURN d.name AS name,
                       d.width AS width,
                       d.height AS height,
                       d.area AS area,
                       collect(s.long_name) AS rooms
            """, guid=str(express_id)).data()

            if result:
                return jsonify({
                    "status":      "success",
                    "element_type":"Door",
                    "data":        result[0]
                })

            # Check if it is a window
            result = session.run("""
                MATCH (w:Window)
                WHERE w.guid CONTAINS $guid
                OPTIONAL MATCH (w)-[r:BELONGS_TO]->(s:Space)
                RETURN w.name AS name,
                       w.width AS width,
                       w.height AS height,
                       w.area AS area,
                       collect(s.long_name) AS rooms
            """, guid=str(express_id)).data()

            if result:
                return jsonify({
                    "status":      "success",
                    "element_type":"Window",
                    "data":        result[0]
                })

            return jsonify({
                "status":      "success",
                "element_type":"Unknown",
                "data":        {}
            })

    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500


@app.route("/reassign-element", methods=["POST"])
def reassign_element():
    """Move element from one room to another + recalculate raumbuch"""
    try:
        body       = request.get_json()
        express_id = body.get("express_id")
        from_room  = body.get("from_room_id")
        to_room_id = body.get("to_room_id")
        elem_type  = body.get("element_type","Wall")
        area       = body.get("area", 0)

        with driver.session() as session:

            if elem_type == "Wall":
                # Remove old BOUNDS relationship
                if from_room:
                    session.run("""
                        MATCH (w:Wall)-[b:BOUNDS]->(s:Space {name:$from_id})
                        WHERE w.guid CONTAINS $eid
                        DELETE b
                    """, from_id=str(from_room),
                        eid=str(express_id))

                # Create new BOUNDS relationship
                session.run("""
                    MATCH (w:Wall)
                    WHERE w.guid CONTAINS $eid
                    MATCH (s:Space {name:$to_id})
                    MERGE (w)-[:BOUNDS {
                        area:      $area,
                        wall_type: w.wall_type
                    }]->(s)
                """, eid=str(express_id),
                    to_id=str(to_room_id),
                    area=float(area))

            elif elem_type == "Door":
                if from_room:
                    session.run("""
                        MATCH (d:Door)-[r:OPENS_INTO]->(s:Space {name:$from_id})
                        WHERE d.guid CONTAINS $eid
                        DELETE r
                    """, from_id=str(from_room),
                        eid=str(express_id))

                session.run("""
                    MATCH (d:Door)
                    WHERE d.guid CONTAINS $eid
                    MATCH (s:Space {name:$to_id})
                    MERGE (d)-[:OPENS_INTO {area: $area}]->(s)
                """, eid=str(express_id),
                    to_id=str(to_room_id),
                    area=float(area))

            elif elem_type == "Window":
                if from_room:
                    session.run("""
                        MATCH (w:Window)-[r:BELONGS_TO]->(s:Space {name:$from_id})
                        WHERE w.guid CONTAINS $eid
                        DELETE r
                    """, from_id=str(from_room),
                        eid=str(express_id))

                session.run("""
                    MATCH (w:Window)
                    WHERE w.guid CONTAINS $eid
                    MATCH (s:Space {name:$to_id})
                    MERGE (w)-[:BELONGS_TO {area: $area}]->(s)
                """, eid=str(express_id),
                    to_id=str(to_room_id),
                    area=float(area))

        # Recalculate raumbuch after reassignment
        from raumbuch_generator import generate_raumbuch
        rooms = generate_raumbuch()

        return jsonify({
            "status":  "success",
            "message": f"Element reassigned to room {to_room_id}",
            "raumbuch": rooms
        })

    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500
if __name__ == "__main__":
    print("BIM Nexus API starting...")
    print("Go to: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)