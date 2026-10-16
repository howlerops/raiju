// Native client spike, gpui build: providers on the left, the live request log on the right.
// `--headless` skips the window: it fetches the providers, waits for one live log event on /ws
// and prints both (used to check the data layer on a machine without a display).

mod data;

use data::{Config, LogEvent, Msg, Provider, clock, connect_logs, fetch_providers, is_timeout, run_feed};
use futures::{StreamExt, channel::mpsc};
use gpui::{
    App, Application, Bounds, Context, Entity, Render, Window, WindowBounds, WindowOptions, div,
    prelude::*, px, rgb, size,
};
use std::time::{Duration, Instant};

// The newest entries kept in the view; older ones are dropped.
const MAX_LOGS: usize = 500;
const HEADLESS_WAIT: Duration = Duration::from_secs(30);

struct Spike {
    status: String,
    providers: Vec<Provider>,
    // newest first
    logs: Vec<LogEvent>,
}

impl Spike {
    fn apply(&mut self, msg: Msg) {
        match msg {
            Msg::Providers(Ok(ps)) => self.providers = ps,
            Msg::Providers(Err(e)) => self.status = e,
            Msg::Connected => self.status = "live: connected to /ws".into(),
            Msg::Disconnected(e) => self.status = format!("offline: {e}"),
            Msg::Log(ev) => {
                self.logs.insert(0, ev);
                self.logs.truncate(MAX_LOGS);
            }
        }
    }
}

impl Render for Spike {
    fn render(&mut self, _window: &mut Window, _cx: &mut Context<Self>) -> impl IntoElement {
        let providers: Vec<_> = self
            .providers
            .iter()
            .map(|p| {
                div()
                    .flex()
                    .flex_col()
                    .px_3()
                    .py_2()
                    .border_b_1()
                    .border_color(rgb(0x333333))
                    .child(div().child(p.name.clone()))
                    .child(
                        div()
                            .text_xs()
                            .text_color(rgb(0x9a9a9a))
                            .child(format!("{} · {} keys", p.kind, p.keys)),
                    )
            })
            .collect();
        let rows: Vec<_> = self.logs.iter().map(log_row).collect();
        div()
            .size_full()
            .flex()
            .flex_col()
            .bg(rgb(0x1e1e1e))
            .text_color(rgb(0xe6e6e6))
            .text_sm()
            .child(
                div()
                    .px_3()
                    .py_2()
                    .border_b_1()
                    .border_color(rgb(0x333333))
                    .child(format!("Raiju · {}", self.status)),
            )
            .child(
                div()
                    .flex()
                    .flex_1()
                    .min_h_0()
                    .child(
                        div()
                            .id("providers")
                            .w(px(260.))
                            .h_full()
                            .overflow_y_scroll()
                            .border_r_1()
                            .border_color(rgb(0x333333))
                            .children(providers),
                    )
                    .child(
                        div()
                            .id("logs")
                            .flex_1()
                            .h_full()
                            .overflow_y_scroll()
                            .children(rows),
                    ),
            )
    }
}

fn log_row(e: &LogEvent) -> impl IntoElement {
    let status = if e.status >= 400 || e.status == 0 { rgb(0xff6b6b) } else { rgb(0x7ee787) };
    div()
        .flex()
        .gap_3()
        .px_3()
        .py_1()
        .border_b_1()
        .border_color(rgb(0x2a2a2a))
        .child(div().w(px(70.)).text_color(rgb(0x9a9a9a)).child(clock(e.ts_ms)))
        .child(div().flex_1().child(e.model.clone()))
        .child(div().w(px(50.)).text_color(status).child(e.status.to_string()))
        .child(div().w(px(80.)).child(format!("{:.0} ms", e.latency_ms)))
        .child(
            div()
                .w(px(110.))
                .child(format!("{} in / {} out", e.prompt_tokens, e.completion_tokens)),
        )
}

fn headless() -> i32 {
    let cfg = Config::from_env();
    match fetch_providers(&cfg) {
        Ok(ps) => {
            println!("providers: {}", ps.len());
            for p in &ps {
                println!("  {} kind={} keys={}", p.name, p.kind, p.keys);
            }
        }
        Err(e) => {
            eprintln!("{e}");
            return 1;
        }
    }
    let mut feed = match connect_logs(&cfg) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("{e}");
            return 1;
        }
    };
    println!("ws: connected to {}/ws", cfg.base);
    let deadline = Instant::now() + HEADLESS_WAIT;
    while Instant::now() < deadline {
        match feed.next_event() {
            Ok(Some(ev)) => {
                println!(
                    "log: {} {} {} status={} latency={:.0}ms tokens={}/{}",
                    clock(ev.ts_ms), ev.provider, ev.model, ev.status, ev.latency_ms,
                    ev.prompt_tokens, ev.completion_tokens
                );
                return 0;
            }
            Ok(None) => {
                eprintln!("ws: closed by the server");
                return 1;
            }
            Err(e) if is_timeout(&e) => {}
            Err(e) => {
                eprintln!("ws: {e}");
                return 1;
            }
        }
    }
    eprintln!("ws: no log event within {} s", HEADLESS_WAIT.as_secs());
    1
}

fn main() {
    if std::env::args().any(|a| a == "--headless") {
        std::process::exit(headless());
    }
    let cfg = Config::from_env();
    Application::new().run(move |cx: &mut App| {
        let bounds = Bounds::centered(None, size(px(1100.), px(640.)), cx);
        let (tx, rx) = mpsc::unbounded::<Msg>();
        std::thread::spawn(move || {
            run_feed(cfg, move |m| {
                let _ = tx.unbounded_send(m);
            })
        });
        cx.open_window(
            WindowOptions {
                window_bounds: Some(WindowBounds::Windowed(bounds)),
                ..Default::default()
            },
            move |_, cx| {
                let view: Entity<Spike> = cx.new(|_| Spike {
                    status: "connecting".into(),
                    providers: Vec::new(),
                    logs: Vec::new(),
                });
                // Feed messages arrive on a channel from the feed thread; the view applies them
                // on the UI thread and re-renders.
                let weak = view.downgrade();
                let mut rx = rx;
                cx.spawn(async move |cx| {
                    while let Some(msg) = rx.next().await {
                        if weak
                            .update(cx, |v, cx| {
                                v.apply(msg);
                                cx.notify();
                            })
                            .is_err()
                        {
                            break;
                        }
                    }
                })
                .detach();
                view
            },
        )
        .unwrap();
        cx.activate(true);
    });
}
