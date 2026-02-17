#!/usr/bin/env python3
"""
Bee Bytez — Code Scanner & Hive Search

Local-first code scanner with a web UI. Runs on localhost,
your code never leaves your machine.
"""

import argparse
import os
import tempfile
import shutil
import webbrowser
import threading
from flask import Flask, request, jsonify, send_from_directory
from scanner import scan_file, scan_directory, build_prompt, LEVEL_NAMES, SUPPORTED_EXTS

app = Flask(__name__, static_folder="static", static_url_path="/static")

# ============================================================
# State
# ============================================================

last_scan = {
    "findings": [],
    "path": "",
    "levels": [],
    "prompt": "",
}

# ============================================================
# Routes
# ============================================================

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Scan a path at the given calibration levels.

    POST JSON: { "path": "/path/to/code", "levels": [1,2,3], "ext": [".py"] }
    """
    data = request.get_json(force=True)
    target = data.get("path", ".")
    levels = data.get("levels", [1, 2])
    ext_filter = data.get("ext", None)

    if not os.path.exists(target):
        return jsonify({"error": f"Path not found: {target}"}), 400

    if os.path.isfile(target):
        findings = scan_file(target, levels)
        base_dir = os.path.dirname(target)
    else:
        findings = scan_directory(target, levels, ext_filter)
        base_dir = target

    prompt = build_prompt(findings, base_dir=base_dir)

    # Store last scan
    last_scan["findings"] = [f.to_dict() for f in findings]
    last_scan["path"] = target
    last_scan["levels"] = levels
    last_scan["prompt"] = prompt

    # Stats
    stats = {
        "total": len(findings),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warning"),
        "infos": sum(1 for f in findings if f.severity == "info"),
        "files_scanned": len(set(f.file for f in findings)),
    }

    return jsonify({
        "findings": last_scan["findings"],
        "prompt": prompt,
        "stats": stats,
        "path": target,
        "levels": levels,
    })


@app.route("/api/prompt")
def api_prompt():
    """Get the last generated prompt."""
    return jsonify({"prompt": last_scan["prompt"]})


@app.route("/api/upload-scan", methods=["POST"])
def api_upload_scan():
    """Scan uploaded files. Accepts multipart/form-data with files and levels.

    Files are saved to a temp directory, scanned, then cleaned up.
    Each file's relative path is preserved via the 'paths[]' field.
    """
    levels_raw = request.form.get("levels", "1,2")
    levels = [int(x) for x in levels_raw.split(",") if x.strip()]

    files = request.files.getlist("files")
    paths = request.form.getlist("paths[]")

    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    # Create a temp dir to hold uploaded files
    tmp_dir = tempfile.mkdtemp(prefix="bee_scan_")

    try:
        saved_files = []
        for i, f in enumerate(files):
            # Use the relative path if provided, otherwise the filename
            rel_path = paths[i] if i < len(paths) else f.filename
            # Sanitise: strip leading slashes, prevent traversal
            rel_path = rel_path.lstrip("/").replace("..", "")
            if not rel_path:
                continue

            dest = os.path.join(tmp_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            f.save(dest)
            saved_files.append(dest)

        # Scan the temp directory
        findings = scan_directory(tmp_dir, levels)
        prompt = build_prompt(findings, base_dir=tmp_dir)

        # Store last scan
        last_scan["findings"] = [f_item.to_dict() for f_item in findings]
        last_scan["path"] = "uploaded files"
        last_scan["levels"] = levels
        last_scan["prompt"] = prompt

        stats = {
            "total": len(findings),
            "errors": sum(1 for f_item in findings if f_item.severity == "error"),
            "warnings": sum(1 for f_item in findings if f_item.severity == "warning"),
            "infos": sum(1 for f_item in findings if f_item.severity == "info"),
            "files_scanned": len(set(f_item.file for f_item in findings)),
        }

        return jsonify({
            "findings": last_scan["findings"],
            "prompt": prompt,
            "stats": stats,
            "path": "uploaded files",
            "levels": levels,
        })

    finally:
        # Always clean up temp files
        shutil.rmtree(tmp_dir, ignore_errors=True)


import subprocess
import json as json_module

@app.route("/api/hive-search", methods=["POST"])
def api_hive_search():
    """Search code using the Rust seeder (TF-IDF + dot product).

    POST JSON: { "path": "/path/to/code", "terms": ["kw1","kw2","kw3","kw4"], "top": 10 }
    """
    data = request.get_json(force=True)
    target = data.get("path", "")
    terms = data.get("terms", [])
    top_k = data.get("top", 10)

    # Build query string from terms
    query = " ".join(t.strip() for t in terms if isinstance(t, str) and t.strip())
    if not query:
        return jsonify({"error": "Need at least one search term"}), 400
    if not target or not os.path.exists(target):
        return jsonify({"error": f"Path not found: {target}"}), 400

    # Find the Rust seeder binary
    seeder_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "target", "release", "bee-bytez")
    if not os.path.isfile(seeder_bin):
        return jsonify({"error": "Seeder binary not found. Run: cargo build --release"}), 500

    try:
        result = subprocess.run(
            [seeder_bin, target, "--json-query", query, "--top", str(top_k)],
            capture_output=True, text=True, timeout=60
        )

        if result.returncode != 0:
            return jsonify({"error": f"Seeder failed: {result.stderr[:200]}"}), 500

        # Parse JSON from stdout
        seeder_output = json_module.loads(result.stdout)

        return jsonify({
            "query": query,
            "results": seeder_output.get("results", []),
            "total_pieces": seeder_output.get("total_pieces", 0),
            "query_time_us": seeder_output.get("query_time_us", 0),
            "path": target,
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Search timed out (60s limit)"}), 504
    except json_module.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse seeder output: {e}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/presets")
def api_presets():
    """Return available calibration presets."""
    return jsonify({
        "levels": {str(k): v for k, v in LEVEL_NAMES.items()},
        "presets": {
            "quick": {"name": "Quick Lint", "levels": [1], "description": "Typos, TODOs, naming issues"},
            "default": {"name": "Standard", "levels": [1, 2], "description": "Lint + bug detection"},
            "security": {"name": "Security Audit", "levels": [1, 2, 3], "description": "Full security scan"},
            "full": {"name": "Full Scan", "levels": [1, 2, 3, 4], "description": "Everything including AI safety"},
        },
        "extensions": sorted(SUPPORTED_EXTS),
    })


@app.route("/api/cache", methods=["GET"])
def api_cache_status():
    """Return cache status so user can see what's stored."""
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__pycache__")
    cache_exists = os.path.isdir(cache_dir)
    cache_size = 0
    cache_files = 0
    if cache_exists:
        for f in os.listdir(cache_dir):
            fp = os.path.join(cache_dir, f)
            if os.path.isfile(fp):
                cache_size += os.path.getsize(fp)
                cache_files += 1
    return jsonify({
        "exists": cache_exists,
        "files": cache_files,
        "size_kb": round(cache_size / 1024, 1),
    })


@app.route("/api/cache", methods=["DELETE"])
def api_cache_clear():
    """Clear cache when user requests it."""
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__pycache__")
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
        return jsonify({"cleared": True, "message": "Cache cleared 🐝"})
    return jsonify({"cleared": False, "message": "No cache to clear"})


# ============================================================
# Main
# ============================================================

def open_browser(port):
    """Open the default browser after a short delay."""
    import time
    time.sleep(1.0)
    webbrowser.open(f"http://localhost:{port}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bee Bytez — Code Scanner & Hive Search")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   🐝 BEE BYTEZ — Code Scanner & Hive Search           ║")
    print(f"║   http://localhost:{args.port}                                 ║")
    print("║   Your code stays on YOUR machine.                    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(args.port,), daemon=True).start()

    app.run(host="127.0.0.1", port=args.port, debug=False)
