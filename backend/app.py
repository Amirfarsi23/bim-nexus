from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from neo4j import GraphDatabase
import os, sys, glob, uuid

sys.path.append(os.path.dirname(__file__))

from ifc_parser import parse_ifc
from neo4j_handler import store_building, get_user_projects, delete_user_project
from raumbuch_generator import generate_raumbuch
from ai_handler import answer_question

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── Single shared Neo4j driver — stays open for app lifetime ──
driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ─────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────
def get_user_context():
    """
    Extract user_id and project_id from request.
    For PhD demo: user_id comes from header X-User-ID.
    project_id comes from form field or JSON body or query param.
    If missing, generates a default so the app still works.
    """
    user_id    = request.headers.get("X-User-ID", "demo_user")
    project_id = (
        request.form.get("project_id") or
        (request.get_json(silent=True) or {}).get("project_id") or
        request.args.get("project_id", "default_project")
    )
    return user_id, project_id


# ─────────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────────
@app.route("/")
def home():
    return open("frontend/index.html", encoding="utf-8").read()

@app.route("/viewer")
def viewer():
    return open("frontend/viewer.html", encoding="utf-8").read()

@app.route("/api")
def api_info():
    return jsonify({"message": "BIM Nexus API is running!", "version": "2.0"})


# ─────────────────────────────────────────────────
# MODULE 1 — Upload IFC
# ─────────────────────────────────────────────────
@app.route("/upload-ifc", methods=["POST"])
def upload_ifc():
    try:
        user_id, project_id = get_user_context()

        if "ifc" not in request.files:
            return jsonify({"status": "error", "message": "No IFC file provided"}), 400

        file = request.files["ifc"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "Empty filename"}), 400

        # Save with user+project prefix to avoid filename collisions
        safe_name = f"{user_id}_{project_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_FOLDER, safe_name)
        file.save(file_path)
        print(f"✅ File saved: {file_path}")

        # Parse → Store → Raumbuch
        print("Parsing IFC...")
        data = parse_ifc(file_path)

        print("Storing in Neo4j...")
        store_building(data, user_id, project_id)

        print("Generating Raumbuch...")
        rooms = generate_raumbuch(driver, user_id, project_id)

        return jsonify({
            "status":     "success",
            "message":    "IFC processed successfully!",
            "user_id":    user_id,
            "project_id": project_id,
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
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────
# MODULE 1 — Projects list
# ─────────────────────────────────────────────────
@app.route("/projects", methods=["GET"])
def list_projects():
    """Return all projects for a user — used by Unity app to show project picker."""
    try:
        user_id = request.headers.get("X-User-ID", "demo_user")
        projects = get_user_projects(user_id)
        return jsonify({"status": "success", "projects": projects})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    """Delete one project for a user."""
    try:
        user_id = request.headers.get("X-User-ID", "demo_user")
        delete_user_project(user_id, project_id)
        return jsonify({"status": "success", "message": f"Project {project_id} deleted"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────
# MODULE 1 — Raumbuch
# ─────────────────────────────────────────────────
@app.route("/raumbuch", methods=["GET"])
def get_raumbuch():
    try:
        user_id, project_id = get_user_context()
        rooms = generate_raumbuch(driver, user_id, project_id)
        return jsonify({
            "status":    "success",
            "rooms":     rooms,
            "total_ngf": sum(r["NGF (m²)"] for r in rooms if r["NGF (m²)"])
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────
# MODULE 2 — AI Chat
# ─────────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    try:
        user_id, project_id = get_user_context()
        body     = request.get_json()
        question = body.get("question", "")

        if not question:
            return jsonify({"status": "error", "message": "No question provided"}), 400

        # Pass user context so AI only queries this user's data
        answer = answer_question(question, driver, user_id, project_id)

        return jsonify({
            "status":     "success",
            "question":   question,
            "answer":     answer,
            "user_id":    user_id,
            "project_id": project_id
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────
# MODULE 1 — Serve IFC file to Unity viewer
# ─────────────────────────────────────────────────
@app.route("/get-ifc")
def get_ifc():
    """Serve the IFC file for this user's project to the Unity / web viewer."""
    user_id, project_id = get_user_context()

    # Find this user's specific IFC file
    pattern = os.path.join(UPLOAD_FOLDER, f"{user_id}_{project_id}_*.ifc")
    files   = glob.glob(pattern)

    if not files:
        # Fall back to any IFC in sample_data for demo
        files = glob.glob("sample_data/*.ifc")
    if not files:
        return jsonify({"error": "No IFC file found"}), 404

    latest = max(files, key=os.path.getmtime)
    return send_file(
        os.path.abspath(latest),
        mimetype="application/octet-stream",
        as_attachment=False
    )


# ─────────────────────────────────────────────────
# MODULE 1 — Element info (click in viewer)
# ─────────────────────────────────────────────────
@app.route("/element-info/<int:express_id>")
def element_info(express_id):
    """Get element data from Neo4j by Express ID — scoped to user's project."""
    user_id, project_id = get_user_context()

    try:
        with driver.session() as session:

            # Wall?
            result = session.run("""
                MATCH (w:Wall {guid: $guid, user_id: $uid, project_id: $pid})
                OPTIONAL MATCH (w)-[b:BOUNDS]->(s:Space)
                RETURN w.name       AS name,
                       w.wall_type  AS type,
                       w.is_external AS is_external,
                       w.material   AS material,
                       collect({room: s.long_name, area: b.area}) AS rooms
            """, guid=str(express_id), uid=user_id, pid=project_id).data()

            if result:
                return jsonify({"status": "success", "element_type": "Wall", "data": result[0]})

            # Door?
            result = session.run("""
                MATCH (d:Door {user_id: $uid, project_id: $pid})
                WHERE d.guid CONTAINS $guid
                OPTIONAL MATCH (d)-[r:OPENS_INTO]->(s:Space)
                RETURN d.name AS name, d.width AS width, d.height AS height,
                       d.area AS area, collect(s.long_name) AS rooms
            """, guid=str(express_id), uid=user_id, pid=project_id).data()

            if result:
                return jsonify({"status": "success", "element_type": "Door", "data": result[0]})

            # Window?
            result = session.run("""
                MATCH (w:Window {user_id: $uid, project_id: $pid})
                WHERE w.guid CONTAINS $guid
                OPTIONAL MATCH (w)-[r:BELONGS_TO]->(s:Space)
                RETURN w.name AS name, w.width AS width, w.height AS height,
                       w.area AS area, collect(s.long_name) AS rooms
            """, guid=str(express_id), uid=user_id, pid=project_id).data()

            if result:
                return jsonify({"status": "success", "element_type": "Window", "data": result[0]})

            return jsonify({"status": "success", "element_type": "Unknown", "data": {}})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────
# MODULE 1 — Update element
# ─────────────────────────────────────────────────
@app.route("/update-element", methods=["POST"])
def update_element():
    try:
        user_id, project_id = get_user_context()
        body      = request.get_json()
        space_id  = body.get("space_id")
        field     = body.get("field")
        new_value = body.get("value")

        allowed_fields = ["long_name", "area", "height"]
        if field not in allowed_fields:
            return jsonify({"status": "error", "message": f"Field '{field}' not editable"}), 400

        with driver.session() as session:
            session.run(f"""
                MATCH (s:Space {{name: $id, user_id: $uid, project_id: $pid}})
                SET s.{field} = $value
            """, id=space_id, value=new_value, uid=user_id, pid=project_id)

        return jsonify({"status": "success", "message": f"Updated {field} for space {space_id}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─────────────────────────────────────────────────
# MODULE 3 — Scheduler (coming Phase 4)
# ─────────────────────────────────────────────────
@app.route("/schedule", methods=["POST"])
def schedule():
    return jsonify({"status": "success", "message": "Scheduler coming in Phase 4"})


# ─────────────────────────────────────────────────
# MODULE 4 — Procurement (coming Phase 5)
# ─────────────────────────────────────────────────
@app.route("/send-rfq", methods=["POST"])
def send_rfq():
    return jsonify({"status": "success", "message": "Procurement coming in Phase 5"})


# ─────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("BIM Nexus API v2.0 starting...")
    print("Go to: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
