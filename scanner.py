#!/usr/bin/env python3
"""
Bee Bytez — Code Scanner & Hive Search

Scans code files line-by-line, detects problems at configurable calibration
levels, and generates structured prompts with exact line numbers.

Calibration Levels:
    1 = Lint       (typos, naming, dead code, TODOs)
    2 = Bug Hunt   (off-by-one, null checks, broken equality, swallowed exceptions)
    3 = Security   (command injection, hardcoded secrets, timing attacks)
    4 = AI Safety  (prompt injections in code, suspicious encoded strings)
"""

import base64
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# ============================================================
# Finding — one detected issue
# ============================================================

@dataclass
class Finding:
    file: str
    line: int
    level: int          # 1-4
    severity: str       # "info", "warning", "error"
    check: str          # short check name
    message: str        # human-readable description

    def to_dict(self):
        return {
            "file": self.file,
            "line": self.line,
            "level": self.level,
            "severity": self.severity,
            "check": self.check,
            "message": self.message,
        }

# ============================================================
# Common typo dictionary
# ============================================================

TYPOS = {
    "teh": "the", "taht": "that", "adn": "and", "wiht": "with",
    "hte": "the", "recieve": "receive", "reciever": "receiver",
    "definately": "definitely", "occured": "occurred",
    "seperate": "separate", "temperture": "temperature",
    "langauge": "language", "fucntion": "function",
    "retrun": "return", "pritn": "print", "lenght": "length",
    "widht": "width", "heigth": "height", "calback": "callback",
    "pasword": "password", "reponse": "response",
    "requets": "request", "dictionaly": "dictionary",
    "excecute": "execute", "authentification": "authentication",
    "initalize": "initialize", "paramter": "parameter",
    "arguement": "argument", "overide": "override",
    "deafult": "default", "improt": "import", "flase": "false",
    "ture": "true", "nubmer": "number", "stirng": "string",
    "arrya": "array", "memroy": "memory", "thred": "thread",
    "proccess": "process", "mesage": "message",
    "enviroment": "environment", "depedency": "dependency",
    "runnning": "running", "comand": "command",
    "direcotry": "directory", "fitler": "filter",
}

# ============================================================
# Level 1 — Lint Checks
# ============================================================

def check_file_type(filepath, lines):
    """Detect file type based on header/shebang/extension. report Unknown if not found."""
    findings = []
    if not lines:
        return [Finding(filepath, 1, 1, "info", "file_type", "Empty file")]

    first_line = lines[0].strip()
    ftype = "Unknown"
    
    # Shebangs
    if first_line.startswith("#!"):
        if "python" in first_line: ftype = "Python Script"
        elif "bash" in first_line or "sh" in first_line: ftype = "Shell Script"
        elif "node" in first_line: ftype = "Node.js Script"
        elif "ruby" in first_line: ftype = "Ruby Script"
        elif "perl" in first_line: ftype = "Perl Script"
        else: ftype = f"Script ({first_line})"
    # Comments / Mode lines
    elif first_line.startswith("//") or first_line.startswith("/*"):
        if "rust" in first_line.lower() or filepath.endswith(".rs"): ftype = "Rust Source"
        elif "c" in first_line.lower() or filepath.endswith(".c") or filepath.endswith(".h"): ftype = "C/C++ Source"
        elif "js" in first_line.lower() or filepath.endswith(".js"): ftype = "JavaScript"
        elif "ts" in first_line.lower() or filepath.endswith(".ts"): ftype = "TypeScript"
        elif "java" in first_line.lower() or filepath.endswith(".java"): ftype = "Java Source"
        elif "go" in first_line.lower() or filepath.endswith(".go"): ftype = "Go Source"
        else: ftype = "Source Code (C-style comments)"
    elif first_line.startswith("#"):
        if filepath.endswith(".py"): ftype = "Python Source"
        elif filepath.endswith(".rb"): ftype = "Ruby Source"
        elif filepath.endswith(".toml"): ftype = "TOML Config"
        elif filepath.endswith(".yaml") or filepath.endswith(".yml"): ftype = "YAML Config"
        else: ftype = "Source Code (Hash comments)"
    elif first_line.startswith("<!DOCTYPE html>") or first_line.startswith("<html"):
        ftype = "HTML Document"
    elif first_line.startswith("{") or first_line.startswith("["):
        ftype = "JSON/Data"
        
    severity = "info"
    msg = f"File Type: {ftype}"
    
    if ftype == "Unknown":
        # Fallback to extension if header failed
        ext = os.path.splitext(filepath)[1]
        if ext in SUPPORTED_EXTS:
             msg = f"File Type: {ext} source (No header detected)"
        else:
             severity = "warning"
             msg = "File Type: Unknown (No header or recognized extension)"

    findings.append(Finding(
        file=filepath, line=1, level=1, severity=severity,
        check="file_type",
        message=msg
    ))
    return findings


