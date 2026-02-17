mod k;
mod va;
mod piece;
mod seeder;

use std::env;
use std::path::Path;
use std::time::Instant;

/// Escape a string for safe JSON embedding.
fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 16);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"'  => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out
}

fn main() {
    eprintln!("╔══════════════════════════════════════════════════════════╗");
    eprintln!("║   🐝 BEE BYTEZ — Hive Search Engine (Rust)             ║");
    eprintln!("╚══════════════════════════════════════════════════════════╝");
    eprintln!();

    // ---------------------------------------------------------------
    // Determine what to load: CLI arg or default to own source
    // ---------------------------------------------------------------
    let args: Vec<String> = env::args().collect();
    let ext_pos = args.iter().position(|a| a == "--ext");
    let ext_filter_str: Option<String> = ext_pos.and_then(|i| args.get(i + 1).cloned());
    let load_dir = args.iter()
        .enumerate()
        .skip(1)
        .filter(|(i, a)| {
            !a.starts_with("--") && 
            !ext_pos.map_or(false, |ep| *i == ep + 1)
        })
        .map(|(_, a)| Path::new(a).to_path_buf())
        .next()
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("src"));

    eprintln!("📂 Loading pieces from: {}", load_dir.display());
    if let Some(ref ext) = ext_filter_str {
        eprintln!("   Filter: .{} files only", ext);
    }
    eprintln!();

    // ---------------------------------------------------------------
    // Phase 1: Load pieces
    // ---------------------------------------------------------------
    let start = Instant::now();
    let manager = if let Some(ref ext) = ext_filter_str {
        let exts: Vec<&str> = ext.split(',').collect();
        piece::PieceManager::from_directory_filtered(&load_dir, Some(&exts))
    } else {
        piece::PieceManager::from_directory(&load_dir)
    };
    let load_time = start.elapsed();

    eprintln!("📦 Pieces loaded:");
    eprintln!("   Total pieces:   {}", manager.pieces.len());
    eprintln!("   Unique pieces:  {}", manager.unique_count());
    eprintln!("   Vocab size:     {} terms", manager.vocab_size());
    eprintln!("   Load time:      {:?}", load_time);
    eprintln!();

    // ---------------------------------------------------------------
    // Phase 2: Build the CPU swarm
    // ---------------------------------------------------------------
    let swarm = seeder::Swarm::from_pieces(&manager);
    eprintln!("🐝 Swarm: {} seeders, {} dims",
        swarm.seeder_count(), swarm.embedding_dim());
    eprintln!();

    // ---------------------------------------------------------------
    // JSON QUERY MODE: single query, JSON output to stdout
    // Usage: bee-bytez-rs /path/to/code --json-query "term1 term2 term3"
    // Used by the Flask web app to bridge Rust seeder to the frontend
    // ---------------------------------------------------------------
    let json_query_pos = args.iter().position(|a| a == "--json-query");
    let top_k_pos = args.iter().position(|a| a == "--top");
    let top_k: usize = top_k_pos
        .and_then(|i| args.get(i + 1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(10);

    if let Some(jq_pos) = json_query_pos {
        if let Some(query_text) = args.get(jq_pos + 1) {
            eprintln!("🐝 JSON query mode: \"{}\"", query_text);
            
            let start = Instant::now();
            let query_embedding = manager.embed_query(query_text);
            let results = swarm.query(&query_embedding, top_k);
            let elapsed = start.elapsed();
            
            eprintln!("   {} results in {:?}", results.len(), elapsed);
            
            // Output JSON to stdout
            let json_results: Vec<String> = results.iter().enumerate().map(|(rank, r)| {
                let source = json_escape(&r.source);
                let preview = json_escape(&r.preview);
                let content = json_escape(&r.content);
                format!(
                    r#"  {{"rank":{},"score":{:.6},"piece_id":{},"start_line":{},"file":"{}","preview":"{}","content":"{}"}}"#,
                    rank + 1, r.score, r.piece_id, r.start_line, source, preview, content
                )
            }).collect();
            
            println!("{{");
            println!(r#"  "query":"{}","#, json_escape(query_text));
            println!(r#"  "total_pieces":{},"#, swarm.seeder_count());
            println!(r#"  "query_time_us":{},"#, elapsed.as_micros());
            println!(r#"  "results":[{}"#, if json_results.is_empty() { "" } else { "\n" });
            println!("{}", json_results.join(",\n"));
            if !json_results.is_empty() { println!("  "); }
            println!("  ]");
            println!("}}");
            return;
        }
    }

    // ---------------------------------------------------------------
    // Interactive mode: run default queries
    // ---------------------------------------------------------------
    let queries: Vec<&str> = vec![
        "dot product multiply accumulate fused math",
        "K object type struct data integer float",
        "piece chunk split file hash",
        "seeder swarm query relevance",
        "plus minus times arithmetic",
    ];

    let overall_start = Instant::now();

    for (qi, query_text) in queries.iter().enumerate() {
        println!("═══════════════════════════════════════════════════════════");
        println!("🔍 Q{}: \"{}\"", qi + 1, query_text);
        println!("───────────────────────────────────────────────────────────");

        let start = Instant::now();
        let query_embedding = manager.embed_query(query_text);
        let results = swarm.query(&query_embedding, 3);
        let query_time = start.elapsed();

        for (rank, result) in results.iter().enumerate() {
            println!();
            println!("   #{} │ score: {:.6} │ piece #{} │ file: {}", rank + 1, result.score, result.piece_id, result.source);
            let lines: Vec<&str> = result.preview
                .lines()
                .filter(|l| !l.trim().is_empty() && !l.starts_with("---"))
                .take(3)
                .collect();
            for line in &lines {
                println!("      │ {}", line.trim());
            }
        }

        println!();
        println!("   ⏱  {:?}", query_time);
        println!();
    }

    let total_time = overall_start.elapsed();
    println!("╔══════════════════════════════════════════════════════════╗");
    println!("║  Done. {} pieces scored per query.{}║", 
        swarm.seeder_count(),
        " ".repeat(23 - swarm.seeder_count().to_string().len()));
    println!("╚══════════════════════════════════════════════════════════╝");
}
