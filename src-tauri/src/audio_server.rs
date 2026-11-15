//! Loopback HTTP server that streams generated audio passages to the WebView.
//!
//! The server binds 127.0.0.1 on an ephemeral port and serves only
//! `GET`/`HEAD /v1/<token>/<document sha256>/<passage index>`. The 256-bit
//! token is compared in constant time and the `Host` header must match
//! exactly, which defeats DNS rebinding. File paths never come from the URL:
//! a lookup function maps the route to a manifest entry, and the server
//! refuses any file that does not canonicalize inside the chunks directory.
//!
//! Each connection is served on its own thread, up to [`MAX_CONNECTIONS`] at
//! once, so one slow or stalled client cannot hold up playback. Bodies are
//! streamed from disk rather than buffered in memory.

use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const MAX_HTTP_REQUEST_BYTES: usize = 16 * 1024;
/// Connections served at once. The media element needs one or two, plus a
/// prefetch; more than this from a loopback client is misbehaviour.
const MAX_CONNECTIONS: usize = 8;
const READ_TIMEOUT: Duration = Duration::from_secs(3);
/// Longest time a client may take to send its whole request head.
const REQUEST_DEADLINE: Duration = Duration::from_secs(5);
/// A paused media element can stop reading; give up on it after this.
const WRITE_TIMEOUT: Duration = Duration::from_secs(10);
const ACCEPT_POLL: Duration = Duration::from_millis(20);
const MAX_ACCEPT_BACKOFF: Duration = Duration::from_millis(640);

/// What the session knows about one requested passage.
pub(crate) enum AudioLookup {
    /// The manifest's file for the passage and the directory it must be in.
    Passage {
        audio_file: PathBuf,
        chunks_root: PathBuf,
    },
    /// No active session for this document, or no such passage.
    NotFound,
    /// The passage exists but its audio directory cannot be located.
    Unavailable,
    /// Reader state could not be read (a poisoned lock).
    StateError,
}

pub(crate) type LookupFn = dyn Fn(&str, usize) -> AudioLookup + Send + Sync;

struct ServerConfig {
    token: String,
    expected_host: String,
    lookup: Arc<LookupFn>,
}

pub(crate) struct AudioServer {
    pub(crate) base_url: String,
    stopped: Arc<AtomicBool>,
    thread: Mutex<Option<thread::JoinHandle<()>>>,
}

impl AudioServer {
    pub(crate) fn start(lookup: Arc<LookupFn>) -> io::Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        listener.set_nonblocking(true)?;
        let port = listener.local_addr()?.port();
        let config = Arc::new(ServerConfig {
            token: random_token()?,
            expected_host: format!("127.0.0.1:{port}"),
            lookup,
        });
        let base_url = format!("http://127.0.0.1:{port}/v1/{}", config.token);
        let stopped = Arc::new(AtomicBool::new(false));
        let thread_stopped = Arc::clone(&stopped);
        let worker = thread::Builder::new()
            .name("sonara-local-audio-http".to_owned())
            .spawn(move || accept_loop(&listener, &config, &thread_stopped))?;
        Ok(Self {
            base_url,
            stopped,
            thread: Mutex::new(Some(worker)),
        })
    }

    pub(crate) fn stop(&self) {
        self.stopped.store(true, Ordering::SeqCst);
        if let Ok(mut worker) = self.thread.lock() {
            if let Some(worker) = worker.take() {
                let _ = worker.join();
            }
        }
    }
}

impl Drop for AudioServer {
    fn drop(&mut self) {
        self.stop();
    }
}

fn random_token() -> io::Result<String> {
    let mut random = [0_u8; 32];
    getrandom::fill(&mut random).map_err(|error| {
        io::Error::other(format!(
            "Could not create a local audio access token: {error}"
        ))
    })?;
    Ok(random.iter().map(|byte| format!("{byte:02x}")).collect())
}

/// Releases a connection slot when the connection's thread finishes, or when
/// the thread could not be started and its closure is dropped.
struct ConnectionSlot(Arc<AtomicUsize>);