def check_typos(filepath, lines):
    """Find common typos in comments and strings."""
    findings = []
    for i, line in enumerate(lines, 1):
        # Only check comments and strings, not code identifiers
        comment = ""
        if "#" in line:
            comment = line[line.index("#"):]
        elif line.strip().startswith(("//", "/*", "*")):
            comment = line

        if not comment:
            # Check string literals
            strings = re.findall(r'["\']([^"\']{3,})["\']', line)
            comment = " ".join(strings)

        if not comment:
            continue

        words = re.findall(r"[a-zA-Z]+", comment)
        for word in words:
            lower = word.lower()
            if lower in TYPOS:
                findings.append(Finding(
                    file=filepath, line=i, level=1, severity="info",
                    check="typo",
                    message=f'Typo: "{word}" → "{TYPOS[lower]}"'
                ))
    return findings


def check_todo_fixme(filepath, lines):
    """Flag TODO, FIXME, HACK, XXX, TEMP markers."""
    findings = []
    pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX|TEMP|WORKAROUND)\b", re.IGNORECASE)
    for i, line in enumerate(lines, 1):
        match = pattern.search(line)
        if match:
            tag = match.group(1).upper()
            rest = line[match.end():].strip().lstrip(":").strip()
            msg = f"{tag} marker"
            if rest:
                msg += f": {rest[:80]}"
            findings.append(Finding(
                file=filepath, line=i, level=1, severity="info",
                check="todo", message=msg
            ))
    return findings


def check_naming_consistency(filepath, lines):
    """Detect mixed snake_case and camelCase function/variable definitions."""
    snake_defs = []
    camel_defs = []
    snake_pat = re.compile(r"(?:def|let|var|const)\s+([a-z][a-z0-9]*(?:_[a-z0-9]+)+)")
    camel_pat = re.compile(r"(?:def|let|var|const)\s+([a-z]+[A-Z][a-zA-Z0-9]*)")

    for i, line in enumerate(lines, 1):
        if snake_pat.search(line):
            snake_defs.append(i)
        if camel_pat.search(line):
            camel_defs.append(i)

    findings = []
    # Only flag if BOTH styles exist (inconsistency)
    if snake_defs and camel_defs:
        minority = camel_defs if len(camel_defs) < len(snake_defs) else snake_defs
        style = "camelCase" if len(camel_defs) < len(snake_defs) else "snake_case"
        for line_num in minority[:5]:  # Cap at 5 to avoid flooding
            findings.append(Finding(
                file=filepath, line=line_num, level=1, severity="info",
                check="naming",
                message=f"Inconsistent naming: {style} used here but file is mostly {'snake_case' if style == 'camelCase' else 'camelCase'}"
            ))
    return findings


