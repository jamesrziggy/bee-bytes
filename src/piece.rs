//! Piece Manager — BitTorrent-style data chunking for the GPU Seeder.
//!
//! Splits files into semantic pieces, computes embeddings for relevance
//! scoring, and hashes for deduplication.
//!
//! BitTorrent mapping:
//!   File on disk     → Torrent file
//!   Chunk of file    → Piece
//!   Piece hash       → Info hash (integrity + dedup)
//!   Piece embedding  → Used for relevance-first (replaces rarest-first)

use std::collections::hash_map::DefaultHasher;
use std::collections::HashMap;
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};

use crate::k::K;

/// A single piece — one chunk of data with its embedding.
///
/// BitTorrent equivalent: a piece in a .torrent file.
/// Each piece has:
///   - A unique hash (like BitTorrent's piece hash for integrity/dedup)
///   - Raw content (the actual data)
///   - An embedding vector (for relevance scoring via _dot)
///   - Source info (which file it came from)
#[derive(Clone, Debug)]
pub struct Piece {
    /// Unique piece ID
    pub id: usize,
    /// Hash of the content — used for dedup (BitTorrent: piece hash)
    pub hash: u64,
    /// Raw text content of this piece
    pub content: String,
    /// Source file path
    pub source: PathBuf,
    /// Starting line number in the source file (1-indexed)
    pub start_line: usize,
    /// Character/term frequency embedding — stored as K float array
    /// for direct use with _dot from va.rs
    pub embedding: K,
}

/// The Piece Manager — loads files, splits into pieces, computes embeddings.
///
/// BitTorrent equivalent: the torrent creator + piece hasher.
pub struct PieceManager {
    /// All pieces, indexed by ID
    pub pieces: Vec<Piece>,
    /// Hash → piece IDs (for dedup detection)
    pub hash_index: HashMap<u64, Vec<usize>>,
    /// Vocabulary for TF-IDF embeddings
    pub vocab: Vec<String>,
}

impl PieceManager {
    /// Load all files from a directory (all text extensions).
    pub fn from_directory(dir: &Path) -> PieceManager {
        Self::from_directory_filtered(dir, None)
    }

    /// Load files with optional extension filter.
    /// e.g. `Some(&["rs"])` to only index `.rs` files.
    pub fn from_directory_filtered(dir: &Path, ext_filter: Option<&[&str]>) -> PieceManager {
        let mut raw_chunks: Vec<(String, PathBuf, usize)> = Vec::new();
        Self::walk_dir(dir, &mut raw_chunks, ext_filter);
        let vocab = Self::build_vocab(&raw_chunks);
        let mut pieces = Vec::new();
        let mut hash_index: HashMap<u64, Vec<usize>> = HashMap::new();
        for (i, (content, source, start_line)) in raw_chunks.iter().enumerate() {
            let hash = Self::hash_content(content);
            let embedding = Self::compute_embedding(content, &vocab);
            hash_index.entry(hash).or_default().push(i);
            pieces.push(Piece {
                id: i,
                hash,
                content: content.clone(),
                source: source.clone(),
                start_line: *start_line,
                embedding,
            });
        }
        PieceManager { pieces, hash_index, vocab }
    }