impl Drop for ConnectionSlot {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

fn accept_loop(listener: &TcpListener, config: &Arc<ServerConfig>, stopped: &AtomicBool) {
    let in_flight = Arc::new(AtomicUsize::new(0));
    let mut backoff = ACCEPT_POLL;
    while !stopped.load(Ordering::SeqCst) {
        match listener.accept() {
            Ok((stream, _)) => {
                backoff = ACCEPT_POLL;
                // BSD and macOS hand out accepted sockets that inherit the
                // listener's non-blocking mode; the handler needs blocking reads.
                if stream.set_nonblocking(false).is_err() {
                    continue;
                }
                if in_flight.fetch_add(1, Ordering::SeqCst) >= MAX_CONNECTIONS {
                    in_flight.fetch_sub(1, Ordering::SeqCst);
                    reject_busy(stream);
                    continue;
                }
                let slot = ConnectionSlot(Arc::clone(&in_flight));
                let config = Arc::clone(config);
                let spawned = thread::Builder::new()
                    .name("sonara-audio-connection".to_owned())
                    .spawn(move || {
                        let _slot = slot;
                        serve_connection(&config, stream);
                    });
                if spawned.is_err() {
                    // Out of threads: the dropped closure closed the socket and
                    // freed the slot. Pause before accepting more.
                    thread::sleep(MAX_ACCEPT_BACKOFF);
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                thread::sleep(ACCEPT_POLL);
            }
            Err(_) => {
                // Aborted handshakes, interrupts and descriptor exhaustion are
                // transient. Back off and keep serving rather than exiting.
                thread::sleep(backoff);
                backoff = (backoff * 2).min(MAX_ACCEPT_BACKOFF);
            }
        }
    }
}

/// Refuse a connection over the limit without blocking the accept loop.
fn reject_busy(mut stream: TcpStream) {
    let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));
    let _ = write_head(&mut stream, 503, "text/plain", 4, None);
    let _ = stream.write_all(b"Busy");
    let _ = stream.shutdown(Shutdown::Write);
    // Read whatever request bytes already arrived, without waiting, so the
    // close is a clean FIN rather than a reset that discards the reply.
    if stream.set_nonblocking(true).is_ok() {
        let mut sink = [0_u8; 4096];
        while matches!(stream.read(&mut sink), Ok(count) if count > 0) {}
    }
}

/// Read the request head, up to the blank line that ends it.
fn read_request_head(stream: &mut TcpStream) -> Result<Vec<u8>, Option<u16>> {
    let started = Instant::now();
    let mut bytes = Vec::with_capacity(2048);
    let mut buffer = [0_u8; 2048];
    loop {
        if started.elapsed() > REQUEST_DEADLINE {
            return Err(None);
        }
        match stream.read(&mut buffer) {
            Ok(0) | Err(_) => return Err(None),
            Ok(count) => {
                if bytes.len() + count > MAX_HTTP_REQUEST_BYTES {
                    return Err(Some(431));
                }
                bytes.extend_from_slice(&buffer[..count]);
                if bytes.windows(4).any(|window| window == b"\r\n\r\n") {
                    return Ok(bytes);
                }
            }
        }
    }
}