def check_unused_imports(filepath, lines):
    """Detect Python imports that are never referenced in the rest of the file."""
    if not filepath.endswith(".py"):
        return []

    findings = []
    full_text = "\n".join(lines)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # from X import Y, Z
        m = re.match(r"from\s+\S+\s+import\s+(.+)", stripped)
        if m:
            names = [n.strip().split(" as ")[-1].strip() for n in m.group(1).split(",")]
            for name in names:
                if not name or name == "*":
                    continue
                # Check if name appears anywhere AFTER the import
                rest = "\n".join(lines[i:])
                # Simple word-boundary check
                if not re.search(r"\b" + re.escape(name) + r"\b", rest):
                    findings.append(Finding(
                        file=filepath, line=i, level=1, severity="info",
                        check="unused_import",
                        message=f"Unused import: `{name}` is imported but never used"
                    ))
            continue

        # import X
        m = re.match(r"import\s+(\S+)", stripped)
        if m:
            name = m.group(1).split(".")[-1]
            rest = "\n".join(lines[i:])
            if not re.search(r"\b" + re.escape(name) + r"\b", rest):
                findings.append(Finding(
                    file=filepath, line=i, level=1, severity="info",
                    check="unused_import",
                    message=f"Unused import: `{name}` is imported but never used"
                ))
    return findings


# ============================================================
# Level 2 — Bug Hunt Checks
# ============================================================

def check_bare_except(filepath, lines):
    """Detect bare except clauses that swallow all exceptions."""
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "except:" or stripped.startswith("except:"):
            findings.append(Finding(
                file=filepath, line=i, level=2, severity="warning",
                check="bare_except",
                message="Bare `except:` swallows all exceptions including KeyboardInterrupt and SystemExit. Use `except Exception:` instead."
            ))
        elif re.match(r"except\s+\w+.*:\s*$", stripped):
            # Check if next non-empty line is just `pass`
            for j in range(i, min(i + 3, len(lines))):
                next_line = lines[j].strip()
                if next_line == "pass":
                    findings.append(Finding(
                        file=filepath, line=j + 1, level=2, severity="warning",
                        check="swallowed_exception",
                        message="Exception caught and silently swallowed with `pass`. At minimum, log the error."
                    ))
                    break
                elif next_line and not next_line.startswith("#"):
                    break
    return findings


def check_mutable_defaults(filepath, lines):
    """Detect mutable default arguments in Python function definitions."""
    if not filepath.endswith(".py"):
        return []

    findings = []
    pattern = re.compile(r"def\s+\w+\s*\(.*?(=\s*(\[\]|\{\}|\bset\(\)))")
    for i, line in enumerate(lines, 1):
        if pattern.search(line):
            findings.append(Finding(
                file=filepath, line=i, level=2, severity="warning",
                check="mutable_default",
                message="Mutable default argument (list/dict/set). Use `None` as default and create inside the function."
            ))
    return findings


def check_equality_issues(filepath, lines):
    """Detect broken __eq__ implementations."""
    findings = []
    in_eq = False
    eq_line = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "def __eq__" in stripped:
            in_eq = True
            eq_line = i
        elif in_eq and stripped.startswith("def "):
            in_eq = False

        if in_eq:
            # Truthiness chaining: `return self and other and ...`
            if re.search(r"return\s+self\s+and\s+other\s+and", stripped):
                findings.append(Finding(
                    file=filepath, line=i, level=2, severity="warning",
                    check="broken_eq",
                    message="__eq__ uses truthiness chaining (`return self and other and ...`). This returns non-bool values and breaks __ne__. Use isinstance check + return NotImplemented for foreign types."
                ))

            # No isinstance check
            if "return" in stripped and "isinstance" not in "\n".join(lines[eq_line-1:i]):
                if "==" in stripped and "isinstance" not in stripped:
                    pass  # Only flag if there's no isinstance anywhere in __eq__

    # __eq__ without __hash__
    has_eq = any("def __eq__" in line for line in lines)
    has_hash = any("def __hash__" in line for line in lines)
    has_class = any(re.match(r"\s*class\s+", line) for line in lines)
    if has_eq and not has_hash and has_class:
        eq_idx = next(i for i, l in enumerate(lines, 1) if "def __eq__" in l)
        findings.append(Finding(
            file=filepath, line=eq_idx, level=2, severity="info",
            check="eq_without_hash",
            message="__eq__ defined without __hash__. Objects will be unhashable (can't use in sets/dicts)."
        ))

    return findings


