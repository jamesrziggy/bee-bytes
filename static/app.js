/* ============================================================
   Bee Bytez — Frontend Logic
   ============================================================ */

const API = "";
let lastPrompt = "";
let droppedFiles = [];  // [{file: File, path: "relative/path"}]
let isScanning = false;  // Guard against double scans

// ============================================================
// Drag & Drop
// ============================================================

const dropZone = document.getElementById("drop-zone");
const dropContent = document.getElementById("drop-zone-content");
const dropActive = document.getElementById("drop-zone-active");
const dropFilesList = document.getElementById("drop-zone-files");

// Prevent default drag behavior on body so browser doesn't navigate to the file
["dragenter", "dragover", "dragleave", "drop"].forEach(evt => {
    document.body.addEventListener(evt, e => { e.preventDefault(); }, false);
});

// Visual feedback on drag over the drop zone
dropZone.addEventListener("dragenter", () => dropZone.classList.add("drag-over"));
dropZone.addEventListener("dragover", () => dropZone.classList.add("drag-over"));
dropZone.addEventListener("dragleave", (e) => {
    // Only remove if we actually left the drop zone
    if (!dropZone.contains(e.relatedTarget)) {
        dropZone.classList.remove("drag-over");
    }
});

dropZone.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("drag-over");

    const items = e.dataTransfer.items;
    if (!items || items.length === 0) return;

    droppedFiles = [];
    const promises = [];

    for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
        if (entry) {
            promises.push(readEntry(entry, ""));
        } else if (items[i].kind === "file") {
            const file = items[i].getAsFile();
            if (file) droppedFiles.push({ file, path: file.name });
        }
    }

    await Promise.all(promises);

    if (droppedFiles.length > 0) {
        showDroppedFiles();
        // Don't clear scan-path — user may need it for Hive Search
        // Don't auto-scan — let user click Scan or Hive Search
    }
});

// Recursively read directory entries
function readEntry(entry, basePath) {
    return new Promise((resolve) => {
        if (entry.isFile) {
            entry.file(f => {
                const relPath = basePath ? basePath + "/" + f.name : f.name;
                droppedFiles.push({ file: f, path: relPath });
                resolve();
            });
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            const dirPath = basePath ? basePath + "/" + entry.name : entry.name;
            readAllEntries(reader, dirPath).then(resolve);
        } else {
            resolve();
        }
    });
}

function readAllEntries(reader, dirPath) {
    return new Promise((resolve) => {
        let allEntries = [];
        function readBatch() {
            reader.readEntries(entries => {
                if (entries.length === 0) {
                    Promise.all(allEntries.map(e => readEntry(e, dirPath))).then(resolve);
                } else {
                    allEntries = allEntries.concat(Array.from(entries));
                    readBatch(); // Keep reading (Chrome returns max 100 per batch)
                }
            });
        }
        readBatch();
    });
}

// Show dropped files in the drop zone
function showDroppedFiles() {
    dropZone.classList.add("has-files");
    dropContent.style.display = "none";
    dropFilesList.style.display = "block";

    const maxShow = 6;
    const shown = droppedFiles.slice(0, maxShow);
    const remaining = droppedFiles.length - maxShow;

    let html = `
        <div class="drop-zone-files-header">
            <span class="drop-zone-files-title">✅ ${droppedFiles.length} file${droppedFiles.length !== 1 ? 's' : ''}</span>
            <button class="drop-zone-clear" onclick="clearDroppedFiles(event)">✕ Clear</button>
        </div>
    `;

    for (const { path } of shown) {
        html += `<div class="drop-file-item">${escapeHtml(path)}</div>`;
    }

    if (remaining > 0) {
        html += `<div class="drop-file-count">+${remaining} more file${remaining !== 1 ? 's' : ''}</div>`;
    }

    dropFilesList.innerHTML = html;
}