fn serve_connection(config: &ServerConfig, mut stream: TcpStream) {
    let _ = stream.set_read_timeout(Some(READ_TIMEOUT));
    let _ = stream.set_write_timeout(Some(WRITE_TIMEOUT));
    let bytes = match read_request_head(&mut stream) {
        Ok(bytes) => bytes,
        Err(Some(status)) => return write_text(&mut stream, status, "Request too large"),
        Err(None) => return,
    };

    let request_text = String::from_utf8_lossy(&bytes);
    let mut lines = request_text.split("\r\n");
    let request_line = lines.next().unwrap_or_default();
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts.next().unwrap_or_default();
    let path = request_parts.next().unwrap_or_default();
    let version = request_parts.next().unwrap_or_default();
    if (version != "HTTP/1.0" && version != "HTTP/1.1") || path.contains('?') {
        return write_text(&mut stream, 400, "Malformed request");
    }
    if method != "GET" && method != "HEAD" {
        return write_text(&mut stream, 405, "Method not allowed");
    }

    let mut host = None;
    let mut range = None;
    for line in lines.take_while(|line| !line.is_empty()) {
        if let Some((name, value)) = line.split_once(':') {
            if name.eq_ignore_ascii_case("host") {
                host = Some(value.trim());
            } else if name.eq_ignore_ascii_case("range") {
                range = Some(value.trim());
            }
        }
    }
    if host != Some(config.expected_host.as_str()) {
        return write_text(&mut stream, 421, "Unexpected host");
    }
    let Ok((document_hash, index)) = parse_audio_route(path, &config.token) else {
        return write_text(&mut stream, 404, "Audio passage not found");
    };
    let (audio_file, chunks_root) = match (config.lookup)(document_hash, index) {
        AudioLookup::Passage {
            audio_file,
            chunks_root,
        } => (audio_file, chunks_root),
        AudioLookup::NotFound => return write_text(&mut stream, 404, "Audio passage not found"),
        AudioLookup::Unavailable => {
            return write_text(&mut stream, 404, "Generated audio unavailable")
        }
        AudioLookup::StateError => return write_text(&mut stream, 500, "Reader state unavailable"),
    };
    let Some(mut file) = open_contained(&audio_file, &chunks_root) else {
        return write_text(&mut stream, 404, "Generated audio unavailable");
    };
    let file_length = match file.metadata() {
        Ok(metadata) if metadata.is_file() => metadata.len(),
        _ => return write_text(&mut stream, 404, "Generated audio unavailable"),
    };
    let (start, end, partial) = match range {
        Some(value) => match parse_byte_range(value, file_length) {
            Some((start, end)) => (start, end, true),
            None => {
                let _ = write_head(
                    &mut stream,
                    416,
                    "audio/wav",
                    0,
                    Some(format!("bytes */{file_length}")),
                );
                return;
            }
        },
        None => (0, file_length, false),
    };
    let content_length = end - start;
    if method == "GET" && file.seek(SeekFrom::Start(start)).is_err() {
        return write_text(&mut stream, 500, "Could not read audio");
    }
    let content_range = partial.then(|| format!("bytes {start}-{}/{file_length}", end - 1));
    let status = if partial { 206 } else { 200 };
    if write_head(
        &mut stream,
        status,
        "audio/wav",
        content_length,
        content_range,
    )
    .is_err()
        || method == "HEAD"
    {
        return;
    }
    // The status line is already sent, so a short copy (the file shrank, or
    // the client went away) can only end the connection early; the client
    // sees fewer bytes than Content-Length and treats it as an error.
    let _ = io::copy(&mut file.take(content_length), &mut stream);
}

/// Open `audio_file` only if it resolves, after symlinks, inside `chunks_root`.
fn open_contained(audio_file: &Path, chunks_root: &Path) -> Option<File> {
    let chunks_root = chunks_root.canonicalize().ok()?;
    let audio_path = audio_file.canonicalize().ok()?;
    if !audio_path.starts_with(&chunks_root) || !audio_path.is_file() {
        return None;
    }
    File::open(audio_path).ok()
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        206 => "Partial Content",
        400 => "Bad Request",
        404 => "Not Found",
        405 => "Method Not Allowed",
        416 => "Range Not Satisfiable",
        421 => "Misdirected Request",
        431 => "Request Header Fields Too Large",
        503 => "Service Unavailable",
        _ => "Internal Server Error",
    }
}

fn write_head(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    content_length: u64,
    content_range: Option<String>,
) -> io::Result<()> {
    let mut headers = format!(
        "HTTP/1.1 {status} {}\r\nContent-Type: {content_type}\r\nContent-Length: {content_length}\r\nConnection: close\r\n",
        reason_phrase(status)
    );
    if content_type == "audio/wav" {
        headers.push_str("Accept-Ranges: bytes\r\n");
    }
    if let Some(content_range) = content_range {
        headers.push_str(&format!("Content-Range: {content_range}\r\n"));
    }
    if status == 503 {
        headers.push_str("Retry-After: 1\r\n");
    }
    headers.push_str("Cache-Control: no-store\r\n\r\n");
    stream.write_all(headers.as_bytes())
}

fn write_text(stream: &mut TcpStream, status: u16, message: &str) {
    if write_head(stream, status, "text/plain", message.len() as u64, None).is_ok() {
        let _ = stream.write_all(message.as_bytes());
    }
}

pub(crate) fn parse_byte_range(header_value: &str, size: u64) -> Option<(u64, u64)> {
    if size == 0 {
        return None;
    }
    let range = header_value.strip_prefix("bytes=")?;
    if range.contains(',') {
        return None;
    }
    let (start_text, end_text) = range.split_once('-')?;
    if start_text.is_empty() {
        let suffix_length = end_text.parse::<u64>().ok()?;
        return (suffix_length > 0).then(|| (size.saturating_sub(suffix_length), size));
    }
    let start = start_text.parse::<u64>().ok()?;
    if start >= size {
        return None;
    }
    let end = if end_text.is_empty() {
        size - 1
    } else {
        end_text.parse::<u64>().ok()?.min(size - 1)
    };
    (end >= start).then_some((start, end + 1))
}