def check_comparison_pitfalls(filepath, lines):
    """Detect is/== confusion and None comparison issues."""
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        # `== None` instead of `is None`
        if re.search(r"==\s*None\b", stripped) or re.search(r"!=\s*None\b", stripped):
            findings.append(Finding(
                file=filepath, line=i, level=2, severity="info",
                check="none_comparison",
                message="Use `is None` / `is not None` instead of `== None` / `!= None`."
            ))

        # `== True` / `== False`
        if re.search(r"==\s*(True|False)\b", stripped):
            findings.append(Finding(
                file=filepath, line=i, level=2, severity="info",
                check="bool_comparison",
                message="Use `if x:` / `if not x:` instead of `== True` / `== False`."
            ))
    return findings


def check_bracket_mismatch(filepath, lines):
    """Detect mismatched brackets, parentheses, and braces."""
    findings = []
    pairs = {'(': ')', '[': ']', '{': '}'}
    openers = set(pairs.keys())
    closers = set(pairs.values())
    closer_to_opener = {v: k for k, v in pairs.items()}

    # Track across the whole file for overall mismatch
    stack = []  # (char, line_number)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        in_string = None
        prev_char = None
        for ch in line:
            # Track string state (skip brackets inside strings)
            if ch in ('"', "'") and prev_char != '\\':
                if in_string is None:
                    in_string = ch
                elif in_string == ch:
                    in_string = None
                prev_char = ch
                continue
            prev_char = ch

            if in_string:
                continue

            if ch in openers:
                stack.append((ch, i))
            elif ch in closers:
                expected_opener = closer_to_opener[ch]
                if stack and stack[-1][0] == expected_opener:
                    stack.pop()
                elif stack and stack[-1][0] != expected_opener:
                    findings.append(Finding(
                        file=filepath, line=i, level=2, severity="error",
                        check="bracket_mismatch",
                        message=f"Mismatched bracket: found `{ch}` but expected `{pairs[stack[-1][0]]}` (opened on line {stack[-1][1]})"
                    ))
                    stack.pop()
                else:
                    findings.append(Finding(
                        file=filepath, line=i, level=2, severity="error",
                        check="bracket_mismatch",
                        message=f"Unexpected closing `{ch}` with no matching opener"
                    ))

    # Report any unclosed brackets
    for ch, line_num in stack:
        findings.append(Finding(
            file=filepath, line=line_num, level=2, severity="error",
            check="bracket_mismatch",
            message=f"Unclosed `{ch}` — missing matching `{pairs[ch]}`"
        ))

    return findings


def check_assignment_comparison(filepath, lines):
    """Detect likely = vs == confusion."""
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        # Inside if/while/elif — single = is suspicious (not ==, !=, <=, >=, :=)
        if re.match(r"\s*(if|elif|while)\s+", line):
            # Find single = that's not ==, !=, <=, >=, :=
            condition = re.sub(r"(==|!=|<=|>=|:=)", "XX", line)
            if re.search(r"[^!<>:=]=[^=]", condition):
                findings.append(Finding(
                    file=filepath, line=i, level=2, severity="warning",
                    check="assign_in_condition",
                    message="Possible assignment `=` in condition — did you mean `==`?"
                ))
    return findings


# ============================================================
# Level 3 — Security Checks
# ============================================================

