//! Native window for Colony Local.
//!
//! Starts the Python `colony` server on a free local port, shows a loading page while it boots,
//! then points the window at it. The server is stopped when the window closes.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const START_TIMEOUT: Duration = Duration::from_secs(30);

struct Server(Mutex<Option<Child>>);

/// `COLONY_BIN` wins; otherwise the project's own virtualenv (when run from a checkout); otherwise PATH.
fn colony_command() -> PathBuf {
    if let Ok(path) = std::env::var("COLONY_BIN") {
        return path.into();
    }
    let venv = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.venv/bin/colony");
    if venv.exists() {
        venv
    } else {
        "colony".into()
    }
}

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

fn is_listening(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok()
}

/// Replace the text on the loading page (and mark it as failed).
fn show_error(window: &WebviewWindow, text: &str) {
    let text = serde_json::to_string(text).unwrap_or_else(|_| "\"Colony could not start.\"".into());
    let _ = window.eval(format!(
        "(function f(){{var e=document.getElementById('msg');\
         if(e){{e.textContent={text};document.body.classList.add('failed')}}else{{setTimeout(f,100)}}}})()"
    ));
}

fn start_server(app: &tauri::AppHandle, window: &WebviewWindow) {
    let port = match free_port() {
        Ok(port) => port,
        Err(err) => return show_error(window, &format!("Could not find a free port: {err}")),
    };
    let command = colony_command();
    let child = match Command::new(&command)
        // Piped stdin stays open while this app lives; the server stops itself when it closes.
        .args(["--no-open", "--exit-with-parent", "--port", &port.to_string()])
        .stdin(Stdio::piped())
        // Start in the home folder: Colony refuses that as a workspace, so agents with tools can't
        // silently work inside this project's src-tauri folder; the user picks a project folder in Workspace settings.
        .current_dir(std::env::var("HOME").unwrap_or_else(|_| "/".into()))
        .spawn() {
        Ok(child) => child,
        Err(err) => {
            return show_error(
                window,
                &format!(
                    "Could not start the Colony server ({}): {err}\n\
                     Install it with `pip install -e local` or set COLONY_BIN to the colony command.",
                    command.display()
                ),
            )
        }
    };
    app.state::<Server>().0.lock().unwrap().replace(child);

    let started = Instant::now();
    while started.elapsed() < START_TIMEOUT {
        if is_listening(port) {
            let url = format!("http://127.0.0.1:{port}");
            if let Err(err) = window.navigate(url.parse().expect("valid local url")) {
                show_error(window, &format!("Could not open {url}: {err}"));
            }
            return;
        }
        // The server may already have crashed (bad config, missing package).
        let exited = app.state::<Server>().0.lock().unwrap().as_mut().and_then(|c| c.try_wait().ok().flatten());
        if let Some(status) = exited {
            return show_error(window, &format!("The Colony server stopped right away ({status}). See the terminal for details."));
        }
        thread::sleep(Duration::from_millis(150));
    }
    show_error(window, "The Colony server did not start within 30 seconds.");
}

fn main() {
    tauri::Builder::default()
        .manage(Server(Mutex::new(None)))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Colony")
                .inner_size(1280.0, 820.0)
                .min_inner_size(900.0, 600.0)
                .disable_drag_drop_handler() // let the page receive dropped files (chat attachments)
                .build()?;
            let handle = app.handle().clone();
            thread::spawn(move || start_server(&handle, &window));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Colony window")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Server>().0.lock().unwrap().take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
