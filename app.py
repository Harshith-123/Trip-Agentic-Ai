"""
Flask web frontend for Trip Agentic AI.
Run: python app.py
"""
import json
import os
import threading
from flask import Flask, render_template, request, jsonify, session, Response, stream_with_context

from models import Card, TripRequest
from pipeline import run_pipeline

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Store progress messages per run (keyed by session id)
_progress: dict[str, list[str]] = {}
_results:  dict[str, str]       = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/cards", methods=["POST"])
def save_cards():
    data = request.get_json()
    cards = data.get("cards", [])
    if not cards:
        return jsonify({"error": "No cards provided"}), 400
    session["cards"] = cards
    return jsonify({"ok": True, "count": len(cards)})


@app.route("/api/run", methods=["POST"])
def run():
    data = request.get_json()
    cards_raw = session.get("cards") or data.get("cards", [])
    if not cards_raw:
        return jsonify({"error": "No cards in session. Add cards first."}), 400

    cards = [Card(**c) for c in cards_raw]
    try:
        origin = data["origin"].upper()
        destination = data["destination"].upper()

        if origin == destination:
            return jsonify({"error": f"Origin and destination cannot both be {origin}. Please enter different airports."}), 400
        if len(origin) != 3 or len(destination) != 3:
            return jsonify({"error": "Airport codes must be exactly 3 letters (e.g. BLR, JFK, DXB)."}), 400

        trip = TripRequest(
            cards=cards,
            origin=origin,
            destination=destination,
            check_in=data["check_in"],
            check_out=data.get("check_out", data["check_in"]),
            adults=int(data.get("adults", 1)),
            currency=data.get("currency", "USD").upper(),
            trip_type=data.get("trip_type", "one-way"),
            return_date=data.get("return_date", ""),
            hotel_check_in=data.get("hotel_check_in", ""),
            hotel_check_out=data.get("hotel_check_out", ""),
        )
    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400

    report = run_pipeline(trip)

    # Save report
    with open("trip_report.md", "w", encoding="utf-8") as f:
        f.write(report)

    return jsonify({"report": report})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
