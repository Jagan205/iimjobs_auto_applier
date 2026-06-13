from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import threading
from pathlib import Path

from config import KEYWORDS_FILE, APPLIED_JOBS_FILE, PORT
from iimjobs_bot import IIMJobsBot, get_runtime_state, reset_runtime_state

app = Flask(__name__)

# CORS FIX
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                "http://localhost:3000",
                "http://127.0.0.1:3000"
            ]
        }
    }
)


@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = request.headers.get(
        "Origin",
        "*"
    )
    response.headers["Access-Control-Allow-Headers"] = \
        "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = \
        "GET,POST,PUT,DELETE,OPTIONS"

    return response


bot_thread = None


def read_json(path: Path, default):
    if not path.exists():
        return default

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return default


def write_json(path: Path, data):
    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "ok": True,
        "state": get_runtime_state(),
        "keywords": read_json(KEYWORDS_FILE, []),
        "applied_count": len(
            read_json(APPLIED_JOBS_FILE, [])
        )
    })


@app.route("/api/keywords", methods=["GET"])
def get_keywords():
    return jsonify(
        read_json(KEYWORDS_FILE, [])
    )


@app.route("/api/keywords", methods=["POST", "OPTIONS"])
def save_keywords():

    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    payload = request.get_json(force=True)

    keywords = payload.get(
        "keywords",
        []
    )

    cleaned = []

    for k in keywords:
        k = str(k).strip()

        if k and k not in cleaned:
            cleaned.append(k)

    write_json(
        KEYWORDS_FILE,
        cleaned
    )

    return jsonify({
        "ok": True,
        "keywords": cleaned
    })


@app.route("/api/applied", methods=["GET"])
def applied():
    return jsonify(
        read_json(
            APPLIED_JOBS_FILE,
            []
        )
    )


@app.route("/api/run", methods=["POST", "OPTIONS"])
def run_bot():

    global bot_thread

    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    state = get_runtime_state()

    if state.get("running"):
        return jsonify({
            "ok": False,
            "message": "Bot already running"
        }), 409

    payload = request.get_json(
        silent=True
    ) or {}

    keywords = payload.get(
        "keywords"
    ) or read_json(
        KEYWORDS_FILE,
        []
    )

    if not keywords:
        return jsonify({
            "ok": False,
            "message": "No keywords found"
        }), 400

    write_json(
        KEYWORDS_FILE,
        keywords
    )

    reset_runtime_state()

    def target():
        bot = IIMJobsBot()
        bot.run(keywords)

    bot_thread = threading.Thread(
        target=target,
        daemon=True
    )

    bot_thread.start()

    return jsonify({
        "ok": True,
        "message": "Bot started",
        "keywords": keywords
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

    print(
        f"Backend running at http://127.0.0.1:{PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=True
    )
