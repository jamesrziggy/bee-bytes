# 🐝 Bee Bytez

**Code Scanner & Hive Search — your code never leaves your machine.**

Bee Bytez is a local tool. It runs a tiny server on YOUR computer and opens YOUR browser. No internet needed. No accounts. No data leaves your system. Think of it like running a private game server — it's all local.

---

## Quick Start

```bash
./bee-bytez
```

Your browser opens. That's it. Start scanning.

### What You Can Do

1. **Drop a folder** into the drop zone (or type a path)
2. **Pick a calibration level** — from quick lint checks to full security scans
3. **Hit Scan** — findings show up with exact line numbers so you can fix them
4. **Hive Search** — type up to 4 keywords, the Rust engine finds the most relevant code chunks in milliseconds
5. **Copy Prompt** — if you want AI help, hit Copy and paste the prompt into ChatGPT/Claude/whatever

### Cache

Click the 🗑️ Cache button in the top right to see what's stored and clear it. You control your data.

### Options

```bash
./bee-bytez                # Normal launch (opens browser)
./bee-bytez --port 8080    # Use a different port
./bee-bytez --no-browser   # Start without opening browser
```

---

## Requirements

- **Python 3.8+** — this runs the web UI and scanner
- **Flask** — `pip install flask` (the launcher will install it for you if missing)
- **Rust toolchain** — only needed if you want Hive Search (the fast code search feature)

---

## 🦀 Building the Rust Seeder (Hive Search Engine)

Hive Search is powered by a small Rust binary that indexes your code and finds relevant chunks using TF-IDF vector math. **You only need to compile it once** — after that it just works.

### What is Rust? (Don't worry)

Rust is a fast, safe programming language. You don't need to *know* Rust to use Bee Bytez — you just need the Rust compiler installed so it can build the search engine binary. Think of it like installing a kitchen appliance: you don't need to know how the motor works, you just plug it in once.

### Step 1: Install Rust

If you don't have Rust installed, run this one command:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

It will ask you a question — just press **Enter** to accept the defaults. When it's done, restart your terminal (or run `source ~/.cargo/env`).

> **Windows users:** Download the installer from [rustup.rs](https://rustup.rs) instead.

Verify it worked:

```bash
rustc --version
# You should see something like: rustc 1.XX.X
```

### Step 2: Build the Seeder

From the Bee Bytez folder, run:

```bash
cargo build --release
```

This will:
1. Download any Rust dependencies (just a few small ones)
2. Compile the seeder into a fast, optimized binary
3. Put the binary at `./target/release/bee-bytez`

**First build takes 30–60 seconds.** After that, you never need to do it again unless you modify the Rust source code.

> **What you'll see:** A progress bar with `Compiling bee-bytez v0.1.0`. A couple of yellow "warnings" are normal and harmless — they're just Rust being very thorough about unused variables.

### Step 3: Done!

That's it. Hive Search will now work in the web UI. The scanner side (Scan button) works with just Python — no Rust needed for that.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| `cargo: command not found` | Rust isn't installed yet. Go back to Step 1. |
| `linker 'cc' not found` | You need a C compiler. Run `sudo apt install build-essential` (Ubuntu/Debian) or `xcode-select --install` (macOS). |
| Warnings during build | **Normal.** Yellow warnings are fine. Only red errors matter. |
| Hive Search returns no results | Make sure the path you entered actually has code files (`.rs`, `.py`, `.js`, `.c`, etc.) |

---

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Your Code  │────▶│  Python App  │────▶│   Web Browser    │
│  (on disk)  │     │  (Flask)     │     │   (localhost)    │
└─────────────┘     └──────┬───────┘     └──────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
        ┌─────▼─────┐           ┌───────▼───────┐
        │  Scanner   │           │  Rust Seeder  │
        │ (Python)   │           │  (bee-bytez)  │
        │            │           │               │
        │ Lint rules │           │ TF-IDF index  │
        │ Regex scan │           │ Dot product   │
        │ Security   │           │ Multi-thread  │
        └────────────┘           └───────────────┘
```

- **Scanner** (Python) — pattern-matching code analysis. Looks for bugs, style issues, and security problems.
- **Seeder** (Rust) — vector search engine. Splits your code into chunks, builds TF-IDF embeddings, and finds the most relevant pieces using dot product similarity. Runs across all your CPU cores in parallel.

---

## For Power Users

See [TERMINAL.md](TERMINAL.md) for CLI tools, JSON piping, CI integration, and direct seeder usage.

---

## Project Structure

```
bee-bytes/
├── bee-bytez           # Launch script (start here)
├── app.py              # Flask web server
├── scanner.py          # Python code scanner
├── static/
│   ├── index.html      # Web UI
│   ├── app.js          # Frontend logic
│   └── style.css       # Honey bee theme
├── src/                # Rust seeder source
│   ├── main.rs         # CLI entry point
│   ├── lib.rs          # Module exports
│   ├── k.rs            # K3 vector types
│   ├── va.rs           # Arithmetic verbs (dot, plus, times, etc.)
│   ├── piece.rs        # Code chunker + TF-IDF embeddings
│   └── seeder.rs       # Multi-threaded swarm search
├── Cargo.toml          # Rust dependencies
└── README.md           # You are here
```

## License

MIT