def check_command_injection(filepath, lines):
    """Detect potential command injection vectors."""
    findings = []
    patterns = [
        (r"\bos\.system\s*\(", "os.system() runs shell commands — use subprocess.run() without shell=True"),
        (r"\bos\.popen\s*\(", "os.popen() runs shell commands — use subprocess.run() instead"),
        (r"subprocess\.\w+\(.*shell\s*=\s*True", "subprocess with shell=True enables shell injection"),
        (r"\beval\s*\(", "eval() executes arbitrary code — avoid or restrict input"),
        (r"\bexec\s*\(", "exec() executes arbitrary code — avoid or restrict input"),
    ]
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for pattern, msg in patterns:
            if re.search(pattern, stripped):
                findings.append(Finding(
                    file=filepath, line=i, level=3, severity="error",
                    check="command_injection", message=msg
                ))
    return findings


def check_hardcoded_secrets(filepath, lines):
    """Detect hardcoded passwords, API keys, and tokens."""
    findings = []
    patterns = [
        (r"""(?:password|passwd|pwd)\s*=\s*['"][^'"]{4,}['"]""", "Hardcoded password"),
        (r"""(?:api_key|apikey|api_secret)\s*=\s*['"][^'"]{4,}['"]""", "Hardcoded API key"),
        (r"""(?:secret|secret_key)\s*=\s*['"][^'"]{4,}['"]""", "Hardcoded secret"),
        (r"""(?:token|access_token|auth_token)\s*=\s*['"][^'"]{8,}['"]""", "Hardcoded token"),
        (r"""(?:aws_access_key_id)\s*=\s*['"]AKIA[^'"]+['"]""", "Hardcoded AWS access key"),
    ]
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for pattern, label in patterns:
            if re.search(pattern, stripped, re.IGNORECASE):
                findings.append(Finding(
                    file=filepath, line=i, level=3, severity="error",
                    check="hardcoded_secret",
                    message=f"{label} detected. Move to environment variable or secrets manager."
                ))
    return findings


def check_timing_attack(filepath, lines):
    """Detect hand-rolled constant-time comparison functions."""
    findings = []
    full_text = "\n".join(lines)

    # Pattern: XOR accumulation loop for byte comparison
    if re.search(r"for\s+\w+\s+in\s+range\s*\(\s*len\s*\(", full_text):
        for i, line in enumerate(lines, 1):
            if re.search(r"\|=.*\^", line) or re.search(r"\^=", line):
                findings.append(Finding(
                    file=filepath, line=i, level=3, severity="error",
                    check="timing_attack",
                    message="Hand-rolled byte comparison with XOR — vulnerable to timing attacks. Use hmac.compare_digest() instead."
                ))

    # Early return on length mismatch in comparison function
    in_compare_func = False
    for i, line in enumerate(lines, 1):
        if re.search(r"def\s+\w*(compare|equal|eq|const).*\(", line, re.IGNORECASE):
            in_compare_func = True
        elif in_compare_func and line.strip().startswith("def "):
            in_compare_func = False
        if in_compare_func and re.search(r"if\s+len\s*\(.+\)\s*!=\s*len", line):
            # Check if next line is return False
            if i < len(lines) and "return False" in lines[i]:
                findings.append(Finding(
                    file=filepath, line=i, level=3, severity="error",
                    check="timing_attack",
                    message="Early return on length mismatch leaks timing information. Use hmac.compare_digest() which handles length differences in constant time."
                ))

    return findings


def check_insecure_deserialization(filepath, lines):
    """Detect unsafe deserialization."""
    findings = []
    patterns = [
        (r"\bpickle\.loads?\s*\(", "pickle.load() can execute arbitrary code. Use JSON or validate input."),
        (r"\byaml\.load\s*\((?!.*Loader\s*=\s*yaml\.SafeLoader)", "yaml.load() without SafeLoader can execute arbitrary code. Use yaml.safe_load()."),
        (r"\byaml\.unsafe_load\s*\(", "yaml.unsafe_load() can execute arbitrary code. Use yaml.safe_load()."),
        (r"\bmarshal\.loads?\s*\(", "marshal.load() can execute arbitrary code."),
    ]
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for pattern, msg in patterns:
            if re.search(pattern, stripped):
                findings.append(Finding(
                    file=filepath, line=i, level=3, severity="error",
                    check="insecure_deser", message=msg
                ))
    return findings


