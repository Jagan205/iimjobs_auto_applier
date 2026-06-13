from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import threading
from pathlib import Path

from config import KEYWORDS_FILE, APPLIED_JOBS_FILE, PORT, DATA_DIR
from iimjobs_bot import IIMJobsBot, get_runtime_state, reset_runtime_state

app = Flask(__name__)

CORS(app, resources={r"/api/*": {"origins": [
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]}})


@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response


bot_thread = None
CONFIG_FILE = DATA_DIR / "search_config.json"


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def default_config():
    return {
        "roles": read_json(KEYWORDS_FILE, []),
        "jd_keywords": [],
        "locations": []
    }


def get_config():
    data = read_json(CONFIG_FILE, default_config())
    return {
        "roles": data.get("roles", []),
        "jd_keywords": data.get("jd_keywords", []),
        "locations": data.get("locations", [])
    }


def save_config_payload(payload):
    roles = []
    jd_keywords = []
    locations = []

    for x in payload.get("roles", []):
        x = str(x).strip()
        if x and x not in roles:
            roles.append(x)

    for x in payload.get("jd_keywords", []):
        x = str(x).strip()
        if x and x not in jd_keywords:
            jd_keywords.append(x)

    for x in payload.get("locations", []):
        x = str(x).strip()
        if x and x not in locations:
            locations.append(x)

    config = {
        "roles": roles,
        "jd_keywords": jd_keywords,
        "locations": locations
    }

    write_json(CONFIG_FILE, config)
    write_json(KEYWORDS_FILE, roles)
    return config


@app.route("/api/status", methods=["GET"])
def status():
    config = get_config()
    return jsonify({
        "ok": True,
        "state": get_runtime_state(),
        "config": config,
        "keywords": config["roles"],
        "applied_count": len(read_json(APPLIED_JOBS_FILE, []))
    })


@app.route("/api/config", methods=["GET"])
def read_config():
    return jsonify(get_config())


@app.route("/api/config", methods=["POST", "OPTIONS"])
def save_config():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(force=True)
    config = save_config_payload(payload)

    return jsonify({
        "ok": True,
        "config": config
    })


@app.route("/api/keywords", methods=["GET"])
def get_keywords():
    return jsonify(get_config().get("roles", []))


@app.route("/api/keywords", methods=["POST", "OPTIONS"])
def save_keywords():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(force=True)
    keywords = payload.get("keywords", [])

    config = get_config()
    config["roles"] = keywords
    config = save_config_payload(config)

    return jsonify({"ok": True, "keywords": config["roles"], "config": config})


@app.route("/api/applied", methods=["GET"])
def applied():
    return jsonify(read_json(APPLIED_JOBS_FILE, []))


@app.route("/api/run", methods=["POST", "OPTIONS"])
def run_bot():
    global bot_thread

    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    state = get_runtime_state()

    if state.get("running"):
        return jsonify({"ok": False, "message": "Bot already running"}), 409

    payload = request.get_json(silent=True) or get_config()
    config = save_config_payload(payload)

    roles = config["roles"]
    jd_keywords = config["jd_keywords"]
    locations = config["locations"]

    if not roles:
        return jsonify({"ok": False, "message": "Please add at least one job role"}), 400

    if not jd_keywords:
        return jsonify({"ok": False, "message": "Please add at least one JD keyword because matching uses Role AND Keywords"}), 400

    reset_runtime_state()

    def target():
        bot = IIMJobsBot()
        bot.run(roles=roles, jd_keywords=jd_keywords, locations=locations)

    bot_thread = threading.Thread(target=target, daemon=True)
    bot_thread.start()

    return jsonify({
        "ok": True,
        "message": "Bot started",
        "config": config
    })


@app.route("/api/stop", methods=["POST", "OPTIONS"])
def stop_bot():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    state = get_runtime_state()
    state["stop_requested"] = True

    return jsonify({
        "ok": True,
        "message": "Stop requested"
    })


if __name__ == "__main__":
    print(f"Backend running at http://127.0.0.1:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
