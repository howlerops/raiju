// Data layer for the native client spike: the management API's provider list and the
// live request-log feed on /ws. Blocking calls; the UI decides which thread runs them.
// Copied unchanged into clients/slint-spike/src/data.rs.

use serde_json::Value;
use std::io::ErrorKind;
use tungstenite::client::IntoClientRequest;
use std::net::TcpStream;
use std::time::{Duration, Instant};

const HTTP_TIMEOUT: Duration = Duration::from_secs(5);
const READ_TICK: Duration = Duration::from_millis(500);
const PROVIDER_REFRESH: Duration = Duration::from_secs(10);
const RETRY_DELAY: Duration = Duration::from_secs(2);

// The gateway and the admin token. RAIJU_URL and RAIJU_TOKEN override the defaults.
#[derive(Clone, Debug)]
pub struct Config {
    pub base: String,
    pub token: String,
}

impl Config {
    pub fn from_env() -> Config {
        let base = std::env::var("RAIJU_URL").unwrap_or_else(|_| "http://127.0.0.1:18171".into());
        let token = std::env::var("RAIJU_TOKEN").unwrap_or_else(|_| "admin-secret".into());
        Config { base: base.trim_end_matches('/').to_string(), token }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Provider {
    pub name: String,
    pub kind: String,
    pub base_url: String,
    pub keys: usize,
}

// One request-log entry, as the /ws feed sends it (no bodies).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct LogEvent {
    pub ts_ms: f64,
    pub request_id: String,
    pub op: String,
    pub provider: String,
    pub model: String,
    pub status: i64,
    pub latency_ms: f64,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub cost: f64,
    pub cache_hit: bool,
    pub error: String,
}

// What the feed loop reports to the UI.
#[derive(Debug)]
pub enum Msg {
    Providers(Result<Vec<Provider>, String>),
    Connected,
    Disconnected(String),
    Log(LogEvent),
}

fn text(v: &Value, key: &str) -> String {
    v.get(key).and_then(Value::as_str).unwrap_or("").to_string()
}

fn num(v: &Value, key: &str) -> f64 {
    v.get(key).and_then(Value::as_f64).unwrap_or(0.0)
}

pub fn parse_providers(body: &str) -> Result<Vec<Provider>, String> {
    let v: Value = serde_json::from_str(body).map_err(|e| format!("providers: {e}"))?;
    let list = v
        .get("providers")
        .and_then(Value::as_array)
        .ok_or("providers: no providers array")?;
    Ok(list
        .iter()
        .map(|p| Provider {
            name: text(p, "name"),
            kind: text(p, "kind"),
            base_url: text(p, "base_url"),
            keys: p.get("keys").and_then(Value::as_array).map_or(0, |k| k.len()),
        })
        .collect())
}

// A /ws text frame: {"type": "log", "data": {...}}. Other frames give None.
pub fn parse_log_event(frame: &str) -> Option<LogEvent> {
    let v: Value = serde_json::from_str(frame).ok()?;
    if v.get("type").and_then(Value::as_str) != Some("log") {
        return None;
    }
    let d = v.get("data")?;
    Some(LogEvent {
        ts_ms: num(d, "ts"),
        request_id: text(d, "request_id"),
        op: text(d, "op"),
        provider: text(d, "provider"),
        model: text(d, "model"),
        status: num(d, "status") as i64,
        latency_ms: num(d, "latency_ms"),
        prompt_tokens: num(d, "prompt_tokens") as i64,
        completion_tokens: num(d, "completion_tokens") as i64,
        cost: num(d, "cost"),
        cache_hit: d.get("cache_hit").and_then(Value::as_bool).unwrap_or(false),
        error: text(d, "error"),
    })
}

// GET /api/providers with the admin bearer token.
pub fn fetch_providers(cfg: &Config) -> Result<Vec<Provider>, String> {
    let url = format!("{}/api/providers", cfg.base);
    let body = ureq::get(&url)
        .set("authorization", &format!("Bearer {}", cfg.token))
        .timeout(HTTP_TIMEOUT)
        .call()
        .map_err(|e| format!("GET /api/providers: {e}"))?
        .into_string()
        .map_err(|e| format!("GET /api/providers: {e}"))?;
    parse_providers(&body)
}

// A connected /ws socket. Reads time out every READ_TICK so the caller can do other work.
pub struct LogFeed {
    ws: tungstenite::WebSocket<TcpStream>,
}

// Opens /ws (plain ws only; this spike does not speak TLS).
pub fn connect_logs(cfg: &Config) -> Result<LogFeed, String> {
    let host = cfg
        .base
        .strip_prefix("http://")
        .ok_or("RAIJU_URL must start with http:// (no TLS in this spike)")?;
    // into_client_request adds the upgrade headers (the key among them); the token goes on top.
    let mut req = format!("ws://{host}/ws")
        .into_client_request()
        .map_err(|e| format!("ws request: {e}"))?;
    let auth = tungstenite::http::HeaderValue::from_str(&format!("Bearer {}", cfg.token))
        .map_err(|e| format!("ws token: {e}"))?;
    req.headers_mut().insert("authorization", auth);
    let stream = TcpStream::connect(host).map_err(|e| format!("connect {host}: {e}"))?;
    stream.set_read_timeout(Some(READ_TICK)).map_err(|e| e.to_string())?;
    let (ws, _resp) = tungstenite::client(req, stream).map_err(|e| format!("ws handshake: {e}"))?;
    Ok(LogFeed { ws })
}

impl LogFeed {
    // The next log entry. Ok(None) when the server closes; a timeout error (see is_timeout)
    // when nothing arrived within READ_TICK.
    pub fn next_event(&mut self) -> Result<Option<LogEvent>, tungstenite::Error> {
        loop {
            match self.ws.read()? {
                tungstenite::Message::Text(t) => {
                    if let Some(ev) = parse_log_event(&t) {
                        return Ok(Some(ev));
                    }
                }
                tungstenite::Message::Close(_) => return Ok(None),
                _ => {}
            }
        }
    }
}

pub fn is_timeout(e: &tungstenite::Error) -> bool {
    matches!(e, tungstenite::Error::Io(io) if io.kind() == ErrorKind::WouldBlock || io.kind() == ErrorKind::TimedOut)
}

// The feed loop for a UI: providers first, then the live log stream, with the provider list
// refreshed every PROVIDER_REFRESH. Reconnects after a failure. Never returns; run it on a
// background thread and let `emit` hand each message to the UI.
pub fn run_feed(cfg: Config, mut emit: impl FnMut(Msg)) {
    loop {
        emit(Msg::Providers(fetch_providers(&cfg)));
        let mut feed = match connect_logs(&cfg) {
            Ok(f) => f,
            Err(e) => {
                emit(Msg::Disconnected(e));
                std::thread::sleep(RETRY_DELAY);
                continue;
            }
        };
        emit(Msg::Connected);
        let mut last_refresh = Instant::now();
        loop {
            match feed.next_event() {
                Ok(Some(ev)) => emit(Msg::Log(ev)),
                Ok(None) => {
                    emit(Msg::Disconnected("server closed /ws".into()));
                    break;
                }
                Err(e) if is_timeout(&e) => {}
                Err(e) => {
                    emit(Msg::Disconnected(e.to_string()));
                    break;
                }
            }
            if last_refresh.elapsed() >= PROVIDER_REFRESH {
                emit(Msg::Providers(fetch_providers(&cfg)));
                last_refresh = Instant::now();
            }
        }
        std::thread::sleep(RETRY_DELAY);
    }
}

// HH:MM:SS (UTC) for a unix time in milliseconds.
pub fn clock(ts_ms: f64) -> String {
    let secs = (ts_ms / 1000.0).floor() as i64;
    let day = secs.rem_euclid(86_400);
    format!("{:02}:{:02}:{:02}", day / 3600, (day % 3600) / 60, day % 60)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn providers_parse_names_kinds_and_key_counts() {
        let body = r#"{"providers":[{"name":"openai","kind":"openai","base_url":"","keys":[{"name":"k1"},{"name":"k2"}]},{"name":"anthropic","kind":"anthropic","keys":[]}]}"#;
        let ps = parse_providers(body).unwrap();
        assert_eq!(ps.len(), 2);
        assert_eq!(ps[0], Provider { name: "openai".into(), kind: "openai".into(), base_url: "".into(), keys: 2 });
        assert_eq!(ps[1].keys, 0);
        assert!(parse_providers("{}").is_err());
    }

    #[test]
    fn log_frames_parse_and_other_frames_are_skipped() {
        let frame = r#"{"type":"log","data":{"ts":1792119710633,"request_id":"req_1","op":"chat","provider":"openai","model":"openai/gpt-4o-mini","status":200,"prompt_tokens":3,"completion_tokens":4,"cost":0.00000285,"latency_ms":12.5,"cache_hit":true}}"#;
        let ev = parse_log_event(frame).unwrap();
        assert_eq!(ev.model, "openai/gpt-4o-mini");
        assert_eq!((ev.status, ev.prompt_tokens, ev.completion_tokens), (200, 3, 4));
        assert!(ev.cache_hit);
        assert_eq!(ev.latency_ms, 12.5);
        assert!(parse_log_event(r#"{"type":"store_update","data":{}}"#).is_none());
        assert!(parse_log_event("not json").is_none());
    }

    #[test]
    fn clock_is_utc_time_of_day() {
        assert_eq!(clock(0.0), "00:00:00");
        assert_eq!(clock(1792119710633.0), "03:01:50");
    }
}