# ============================================================
# Level 4 — AI Safety Checks
# ============================================================

def check_prompt_injection(filepath, lines):
    """Detect potential prompt injections hidden in code/comments."""
    findings = []
    suspicious_phrases = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"you\s+are\s+now\s+a",
        r"disregard\s+(all\s+)?(above|prior|previous)",
        r"forget\s+(everything|all|your)\s+(above|instructions|rules)",
        r"new\s+instructions?\s*:",
        r"system\s*:\s*you\s+are",
        r"act\s+as\s+(if\s+you\s+are\s+)?a",
        r"pretend\s+(to\s+be|you\s+are)",
        r"do\s+not\s+follow\s+(the\s+)?(above|previous|prior)",
        r"override\s+(system|instructions|rules)",
    ]
    pattern = re.compile("|".join(suspicious_phrases), re.IGNORECASE)

    for i, line in enumerate(lines, 1):
        if pattern.search(line):
            findings.append(Finding(
                file=filepath, line=i, level=4, severity="error",
                check="prompt_injection",
                message=f"Possible prompt injection in code/comment. This string could confuse AI agents processing this file."
            ))
    return findings


def check_suspicious_encoded(filepath, lines):
    """Detect base64 or hex-encoded strings that might hide instructions."""
    findings = []
    b64_pattern = re.compile(r'["\']([A-Za-z0-9+/]{40,}={0,2})["\']')

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        match = b64_pattern.search(stripped)
        if match:
            encoded = match.group(1)
            try:
                decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
                # Check if decoded content looks like text/instructions
                if re.search(r"[a-zA-Z\s]{20,}", decoded):
                    preview = decoded[:60].replace("\n", " ")
                    findings.append(Finding(
                        file=filepath, line=i, level=4, severity="warning",
                        check="suspicious_encoded",
                        message=f"Base64 string decodes to readable text: \"{preview}...\" — verify this is intentional."
                    ))
            except Exception:
                pass
    return findings


def check_unusual_comments(filepath, lines):
    """Detect comments that look like commands rather than documentation."""
    findings = []
    command_patterns = [
        (r"#\s*(run|execute|call|invoke|trigger|send|post|delete|drop)\s+", "Comment reads like a command"),
        (r"#\s*\$\s*\w+", "Comment contains shell-style variable"),
        (r"#\s*(curl|wget|ssh|scp|rm\s+-rf)\s+", "Comment contains shell command"),
    ]
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        for pattern, label in command_patterns:
            if re.search(pattern, stripped, re.IGNORECASE):
                # Don't flag common dev comments
                if any(skip in stripped.lower() for skip in ["# run tests", "# run the", "# execute the", "# call the"]):
                    continue
                findings.append(Finding(
                    file=filepath, line=i, level=4, severity="info",
                    check="command_comment",
                    message=f"{label}. AI agents might interpret this as an instruction rather than documentation."
                ))
    return findings


# ============================================================
# Scanner — runs all checks
# ============================================================

# All checks organized by level
ALL_CHECKS = {
    1: [check_file_type, check_typos, check_todo_fixme, check_naming_consistency, check_unused_imports],
    2: [check_bare_except, check_mutable_defaults, check_equality_issues, check_comparison_pitfalls, check_bracket_mismatch, check_assignment_comparison],
    3: [check_command_injection, check_hardcoded_secrets, check_timing_attack, check_insecure_deserialization],
    4: [check_prompt_injection, check_suspicious_encoded, check_unusual_comments],
}

SUPPORTED_EXTS = {".py", ".rs", ".js", ".ts", ".c", ".h", ".go", ".rb", ".java", ".toml", ".md", ".txt"}


