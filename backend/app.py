from flask import Flask, request, jsonify
from dotenv import load_dotenv
from neo4j import GraphDatabase
import os

load_dotenv()

app = Flask(__name__)

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"),
          os.getenv("NEO4J_PASSWORD"))
)

@app.route("/")
def home():
    return jsonify({
        "message": "BIM Nexus API is running!",
        "version": "1.0",
        "modules": [
            "BIM Intelligence",
            "Scheduler",
            "Procurement",
            "Cost AI"
        ]
    })

@app.route("/upload-ifc", methods=["POST"])
def upload_ifc():
    return jsonify({
        "status": "success",
        "message": "IFC upload endpoint ready"
    })

@app.route("/chat", methods=["POST"])
def chat():
    return jsonify({
        "status": "success",
        "message": "AI chat endpoint ready"
    })

@app.route("/schedule", methods=["POST"])
def schedule():
    return jsonify({
        "status": "success",
        "message": "Scheduler endpoint ready"
    })

@app.route("/send-rfq", methods=["POST"])
def send_rfq():
    return jsonify({
        "status": "success",
        "message": "Procurement endpoint ready"
    })

if __name__ == "__main__":
    print("BIM Nexus server starting...")
    app.run(debug=True, port=5000)