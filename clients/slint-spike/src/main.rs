// Native client spike, Slint build: providers on the left, the live request log on the right.
// `--headless` skips the window: it fetches the providers, waits for one live log event on /ws
// and prints both. `--screenshot PATH` renders one frame with the software renderer and no
// display, after collecting the feed for a few seconds, and saves it as a PNG.

mod data;

slint::include_modules!();

use data::{Config, LogEvent, Msg, Provider, clock, connect_logs, fetch_providers, is_timeout, run_feed};
use slint::{Model, ModelRc, VecModel};
use std::cell::RefCell;
use std::rc::Rc;
use std::time::{Duration, Instant};

// The newest entries kept in the view; older ones are dropped.
const MAX_LOGS: usize = 500;
const HEADLESS_WAIT: Duration = Duration::from_secs(30);
const SHOT_WIDTH: u32 = 1100;
const SHOT_HEIGHT: u32 = 640;
const SHOT_COLLECT: Duration = Duration::from_secs(4);

// The models live on the UI thread; the feed thread never touches them.
struct Models {
    providers: Rc<VecModel<ProviderRow>>,
    logs: Rc<VecModel<LogRow>>,
}

thread_local! {
    static MODELS: RefCell<Option<Models>> = const { RefCell::new(None) };
}

fn init_models(ui: &Main) {
    let models = Models {
        providers: Rc::new(VecModel::default()),
        logs: Rc::new(VecModel::default()),
    };
    ui.set_providers(ModelRc::from(models.providers.clone()));
    ui.set_logs(ModelRc::from(models.logs.clone()));
    MODELS.with(|m| *m.borrow_mut() = Some(models));
}

fn provider_row(p: &Provider) -> ProviderRow {
    ProviderRow {
        name: p.name.clone().into(),
        detail: format!("{} · {} keys", p.kind, p.keys).into(),
    }
}

fn log_row(e: &LogEvent) -> LogRow {
    LogRow {
        time: clock(e.ts_ms).into(),
        model: e.model.clone().into(),
        status: e.status.to_string().into(),
        bad: e.status >= 400 || e.status == 0,
        latency: format!("{:.0} ms", e.latency_ms).into(),
        tokens: format!("{} in / {} out", e.prompt_tokens, e.completion_tokens).into(),
    }
}

// Applies one feed message to the window. Runs on the UI thread.
fn apply(ui: &Main, msg: Msg) {
    match msg {
        Msg::Providers(Ok(ps)) => MODELS.with(|m| {
            if let Some(m) = m.borrow().as_ref() {
                m.providers.set_vec(ps.iter().map(provider_row).collect::<Vec<_>>());
            }
        }),
        Msg::Providers(Err(e)) => ui.set_status(e.into()),
        Msg::Connected => ui.set_status("live: connected to /ws".into()),
        Msg::Disconnected(e) => ui.set_status(format!("offline: {e}").into()),
        Msg::Log(ev) => MODELS.with(|m| {
            if let Some(m) = m.borrow().as_ref() {
                m.logs.insert(0, log_row(&ev));
                while m.logs.row_count() > MAX_LOGS {
                    m.logs.remove(MAX_LOGS);
                }
            }
        }),
    }
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

// A window-less platform: one software-rendered window that is drawn on demand.
struct OffscreenPlatform {
    window: Rc<slint::platform::software_renderer::MinimalSoftwareWindow>,
    start: Instant,
}

impl slint::platform::Platform for OffscreenPlatform {
    fn create_window_adapter(
        &self,
    ) -> Result<Rc<dyn slint::platform::WindowAdapter>, slint::PlatformError> {
        Ok(self.window.clone())
    }

    fn duration_since_start(&self) -> Duration {
        self.start.elapsed()
    }
}

fn screenshot(path: &str) -> Result<(), Box<dyn std::error::Error>> {
    use slint::platform::software_renderer::{MinimalSoftwareWindow, RepaintBufferType};
    let window = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    slint::platform::set_platform(Box::new(OffscreenPlatform {
        window: window.clone(),
        start: Instant::now(),
    }))?;
    let ui = Main::new()?;
    init_models(&ui);
    window.set_size(slint::PhysicalSize::new(SHOT_WIDTH, SHOT_HEIGHT));
    ui.show()?;

    let (tx, rx) = std::sync::mpsc::channel();
    let cfg = Config::from_env();
    std::thread::spawn(move || {
        run_feed(cfg, move |m| {
            let _ = tx.send(m);
        })
    });
    let deadline = Instant::now() + SHOT_COLLECT;
    while Instant::now() < deadline {
        while let Ok(m) = rx.try_recv() {
            apply(&ui, m);
        }
        slint::platform::update_timers_and_animations();
        std::thread::sleep(Duration::from_millis(50));
    }
    slint::platform::update_timers_and_animations();

    let mut pixels = vec![slint::Rgb8Pixel::default(); (SHOT_WIDTH * SHOT_HEIGHT) as usize];
    window.draw_if_needed(|renderer| {
        renderer.render(&mut pixels, SHOT_WIDTH as usize);
    });
    let bytes: Vec<u8> = pixels.iter().flat_map(|p| [p.r, p.g, p.b]).collect();
    let file = std::io::BufWriter::new(std::fs::File::create(path)?);
    let mut enc = png::Encoder::new(file, SHOT_WIDTH, SHOT_HEIGHT);
    enc.set_color(png::ColorType::Rgb);
    enc.set_depth(png::BitDepth::Eight);
    enc.write_header()?.write_image_data(&bytes)?;
    println!("wrote {path}");
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--headless") {
        std::process::exit(headless());
    }
    if let Some(i) = args.iter().position(|a| a == "--screenshot") {
        let path = args.get(i + 1).ok_or("--screenshot needs a path")?;
        return screenshot(path);
    }

    let cfg = Config::from_env();
    let ui = Main::new()?;
    init_models(&ui);
    let weak = ui.as_weak();
    std::thread::spawn(move || {
        run_feed(cfg, move |m| {
            let weak = weak.clone();
            // Hand the message to the UI thread; the closure is the only thing that crosses.
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(ui) = weak.upgrade() {
                    apply(&ui, m);
                }
            });
        })
    });
    ui.run()?;
    Ok(())
}