    /// Walk a directory recursively, reading text files and splitting into chunks.
    fn walk_dir(dir: &Path, chunks: &mut Vec<(String, PathBuf, usize)>, ext_filter: Option<&[&str]>) {
        let entries = match fs::read_dir(dir) {
            Ok(e) => e,
            Err(_) => return,
        };
        let default_exts: &[&str] = &["rs", "toml", "md", "txt", "c", "h", "py", "js", "ts"];
        let allowed = ext_filter.unwrap_or(default_exts);
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                let name = path.file_name().unwrap_or_default().to_string_lossy();
                if !name.starts_with('.') && name != "target" {
                    Self::walk_dir(&path, chunks, ext_filter);
                }
            } else if path.is_file() {
                let ext = path.extension().unwrap_or_default().to_string_lossy();
                if allowed.iter().any(|a| *a == ext.as_ref()) {
                    if let Ok(content) = fs::read_to_string(&path) {
                        let file_chunks = Self::split_into_chunks(&content, 80);
                        for (chunk_text, line_num) in file_chunks {
                            if !chunk_text.trim().is_empty() {
                                chunks.push((chunk_text, path.clone(), line_num));
                            }
                        }
                    }
                }
            }
        }
    }

    /// Split content into chunks of approximately `max_lines` lines.
    ///
    /// Returns Vec<(chunk_text, start_line)> where start_line is 1-indexed.
    /// Tries to split at function/struct boundaries when possible.
    fn split_into_chunks(content: &str, max_lines: usize) -> Vec<(String, usize)> {
        let lines: Vec<&str> = content.lines().collect();

        if lines.len() <= max_lines {
            return vec![(content.to_string(), 1)];
        }

        let mut chunks = Vec::new();
        let mut start = 0;

        while start < lines.len() {
            let mut end = (start + max_lines).min(lines.len());

            // Try to find a natural break point (empty line, fn/struct boundary)
            // Look backwards from the max to find a good split point
            if end < lines.len() {
                let search_start = if end > 10 { end - 10 } else { start };
                for i in (search_start..end).rev() {
                    let line = lines[i].trim();
                    if line.is_empty()
                        || line.starts_with("fn ")
                        || line.starts_with("pub fn ")
                        || line.starts_with("struct ")
                        || line.starts_with("impl ")
                        || line.starts_with("// ==")
                    {
                        end = i;
                        break;
                    }
                }
            }

            let chunk: String = lines[start..end].join("\n");
            chunks.push((chunk, start + 1)); // 1-indexed line number
            start = end;
        }

        chunks
    }

    /// Hash content for dedup and integrity.
    /// BitTorrent equivalent: SHA-1 piece hash.
    /// Using a fast hash here — upgrade to SHA-256 for production.
    fn hash_content(content: &str) -> u64 {
        let mut hasher = DefaultHasher::new();
        content.hash(&mut hasher);
        hasher.finish()
    }

    /// Build vocabulary from all chunks — extract unique terms.
    /// Uses document frequency (how many chunks contain each term) for filtering.
    fn build_vocab(chunks: &[(String, PathBuf, usize)]) -> Vec<String> {
        // Count document frequency: how many chunks contain each term
        let mut doc_freq: HashMap<String, usize> = HashMap::new();

        for (content, _, _) in chunks {
            // Get unique terms in this chunk
            let mut seen_in_chunk: std::collections::HashSet<String> = std::collections::HashSet::new();
            for token in Self::tokenize(content) {
                seen_in_chunk.insert(token);
            }
            // Increment doc frequency for each unique term in this chunk
            for term in seen_in_chunk {
                *doc_freq.entry(term).or_insert(0) += 1;
            }
        }

        let n = chunks.len();
        // Keep all terms that appear in <= 100% of chunks.
        // Rare terms (df=1) are kept — they're the BEST discriminators
        // for needle-in-a-haystack finding. The 512 cap limits total size.
        let max_df = (n as f64 * 1.0).ceil() as usize;
        let mut vocab: Vec<(String, usize)> = doc_freq
            .into_iter()
            .filter(|(_, df)| *df >= 1 && *df <= max_df)
            .collect();

        // Sort by document frequency DESCENDING (most common first)
        // For "Language Modeling", we need common structure words (def, import, etc.)
        vocab.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
        
        // Cap vocabulary size — 20,000 to capture all sparse/rare terms (Needles)
        // 1024 was too small and got flooded by random noise codes.
        vocab.truncate(20_000);
        
        let mut result: Vec<String> = vocab.into_iter().map(|(term, _)| term).collect();
        result.sort(); // Sort alphabetically for consistent indexing

        result
    }

    /// Compute a TF-IDF-style embedding for a piece of text.
    ///
    /// Returns a K float array (from k.rs) so we can use _dot directly
    /// from va.rs for relevance scoring. No ML model needed — just
    /// term frequency vectors.
    fn compute_embedding(content: &str, vocab: &[String]) -> K {
        let tokens = Self::tokenize(content);
        let total = tokens.len() as f64;

        let mut vec = vec![0.0_f64; vocab.len()];

        if total == 0.0 {
            return K::from_floats(vec);
        }

        // Count term frequency
        let mut counts: HashMap<&str, usize> = HashMap::new();
        for token in &tokens {
            *counts.entry(token.as_str()).or_insert(0) += 1;
        }

        // Build TF vector (normalized by document length)
        for (i, term) in vocab.iter().enumerate() {
            if let Some(&count) = counts.get(term.as_str()) {
                vec[i] = count as f64 / total;
            }
        }

        // Normalize to unit length (so _dot gives cosine similarity)
        let magnitude: f64 = vec.iter().map(|x| x * x).sum::<f64>().sqrt();
        if magnitude > 0.0 {
            for v in &mut vec {
                *v /= magnitude;
            }
        }

        K::from_floats(vec)
    }

    /// Convert text to embedding (public, for queries).
    pub fn embed_query(&self, text: &str) -> K {
        Self::compute_embedding(text, &self.vocab)
    }

    /// Convert text to a sequence of Token IDs.
    /// Returns Vec<usize> where each usize is an index into self.vocab.
    /// Unknown tokens are skipped (or could be mapped to UNK if we had one).
    pub fn tokenize_to_ids(&self, text: &str) -> Vec<usize> {
        let tokens = Self::tokenize(text);
        let mut ids = Vec::new();
        // Naive O(N*V) lookup since vocab is small (1024).
        // If vocab grows, self.vocab should be a HashMap<String, usize>.
        // For now, linear scan is fine for "Nano SLM".
        for token in tokens {
            if let Some(pos) = self.vocab.iter().position(|v| v == &token) {
                ids.push(pos);
            }
        }
        ids
    }

    /// Simple tokenizer — split on non-alphanumeric, lowercase, filter short.
    fn tokenize(content: &str) -> Vec<String> {
        content
            .split(|c: char| !c.is_alphanumeric() && c != '_')
            .filter(|s| s.len() >= 2)
            .filter(|s| !s.chars().all(char::is_numeric)) // Skip pure numbers
            .map(|s| s.to_lowercase())
            .collect()
    }

    /// How many unique pieces (after dedup)?
    pub fn unique_count(&self) -> usize {
        self.hash_index.len()
    }

    /// How many duplicate pieces detected?
    pub fn dupe_count(&self) -> usize {
        self.pieces.len() - self.unique_count()
    }

    /// Vocabulary size (embedding dimension).
    pub fn vocab_size(&self) -> usize {
        self.vocab.len()
    }

    /// Decode an embedding vector back to top-N terms.
    /// Used for interpreting the model's output in the REPL.
    pub fn decode_embedding(&self, vec: &K, top_n: usize) -> Vec<(String, f64)> {
        let floats = vec.kf_data();
        if floats.len() != self.vocab.len() {
            // If dims mismatch (e.g. model output is smaller), we can't decode strictly.
            // But if model output IS same size (Auto-Encoder), we can.
            return vec![("dim_mismatch".to_string(), 0.0)];
        }

        let mut terms: Vec<(usize, f64)> = floats.iter().enumerate()
            .map(|(i, &score)| (i, score))
            .filter(|&(_, score)| score > 0.001) // Filter zero/noise
            .collect();

        // Sort by score descending
        terms.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        terms.truncate(top_n);

        terms.into_iter().map(|(i, score)| (self.vocab[i].clone(), score)).collect()
    }
}