function clearDroppedFiles(e) {
    if (e) e.stopPropagation();
    droppedFiles = [];
    dropZone.classList.remove("has-files");
    dropContent.style.display = "";
    dropFilesList.style.display = "none";
    dropFilesList.innerHTML = "";
}

// Upload dropped files and scan
async function runUploadScan() {
    if (isScanning) return;
    isScanning = true;

    const scanBtn = document.getElementById("scan-btn");
    const statusEl = document.getElementById("status");
    const levels = getActiveLevels();

    if (levels.length === 0) {
        alert("Select at least one calibration level.");
        isScanning = false;
        return;
    }

    scanBtn.classList.add("scanning");
    scanBtn.innerHTML = '<span class="scan-btn-icon">⏳</span> Scanning...';
    statusEl.innerHTML = '<span class="status-dot scanning"></span> Uploading & Scanning...';

    try {
        const formData = new FormData();
        formData.append("levels", levels.join(","));

        for (const { file, path } of droppedFiles) {
            formData.append("files", file);
            formData.append("paths[]", path);
        }

        const response = await fetch(`${API}/api/upload-scan`, {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || "Upload scan failed");
        }

        const data = await response.json();
        renderResults(data);
        renderPrompt(data.prompt);
        lastPrompt = data.prompt;

        const total = data.stats.total;
        statusEl.innerHTML = `<span class="status-dot"></span> ${total} finding${total !== 1 ? 's' : ''}`;

    } catch (err) {
        statusEl.innerHTML = '<span class="status-dot" style="background:var(--accent-red);box-shadow:0 0 6px var(--accent-red)"></span> Error';
        document.getElementById("results-list").innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">❌</div>
                <p>${escapeHtml(err.message)}</p>
            </div>
        `;
    } finally {
        isScanning = false;
        scanBtn.classList.remove("scanning");
        scanBtn.innerHTML = '<span class="scan-btn-icon">🔍</span> Scan';
    }
}

// ============================================================
// Preset handling
// ============================================================

const PRESETS = {
    quick: [1],
    default: [1, 2],
    security: [1, 2, 3],
    full: [1, 2, 3, 4],
};

document.querySelectorAll(".preset-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        // Update active state
        document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");

        // Update checkboxes
        const levels = PRESETS[btn.dataset.preset];
        document.querySelectorAll(".level-check").forEach(cb => {
            cb.checked = levels.includes(parseInt(cb.dataset.level));
        });
    });
});

// When individual checkboxes change, update preset highlight
document.querySelectorAll(".level-check").forEach(cb => {
    cb.addEventListener("change", () => {
        const active = getActiveLevels();
        document.querySelectorAll(".preset-btn").forEach(btn => {
            const presetLevels = PRESETS[btn.dataset.preset];
            const match = presetLevels.length === active.length &&
                presetLevels.every((l, i) => l === active[i]);
            btn.classList.toggle("active", match);
        });
    });
});

function getActiveLevels() {
    return Array.from(document.querySelectorAll(".level-check:checked"))
        .map(cb => parseInt(cb.dataset.level))
        .sort();
}

// ============================================================
// Scan
// ============================================================

async function runScan() {
    if (isScanning) return;
    isScanning = true;

    const pathInput = document.getElementById("scan-path");
    const scanBtn = document.getElementById("scan-btn");
    const statusEl = document.getElementById("status");

    const path = pathInput.value.trim();
    if (!path) {
        // If we have dropped files, use the upload flow instead
        if (droppedFiles.length > 0) {
            isScanning = false;  // Reset since runUploadScan has its own guard
            return runUploadScan();
        }
        pathInput.focus();
        pathInput.style.borderColor = "var(--accent-red)";
        setTimeout(() => pathInput.style.borderColor = "", 1500);
        isScanning = false;
        return;
    }

    const levels = getActiveLevels();
    if (levels.length === 0) {
        alert("Select at least one calibration level.");
        isScanning = false;
        return;
    }

    // UI: scanning state
    scanBtn.classList.add("scanning");
    scanBtn.innerHTML = '<span class="scan-btn-icon">⏳</span> Scanning...';
    statusEl.innerHTML = '<span class="status-dot scanning"></span> Scanning...';

    try {
        const response = await fetch(`${API}/api/scan`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, levels }),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || "Scan failed");
        }

        const data = await response.json();
        renderResults(data);
        renderPrompt(data.prompt);
        lastPrompt = data.prompt;

        // Update status
        const total = data.stats.total;
        statusEl.innerHTML = `<span class="status-dot"></span> ${total} finding${total !== 1 ? 's' : ''}`;

    } catch (err) {
        statusEl.innerHTML = '<span class="status-dot" style="background:var(--accent-red);box-shadow:0 0 6px var(--accent-red)"></span> Error';
        document.getElementById("results-list").innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">❌</div>
                <p>${escapeHtml(err.message)}</p>
            </div>
        `;
    } finally {
        isScanning = false;
        scanBtn.classList.remove("scanning");
        scanBtn.innerHTML = '<span class="scan-btn-icon">🔍</span> Scan';
    }
}

