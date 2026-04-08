"""
aps_routes.py — Autodesk Platform Services integration for BIM Nexus
Add this to your Flask app: app.register_blueprint(aps_bp)
Set environment variables: APS_CLIENT_ID, APS_CLIENT_SECRET, APS_BUCKET_KEY
"""

import os
import base64
import time
import requests
from flask import Blueprint, request, jsonify
from functools import lru_cache

aps_bp = Blueprint('aps', __name__, url_prefix='/api/aps')

APS_CLIENT_ID     = os.getenv("APS_CLIENT_ID", "")
APS_CLIENT_SECRET = os.getenv("APS_CLIENT_SECRET", "")
APS_BUCKET_KEY    = os.getenv("APS_BUCKET_KEY", "bimnexus-ifc-bucket")
APS_BASE          = "https://developer.api.autodesk.com"

# ── Token cache (expires in 55 min) ──────────────────────────────────────────
_token_cache = {"token": None, "expires_at": 0}

def get_2legged_token(scope="data:read data:write data:create bucket:create bucket:read"):
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    resp = requests.post(
        f"{APS_BASE}/authentication/v2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id":     APS_CLIENT_ID,
            "client_secret": APS_CLIENT_SECRET,
            "grant_type":    "client_credentials",
            "scope":         scope,
        }
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"]      = data["access_token"]
    _token_cache["expires_at"] = now + data["expires_in"] - 60  # 60s safety margin
    return _token_cache["token"]


def ensure_bucket():
    """Create OSS bucket if it doesn't exist yet."""
    token = get_2legged_token(scope="data:read data:write data:create bucket:create bucket:read")
    resp = requests.post(
        f"{APS_BASE}/oss/v2/buckets",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"bucketKey": APS_BUCKET_KEY, "policyKey": "persistent"}
    )
    # 409 = already exists → fine
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()


# ── Public token endpoint (read-only, safe to expose to browser) ─────────────
@aps_bp.route("/token")
def token():
    """Return a read-only viewer token to the frontend."""
    try:
        t = get_2legged_token(scope="data:read viewables:read")
        return jsonify({"access_token": t})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Upload IFC → OSS, then kick off Model Derivative translation ──────────────
@aps_bp.route("/upload", methods=["POST"])
def upload():
    """
    Accepts the same IFC file the user already uploads to BIM Nexus.
    Returns the URN needed for the APS Viewer.
    """
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    ifc_file = request.files["file"]
    filename = ifc_file.filename.replace(" ", "_").lower()
    data = ifc_file.read()

    try:
        ensure_bucket()
        token = get_2legged_token(scope="data:read data:write data:create bucket:create bucket:read")

        # 1. Upload to OSS
        # Step 1 — Get a signed S3 upload URL
        sign_resp = requests.get(
            f"{APS_BASE}/oss/v2/buckets/{APS_BUCKET_KEY}/objects/{filename}/signeds3upload",
            headers={"Authorization": f"Bearer {token}"},
            params={"minutesExpiration": 60}
        )
        if not sign_resp.ok:
            raise Exception(f"Sign URL failed: {sign_resp.status_code} — {sign_resp.text}")
        sign_data = sign_resp.json()
        upload_key = sign_data["uploadKey"]
        s3_url = sign_data["urls"][0]

        # Step 2 — Upload directly to S3
        s3_resp = requests.put(
            s3_url,
            headers={"Content-Type": "application/octet-stream"},
            data=data,
        )
        if not s3_resp.ok:
            raise Exception(f"S3 upload failed: {s3_resp.status_code} — {s3_resp.text}")

        # Step 3 — Complete the upload
        complete_resp = requests.post(
            f"{APS_BASE}/oss/v2/buckets/{APS_BUCKET_KEY}/objects/{filename}/signeds3upload",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"uploadKey": upload_key}
        )
        if not complete_resp.ok:
            raise Exception(f"Complete upload failed: {complete_resp.status_code} — {complete_resp.text}")
        object_id = complete_resp.json()["objectId"]

        # 2. Create URN (base64-encoded objectId)
        urn = base64.b64encode(object_id.encode()).decode().rstrip("=")

        # 3. Start translation to SVF2
        translate_resp = requests.post(
            f"{APS_BASE}/modelderivative/v2/designdata/job",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
                "x-ads-force":   "true",   # re-translate if already exists
            },
            json={
                "input":  {"urn": urn},
                "output": {"formats": [{"type": "svf2", "views": ["2d", "3d"]}]},
            },
        )
        translate_resp.raise_for_status()

        return jsonify({"urn": urn, "status": "translating"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Poll translation status ───────────────────────────────────────────────────
@aps_bp.route("/status/<path:urn>")
def status(urn):
    """Poll until translation is complete. Frontend polls this every 3s."""
    try:
        token = get_2legged_token()
        resp = requests.get(
            f"{APS_BASE}/modelderivative/v2/designdata/{urn}/manifest",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return jsonify({
            "status":   data.get("status"),
            "progress": data.get("progress", "0%"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
