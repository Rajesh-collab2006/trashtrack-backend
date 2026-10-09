"""
TrashTrack backend API
A small Flask + SQLite service for a garbage-collection complaint
reporting website (CSP project).

Endpoints
---------
GET    /api/complaints              -> list all complaints (optional ?status=reported)
POST   /api/complaints              -> file a new complaint
POST   /api/complaints/<id>/upvote  -> upvote a complaint
PATCH  /api/complaints/<id>/status  -> update status (admin only)
POST   /api/admin/login             -> admin login, returns a token
GET    /api/stats                   -> counts by status
"""

import os
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

# ---------------------------------------------------------------------------
# App + database setup
# ---------------------------------------------------------------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'trashtrack.db')}")
# Render/Heroku-style Postgres URLs sometimes start with postgres:// — SQLAlchemy wants postgresql://
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "trashtrack-admin")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")  # simple static token for the CSP scope

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
CORS(app)
db = SQLAlchemy(app)

CATEGORIES = {"overflow", "dumping", "missed", "litter", "other"}
STATUSES = {"reported", "progress", "resolved"}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class Complaint(db.Model):
    __tablename__ = "complaints"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="reported")
    upvotes = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def ticket_id(self):
        return f"GC-{self.id:04d}"

    def to_dict(self):
        return {
            "id": self.ticket_id(),
            "raw_id": self.id,
            "category": self.category,
            "location": self.location,
            "description": self.description,
            "status": self.status,
            "upvotes": self.upvotes,
            "created_at": self.created_at.isoformat(),
        }


with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_admin():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    return token == ADMIN_TOKEN


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/complaints")
def list_complaints():
    status = request.args.get("status")
    query = Complaint.query
    if status:
        if status not in STATUSES:
            return jsonify({"error": f"invalid status '{status}'"}), 400
        query = query.filter_by(status=status)
    complaints = query.order_by(Complaint.created_at.desc()).all()
    return jsonify([c.to_dict() for c in complaints])


@app.post("/api/complaints")
def create_complaint():
    data = request.get_json(silent=True) or {}
    location = (data.get("location") or "").strip()
    description = (data.get("description") or "").strip()
    category = data.get("category", "other")

    if not location or not description:
        return jsonify({"error": "location and description are required"}), 400
    if category not in CATEGORIES:
        return jsonify({"error": f"invalid category '{category}'"}), 400

    complaint = Complaint(category=category, location=location, description=description)
    db.session.add(complaint)
    db.session.commit()
    return jsonify(complaint.to_dict()), 201


@app.post("/api/complaints/<int:complaint_id>/upvote")
def upvote_complaint(complaint_id):
    complaint = db.session.get(Complaint, complaint_id)
    if not complaint:
        return jsonify({"error": "complaint not found"}), 404
    complaint.upvotes += 1
    db.session.commit()
    return jsonify(complaint.to_dict())


@app.patch("/api/complaints/<int:complaint_id>/status")
def update_status(complaint_id):
    if not require_admin():
        return jsonify({"error": "admin authorization required"}), 401

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if new_status not in STATUSES:
        return jsonify({"error": f"status must be one of {sorted(STATUSES)}"}), 400

    complaint = db.session.get(Complaint, complaint_id)
    if not complaint:
        return jsonify({"error": "complaint not found"}), 404

    complaint.status = new_status
    db.session.commit()
    return jsonify(complaint.to_dict())


@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "invalid password"}), 401
    return jsonify({"token": ADMIN_TOKEN})


@app.get("/api/stats")
def stats():
    all_complaints = Complaint.query.all()
    counts = {s: 0 for s in STATUSES}
    for c in all_complaints:
        counts[c.status] += 1
    counts["all"] = len(all_complaints)
    return jsonify(counts)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)