// Also scan on Enter key in the path input
document.getElementById("scan-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runScan();
});

// ============================================================
// Hive Search — Custom keyword search via Rust seeder
// ============================================================

async function runHiveSearch() {
    const pathInput = document.getElementById("scan-path");
    const hiveBtn = document.getElementById("hive-btn");
    const statusEl = document.getElementById("status");

    const path = pathInput.value.trim();
    if (!path) {
        pathInput.focus();
        pathInput.style.borderColor = "var(--accent-red)";
        setTimeout(() => pathInput.style.borderColor = "", 1500);
        return;
    }

    // Collect search terms (non-empty)
    const terms = [1, 2, 3, 4]
        .map(i => document.getElementById(`term-${i}`).value.trim())
        .filter(t => t);

    if (terms.length === 0) {
        document.getElementById("term-1").focus();
        document.getElementById("term-1").style.borderColor = "var(--accent-red)";
        setTimeout(() => document.getElementById("term-1").style.borderColor = "", 1500);
        return;
    }

    // UI: searching state
    hiveBtn.classList.add("scanning");
    hiveBtn.innerHTML = '<span>⏳</span> Searching...';
    statusEl.innerHTML = '<span class="status-dot scanning"></span> Hive searching...';

    try {
        const response = await fetch(`${API}/api/hive-search`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, terms }),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || "Hive search failed");
        }

        const data = await response.json();
        renderHiveResults(data);

        const count = (data.results || []).length;
        statusEl.innerHTML = `<span class="status-dot"></span> 🐝 ${count} result${count !== 1 ? 's' : ''} found`;

    } catch (err) {
        statusEl.innerHTML = '<span class="status-dot" style="background:var(--accent-red);box-shadow:0 0 6px var(--accent-red)"></span> Error';
        document.getElementById("results-list").innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">❌</div>
                <p>${escapeHtml(err.message)}</p>
            </div>
        `;
    } finally {
        hiveBtn.classList.remove("scanning");
        hiveBtn.innerHTML = '<span>🐝</span> Hive Search';
    }
}

function renderHiveResults(data) {
    const resultsEl = document.getElementById("results-list");
    const results = data.results || [];
    const statsBar = document.getElementById("stats-bar");
    statsBar.style.display = "none";

    if (results.length === 0) {
        resultsEl.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">🔍</div>
                <p>No matching code found.</p>
                <p class="empty-sub">Try different keywords or a larger codebase.</p>
            </div>
        `;
        return;
    }

    let html = `
        <div class="hive-stats">
            <span>🐝 Query: <strong>"${escapeHtml(data.query)}"</strong></span>
            <span>📦 ${data.total_pieces} pieces</span>
            <span>⏱ ${(data.query_time_us / 1000).toFixed(1)}ms</span>
        </div>
    `;

    for (const r of results) {
        const displayFile = shortenPath(r.file || r.source || "", data.path || "");
        const scorePercent = (r.score * 100).toFixed(1);
        // Show first 4 non-empty lines of preview
        const previewLines = (r.preview || r.content || "")
            .split("\n")
            .filter(l => l.trim())
            .slice(0, 4)
            .join("\n");

        // Line numbers from seeder (start_line is 1-indexed)
        const startLine = r.start_line || r.line || null;
        const lineLabel = startLine ? `<span class="hive-result-lines">L${startLine}</span>` : "";

        html += `
            <div class="hive-result">
                <div class="hive-result-header">
                    <span class="hive-result-file">📄 ${escapeHtml(displayFile)} ${lineLabel}</span>
                    <span class="hive-result-score">#${r.rank} — ${scorePercent}%</span>
                </div>
                <div class="hive-result-preview">${escapeHtml(previewLines)}</div>
            </div>
        `;
    }

    resultsEl.innerHTML = html;

    // Build a prompt from hive results
    const promptLines = [
        `Hive Search Results for: "${data.query}"`,
        `${results.length} relevant code chunks found across ${data.total_pieces} pieces.`,
        "",
    ];
    for (const r of results) {
        const file = r.file || r.source || "unknown";
        const startLine = r.start_line || r.line || "";
        const lineInfo = startLine ? ` (line ${startLine})` : "";
        promptLines.push(`### ${file}${lineInfo} (score: ${(r.score * 100).toFixed(1)}%)`);
        const preview = (r.preview || r.content || "").trim();
        if (preview) {
            promptLines.push("```");
            promptLines.push(preview.split("\n").slice(0, 10).join("\n"));
            promptLines.push("```");
        }
        promptLines.push("");
    }
    const prompt = promptLines.join("\n");
    renderPrompt(prompt);
    lastPrompt = prompt;
}