pub(crate) fn parse_audio_route<'a>(path: &'a str, token: &str) -> Result<(&'a str, usize), u16> {
    if path.contains('?') {
        return Err(404);
    }
    let Some(path) = path.strip_prefix('/') else {
        return Err(404);
    };
    let parts: Vec<_> = path.split('/').collect();
    if parts.len() != 4 || parts[0] != "v1" || !constant_time_eq(parts[1], token) {
        return Err(404);
    }
    if crate::session::validate_hash(parts[2]).is_err() {
        return Err(404);
    }
    let index = parts[3].parse::<usize>().map_err(|_| 404_u16)?;
    Ok((parts[2], index))
}

/// Compare without an early exit, so response timing does not reveal how
/// many leading characters of a guessed token were right. The token length
/// (64 hex characters) is not secret.
fn constant_time_eq(candidate: &str, secret: &str) -> bool {
    let (candidate, secret) = (candidate.as_bytes(), secret.as_bytes());
    if candidate.len() != secret.len() {
        return false;
    }
    let difference = candidate
        .iter()
        .zip(secret)
        .fold(0_u8, |acc, (left, right)| acc | (left ^ right));
    std::hint::black_box(difference) == 0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::make_job_id;
    use crate::session::{session_audio_lookup, ReaderChunk, ReaderSession};
    use crate::AppState;
    use std::fs;

    #[test]
    fn local_audio_route_requires_token_and_valid_document_path() {
        let token = "a".repeat(64);
        let hash = "b".repeat(64);
        assert_eq!(
            parse_audio_route(&format!("/v1/{token}/{hash}/3"), &token),
            Ok((hash.as_str(), 3))
        );
        assert!(parse_audio_route(&format!("/v1/wrong/{hash}/3"), &token).is_err());
        assert!(parse_audio_route(&format!("/v1/{}/{hash}/3", "a".repeat(63)), &token).is_err());
        assert!(parse_audio_route(&format!("/v1/{token}/../3"), &token).is_err());
        assert!(
            parse_audio_route(&format!("/v1/{token}/{hash}/3?file=/etc/passwd"), &token).is_err()
        );
    }

    #[test]
    fn token_comparison_checks_every_byte_and_the_length() {
        assert!(constant_time_eq("abcd", "abcd"));
        assert!(!constant_time_eq("abce", "abcd"));
        assert!(!constant_time_eq("xbcd", "abcd"));
        assert!(!constant_time_eq("abc", "abcd"));
        assert!(!constant_time_eq("", "abcd"));
    }

    #[test]
    fn local_audio_ranges_cover_open_ended_and_suffix_requests() {
        assert_eq!(parse_byte_range("bytes=10-19", 100), Some((10, 20)));
        assert_eq!(parse_byte_range("bytes=90-", 100), Some((90, 100)));
        assert_eq!(parse_byte_range("bytes=-5", 100), Some((95, 100)));
        assert_eq!(parse_byte_range("bytes=100-", 100), None);
        assert_eq!(parse_byte_range("bytes=1-2,4-5", 100), None);
    }

    /// A temporary reader-output tree behind a running `AudioServer`.
    struct AudioFixture {
        root: PathBuf,
        server: AudioServer,
        host: String,
        token: String,
        hash: String,
    }

    const BODY_LEN: usize = 1000;
    /// Larger than any copy buffer, so the body is written in many pieces.
    const LARGE_LEN: usize = 3 * 1024 * 1024 + 17;
    const GOOD: usize = 0;
    const OUTSIDE: usize = 1;
    const LARGE: usize = 2;
    #[cfg(unix)]
    const SYMLINK: usize = 3;

    fn pattern(len: usize) -> Vec<u8> {
        (0..len).map(|i| (i % 251) as u8).collect()
    }

    impl AudioFixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("sonara-audio-test-{}", make_job_id()));
            let reader_output = root.join("reader-output");
            let chunks = reader_output.join("chunks/doc");
            fs::create_dir_all(&chunks).unwrap();
            let good = chunks.join("chunk-0.wav");
            fs::write(&good, pattern(BODY_LEN)).unwrap();
            // Inside reader-output but outside chunks/: must not be served.
            let outside = reader_output.join("secret.wav");
            fs::write(&outside, b"not audio").unwrap();
            let large = chunks.join("chunk-large.wav");
            fs::write(&large, pattern(LARGE_LEN)).unwrap();
            #[allow(unused_mut)]
            let mut chunk_files = vec![good, outside.clone(), large];
            #[cfg(unix)]
            {
                let link = chunks.join("escape.wav");
                std::os::unix::fs::symlink(&outside, &link).unwrap();
                chunk_files.push(link);
            }
            let hash = "ab".repeat(32);
            let state = Arc::new(AppState::default());
            *state.session.lock().unwrap() = Some(ReaderSession {
                source_name: "doc.pdf".to_owned(),
                source_sha256: hash.clone(),
                narration_ruleset_version: "rules-test".to_owned(),
                voice: "test".to_owned(),
                engine: "piper".to_owned(),
                sample_rate: 22050,
                channels: 1,
                sample_width_bytes: 2,
                chunks: chunk_files
                    .into_iter()
                    .map(|path| ReaderChunk {
                        audio_file: path.to_string_lossy().into_owned(),
                        duration_seconds: 1.0,
                        pause_after_ms: 0,
                    })
                    .collect(),
            });
            let server = AudioServer::start(Arc::new(move |hash: &str, index: usize| {
                session_audio_lookup(&state, Some(&reader_output), hash, index)
            }))
            .unwrap();
            let rest = server.base_url.strip_prefix("http://").unwrap();
            let (host, token) = rest.split_once("/v1/").unwrap();
            Self {
                host: host.to_owned(),
                token: token.to_owned(),
                root,
                server,
                hash,
            }
        }

        fn path(&self, index: usize) -> String {
            format!("/v1/{}/{}/{index}", self.token, self.hash)
        }

        /// Send a raw request and return (status, headers, body).
        fn send(&self, raw: &str) -> (u16, String, Vec<u8>) {
            let mut client = TcpStream::connect(&self.host).unwrap();
            client
                .write_all(raw.replace("{HOST}", &self.host).as_bytes())
                .unwrap();
            read_response(client)
        }

        fn get(&self, path: &str, extra_headers: &str) -> (u16, String, Vec<u8>) {
            self.send(&format!(
                "GET {path} HTTP/1.1\r\nHost: {{HOST}}\r\n{extra_headers}\r\n"
            ))
        }
    }

    fn read_response(mut client: TcpStream) -> (u16, String, Vec<u8>) {
        let mut response = Vec::new();
        client.read_to_end(&mut response).unwrap();
        let split = response
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .expect("response has a header terminator");
        let headers = String::from_utf8_lossy(&response[..split]).into_owned();
        let status = headers[9..12].parse().unwrap();
        (status, headers, response[split + 4..].to_vec())
    }

    impl Drop for AudioFixture {
        fn drop(&mut self) {
            self.server.stop();
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    #[test]
    fn audio_server_serves_whole_ranged_and_head_requests() {
        let fixture = AudioFixture::new();
        let (status, headers, body) = fixture.get(&fixture.path(GOOD), "");
        assert_eq!(status, 200);
        assert_eq!(body, pattern(BODY_LEN));
        assert!(headers.contains("Accept-Ranges: bytes"));
        assert!(headers.contains("Cache-Control: no-store"));

        let (status, headers, body) = fixture.get(&fixture.path(GOOD), "Range: bytes=10-19\r\n");
        assert_eq!(status, 206);
        assert!(headers.contains("Content-Range: bytes 10-19/1000"));
        assert_eq!(body, pattern(20)[10..]);

        let (status, headers, _) = fixture.get(&fixture.path(GOOD), "Range: bytes=5000-\r\n");
        assert_eq!(status, 416);
        assert!(headers.contains("Content-Range: bytes */1000"));

        let (status, headers, body) = fixture.send(&format!(
            "HEAD {} HTTP/1.1\r\nHost: {{HOST}}\r\n\r\n",
            fixture.path(GOOD)
        ));
        assert_eq!(status, 200);
        assert!(headers.contains("Content-Length: 1000"));
        assert!(body.is_empty());
    }

    #[test]
    fn audio_server_streams_large_passages_and_ranges_within_them() {
        let fixture = AudioFixture::new();
        let (status, headers, body) = fixture.get(&fixture.path(LARGE), "");
        assert_eq!(status, 200);
        assert!(headers.contains(&format!("Content-Length: {LARGE_LEN}")));
        assert!(
            body == pattern(LARGE_LEN),
            "streamed body must match the file"
        );

        let start = 2 * 1024 * 1024 + 3;
        let (status, headers, body) =
            fixture.get(&fixture.path(LARGE), &format!("Range: bytes={start}-\r\n"));
        assert_eq!(status, 206);
        assert!(headers.contains(&format!(
            "Content-Range: bytes {start}-{}/{LARGE_LEN}",
            LARGE_LEN - 1
        )));
        assert!(body == pattern(LARGE_LEN)[start..]);
    }

    #[test]
    fn audio_server_rejects_bad_host_token_method_and_query() {
        let fixture = AudioFixture::new();
        let wrong_host = fixture.send(&format!(
            "GET {} HTTP/1.1\r\nHost: evil.example:80\r\n\r\n",
            fixture.path(GOOD)
        ));
        assert_eq!(wrong_host.0, 421, "DNS-rebinding hosts must be refused");

        let wrong_token = format!("/v1/{}/{}/0", "0".repeat(64), fixture.hash);
        assert_eq!(fixture.get(&wrong_token, "").0, 404);

        let post = fixture.send(&format!(
            "POST {} HTTP/1.1\r\nHost: {{HOST}}\r\n\r\n",
            fixture.path(GOOD)
        ));
        assert_eq!(post.0, 405);

        let query = format!("{}?x=1", fixture.path(GOOD));
        assert_eq!(fixture.get(&query, "").0, 400);

        let oversized = format!(
            "GET {} HTTP/1.1\r\nHost: {{HOST}}\r\nX-Pad: {}\r\n\r\n",
            fixture.path(GOOD),
            "a".repeat(MAX_HTTP_REQUEST_BYTES)
        );
        assert_eq!(fixture.send(&oversized).0, 431);
    }

    #[test]
    fn audio_server_serves_only_files_inside_the_active_chunks_directory() {
        let fixture = AudioFixture::new();
        let other_document = format!("/v1/{}/{}/0", fixture.token, "cd".repeat(32));
        assert_eq!(fixture.get(&other_document, "").0, 404);
        assert_eq!(fixture.get(&fixture.path(99), "").0, 404);
        // A manifest entry outside chunks/ is refused even though it exists.
        let (status, _, body) = fixture.get(&fixture.path(OUTSIDE), "");
        assert_eq!(status, 404);
        assert!(!body.starts_with(b"not audio"));
        #[cfg(unix)]
        {
            // A symlink inside chunks/ that points outside it is refused.
            let (status, _, body) = fixture.get(&fixture.path(SYMLINK), "");
            assert_eq!(status, 404);
            assert!(!body.starts_with(b"not audio"));
        }
    }

    #[test]
    fn a_stalled_client_does_not_hold_up_other_requests() {
        let fixture = AudioFixture::new();
        // Connects and sends half a request, then goes quiet. A serial server
        // would wait for its read timeout before serving anyone else.
        let mut stalled = TcpStream::connect(&fixture.host).unwrap();
        stalled.write_all(b"GET /v1/").unwrap();
        thread::sleep(Duration::from_millis(100));

        let started = Instant::now();
        assert_eq!(fixture.get(&fixture.path(GOOD), "").0, 200);
        assert!(
            started.elapsed() < READ_TIMEOUT / 2,
            "request waited {:?} behind a stalled client",
            started.elapsed()
        );
        drop(stalled);
    }

    #[test]
    fn connections_over_the_limit_are_refused_with_503() {
        let fixture = AudioFixture::new();
        let idle: Vec<_> = (0..MAX_CONNECTIONS)
            .map(|_| TcpStream::connect(&fixture.host).unwrap())
            .collect();
        // Accepted in order, so this one arrives after every slot is taken.
        let extra = TcpStream::connect(&fixture.host).unwrap();
        let (status, headers, _) = read_response(extra);
        assert_eq!(status, 503);
        assert!(headers.contains("Retry-After: 1"));

        // Closing the idle clients frees their slots for new requests.
        drop(idle);
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            let (status, _, _) = fixture.get(&fixture.path(GOOD), "");
            if status == 200 {
                break;
            }
            assert!(Instant::now() < deadline, "slots were never released");
            thread::sleep(Duration::from_millis(20));
        }
    }
}