def scan_file(filepath, levels=None):
    """Scan a single file at the given calibration levels.

    Args:
        filepath: Path to the file
        levels: List of levels to run (default: [1, 2])

    Returns:
        List of Finding objects
    """
    if levels is None:
        levels = [1, 2]

    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    # Strip newlines for processing but keep them for line counting
    lines = [line.rstrip("\n") for line in lines]

    findings = []
    for level in levels:
        if level in ALL_CHECKS:
            for check_fn in ALL_CHECKS[level]:
                try:
                    results = check_fn(filepath, lines)
                    findings.extend(results)
                except Exception as e:
                    findings.append(Finding(
                        file=filepath, line=0, level=level, severity="info",
                        check="scanner_error",
                        message=f"Check {check_fn.__name__} failed: {e}"
                    ))

    # Sort by line number
    findings.sort(key=lambda f: (f.file, f.line))
    return findings


def scan_directory(dirpath, levels=None, ext_filter=None):
    """Scan all files in a directory recursively.

    Args:
        dirpath: Path to directory
        levels: Calibration levels to use (default: [1, 2])
        ext_filter: Optional list of extensions like [".py", ".rs"]

    Returns:
        List of Finding objects
    """
    if levels is None:
        levels = [1, 2]

    allowed_exts = set(ext_filter) if ext_filter else SUPPORTED_EXTS
    skip_dirs = {".git", "__pycache__", "node_modules", "target", ".venv", "venv", ".tox", "dist", "build"}

    findings = []
    for root, dirs, files in os.walk(dirpath):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            ext = Path(fname).suffix
            if ext in allowed_exts:
                findings.extend(scan_file(fpath, levels))

    findings.sort(key=lambda f: (f.file, f.line))
    return findings


# ============================================================
# Prompt Builder — generates the AI-ready prompt
# ============================================================

LEVEL_NAMES = {
    1: "Lint",
    2: "Bug Hunt",
    3: "Security",
    4: "AI Safety",
}


def build_prompt(findings, base_dir=""):
    """Build a structured prompt from findings that AI agents can act on.

    Args:
        findings: List of Finding objects
        base_dir: Base directory to make paths relative to

    Returns:
        Formatted prompt string
    """
    if not findings:
        return "✅ No issues found at the selected calibration levels."

    # Determine which levels were active
    active_levels = sorted(set(f.level for f in findings))
    level_str = " + ".join(LEVEL_NAMES.get(l, f"L{l}") for l in active_levels)

    # Group by file
    by_file = {}
    for f in findings:
        rel_path = f.file
        if base_dir:
            try:
                rel_path = os.path.relpath(f.file, base_dir)
            except ValueError:
                pass
        by_file.setdefault(rel_path, []).append(f)

    # Count stats
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    infos = sum(1 for f in findings if f.severity == "info")

    lines = []
    lines.append("I need you to review and fix the following issues in my codebase.")
    lines.append("Each issue includes the file, line number, and description.")
    lines.append("Go to each line and apply the fix.")
    lines.append("")
    lines.append(f"## Issues Found ({len(findings)} total — {level_str})")
    if errors:
        lines.append(f"🔴 {errors} errors | 🟡 {warnings} warnings | 🔵 {infos} info")
    lines.append("")

    for filepath, file_findings in sorted(by_file.items()):
        lines.append(f"### {filepath}")
        for f in file_findings:
            icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(f.severity, "⚪")
            lines.append(f"- {icon} **Line {f.line}** [{f.check}]: {f.message}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI entry point (for testing)
# ============================================================

if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    levels = [1, 2, 3, 4]

    if len(sys.argv) > 2:
        levels = [int(x) for x in sys.argv[2].split(",")]

    print(f"🔍 Scanning: {target}")
    print(f"📊 Calibration: {', '.join(LEVEL_NAMES.get(l, f'L{l}') for l in levels)}")
    print()

    if os.path.isfile(target):
        findings = scan_file(target, levels)
    else:
        findings = scan_directory(target, levels)

    prompt = build_prompt(findings, base_dir=target if os.path.isdir(target) else os.path.dirname(target))
    print(prompt)
    print(f"\n--- {len(findings)} findings ---")