// Allow Enter key in search term inputs to trigger hive search
[1, 2, 3, 4].forEach(i => {
    const el = document.getElementById(`term-${i}`);
    if (el) {
        el.addEventListener("keydown", (e) => {
            if (e.key === "Enter") runHiveSearch();
        });
    }
});

// ============================================================
// Render results
// ============================================================

function renderResults(data) {
    const { findings, stats } = data;
    const resultsEl = document.getElementById("results-list");
    const statsBar = document.getElementById("stats-bar");

    // Update stats
    document.getElementById("stat-errors").textContent = `${stats.errors} error${stats.errors !== 1 ? 's' : ''}`;
    document.getElementById("stat-warnings").textContent = `${stats.warnings} warning${stats.warnings !== 1 ? 's' : ''}`;
    document.getElementById("stat-infos").textContent = `${stats.infos} info`;
    statsBar.style.display = findings.length > 0 ? "flex" : "none";

    if (findings.length === 0) {
        resultsEl.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">✅</div>
                <p>No issues found!</p>
                <p class="empty-sub">Try enabling more calibration levels.</p>
            </div>
        `;
        return;
    }

    // Group by file
    const byFile = {};
    for (const f of findings) {
        const key = f.file;
        if (!byFile[key]) byFile[key] = [];
        byFile[key].push(f);
    }

    let html = "";
    for (const [filepath, fileFindings] of Object.entries(byFile).sort()) {
        // Get just the filename or short path
        const displayPath = shortenPath(filepath, data.path);

        html += `<div class="file-group">`;
        html += `<div class="file-group-header">
            📄 ${escapeHtml(displayPath)}
            <span class="file-group-count">${fileFindings.length} issue${fileFindings.length !== 1 ? 's' : ''}</span>
        </div>`;

        for (const f of fileFindings) {
            const icon = { error: "🔴", warning: "🟡", info: "🔵" }[f.severity] || "⚪";
            const copyText = `Line ${f.line} [${f.check}]: ${f.message}`;
            html += `<div class="finding-row" style="animation-delay: ${Math.random() * 0.1}s">
                <span class="finding-severity">${icon}</span>
                <span class="finding-line">L${f.line}</span>
                <span class="finding-check">${escapeHtml(f.check)}</span>
                <span class="finding-msg">${formatMessage(f.message)}</span>
                <button class="finding-copy-btn" data-copy="${escapeHtml(copyText)}" title="Copy finding">📋</button>
            </div>`;
        }

        html += `</div>`;
    }

    resultsEl.innerHTML = html;

    // Attach copy handlers to all finding copy buttons
    resultsEl.querySelectorAll(".finding-copy-btn").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const text = btn.getAttribute("data-copy");
            navigator.clipboard.writeText(text).then(() => {
                btn.textContent = "✅";
                setTimeout(() => btn.textContent = "📋", 1000);
            });
        });
    });
}

// ============================================================
// Render prompt
// ============================================================

function renderPrompt(prompt) {
    const promptEl = document.getElementById("prompt-output");
    const copyBtn = document.getElementById("copy-btn");

    // Clear completely first, then set new content
    promptEl.innerHTML = "";
    promptEl.textContent = prompt || "";
    promptEl.scrollTop = 0;

    // Brief flash to indicate update
    promptEl.style.borderColor = "rgba(0, 212, 255, 0.4)";
    setTimeout(() => promptEl.style.borderColor = "", 600);

    copyBtn.style.display = prompt ? "block" : "none";
    lastPrompt = prompt || "";
}

// ============================================================
// Copy prompt to clipboard
// ============================================================

async function copyPrompt() {
    const copyBtn = document.getElementById("copy-btn");
    try {
        await navigator.clipboard.writeText(lastPrompt);
        copyBtn.textContent = "✅ Copied!";
        copyBtn.classList.add("copied");
        setTimeout(() => {
            copyBtn.textContent = "📋 Copy";
            copyBtn.classList.remove("copied");
        }, 2000);
    } catch (err) {
        // Fallback for non-HTTPS
        const textarea = document.createElement("textarea");
        textarea.value = lastPrompt;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
        copyBtn.textContent = "✅ Copied!";
        setTimeout(() => copyBtn.textContent = "📋 Copy", 2000);
    }
}

// ============================================================
// Utilities
// ============================================================

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function formatMessage(msg) {
    // Wrap backtick-quoted terms in <code> tags
    return escapeHtml(msg).replace(/`([^`]+)`/g, '<code>$1</code>');
}

function shortenPath(filepath, basePath) {
    if (basePath && filepath.startsWith(basePath)) {
        return filepath.slice(basePath.length).replace(/^\//, "");
    }
    // Show last 3 path components
    const parts = filepath.split("/");
    if (parts.length > 3) {
        return "…/" + parts.slice(-3).join("/");
    }
    return filepath;
}

// ============================================================
// Cache Control — User decides what stays on their machine
// ============================================================

async function toggleCache() {
    const cacheBtn = document.getElementById("cache-btn");

    try {
        // First check cache status
        const statusRes = await fetch(`${API}/api/cache`);
        const status = await statusRes.json();

        if (!status.exists || status.files === 0) {
            cacheBtn.textContent = "✅ No cache";
            setTimeout(() => cacheBtn.textContent = "🗑️ Cache", 2000);
            return;
        }

        // Show user what's there and confirm clear
        const clear = confirm(
            `🐝 Cache Status:\n\n` +
            `Files: ${status.files}\n` +
            `Size: ${status.size_kb} KB\n\n` +
            `Clear the cache?`
        );

        if (clear) {
            const res = await fetch(`${API}/api/cache`, { method: "DELETE" });
            const data = await res.json();
            cacheBtn.textContent = "✅ Cleared!";
            setTimeout(() => cacheBtn.textContent = "🗑️ Cache", 2000);
        }
    } catch (err) {
        cacheBtn.textContent = "❌ Error";
        setTimeout(() => cacheBtn.textContent = "🗑️ Cache", 2000);
    }
}
