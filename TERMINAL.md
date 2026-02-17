# 🐝 Bee Bytez — Terminal & Power User Guide

For people who live in the terminal. The web UI is just one interface — everything works from the command line too.

## CLI Scanner

```bash
# Scan a directory at calibration levels 1 and 2 (Lint + Bug Hunt)
python3 scanner.py /path/to/your/code 1,2

# Full scan (all 4 levels)
python3 scanner.py /path/to/your/code 1,2,3,4

# Scan a single file
python3 scanner.py /path/to/file.py 1,2,3
```

Output is plain text with file paths, line numbers, severity, and descriptions. Pipe it wherever you want.

## Rust Seeder (Hive Search Engine)

The Hive Search UI is powered by a Rust binary that does TF-IDF relevance search with optional CUDA acceleration.

### Build

```bash
cd src/
cargo build --release
```

### Use

```bash
# Search a codebase with keywords
./target/release/bee-bytez /path/to/code --json-query "async fetch error render"

# Pipe to jq for filtering
./target/release/bee-bytez /path/to/code --json-query "security auth" | jq '.results[] | select(.score > 0.05)'
```

### Output Format (JSON)

```json
{
  "results": [
    {
      "file": "/path/to/file.py",
      "rank": 1,
      "score": 0.081,
      "preview": "def authenticate(user, password):...",
      "start_line": 47
    }
  ],
  "time_ms": 0.2,
  "total_pieces": 142
}
```

## CI / Git Hook Integration

### Pre-commit hook

```bash
#!/bin/bash
# .git/hooks/pre-commit
FINDINGS=$(python3 /path/to/bee-bytes/scanner.py . 1,2,3 2>&1)
ERRORS=$(echo "$FINDINGS" | grep -c "ERROR")
if [ "$ERRORS" -gt 0 ]; then
    echo "🐝 Bee Bytez found $ERRORS errors. Fix them before committing."
    echo "$FINDINGS" | grep "ERROR"
    exit 1
fi
```

### JSON output for scripts

```bash
# The API is available when the server is running
curl -X POST http://localhost:5000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/code", "levels": [1,2,3]}'
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/scan` | Scan code (JSON body: path, levels) |
| POST | `/api/hive-search` | Keyword search (JSON body: path, terms) |
| GET | `/api/presets` | Available calibration presets |
| GET | `/api/cache` | Cache status (file count, size) |
| DELETE | `/api/cache` | Clear the cache |

## Project Structure

```
bee-bytes/
├── bee-bytez           # Launcher script
├── app.py              # Flask API server
├── scanner.py          # Python scanner engine (CLI + library)
├── static/
│   ├── index.html      # Web UI
│   ├── app.js          # Frontend logic
│   └── style.css       # Honey bee theme
├── src/                # Rust seeder (bee-bytez)
│   ├── main.rs
│   ├── lib.rs
│   └── gpu_compute.rs  # CUDA kernels
├── README.md           # User guide
└── TERMINAL.md         # This file
```
