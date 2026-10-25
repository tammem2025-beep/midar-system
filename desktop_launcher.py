from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import urlopen

APP_NAME = "M"
HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"


def configure_local_environment() -> tuple[Path, Path, Path]:
    if getattr(sys, "frozen", False):
        install_dir = Path(sys.executable).resolve().parent
    else:
        install_dir = Path(__file__).resolve().parent

    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    portable_marker = install_dir / "portable-mode.flag"
    portable_mode = bool(getattr(sys, "frozen", False) and portable_marker.is_file())
    support_dir = (install_dir / "M-Portable-Data") if portable_mode else (local_app_data / "M")
    data_dir = support_dir / "data"
    media_dir = data_dir / "media"
    log_dir = support_dir / "logs"
    for folder in (support_dir, data_dir, media_dir, log_dir):
        folder.mkdir(parents=True, exist_ok=True)

    env_file = support_dir / ".env"
    database_file = data_dir / "m.db"
    if not env_file.exists():
        key = secrets.token_urlsafe(48)
        db_url = f"sqlite:///{database_file.as_posix()}"
        env_file.write_text(
            "\n".join(
                [
                    "APP_ENV=development",
                    f"SECRET_KEY={key}",
                    "TOKEN_TTL_SECONDS=43200",
                    "CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000",
                    f"DATABASE_URL={db_url}",
                    f"MEDIA_DIR={media_dir.as_posix()}",
                    "LOGIN_WINDOW_MINUTES=15",
                    "LOGIN_ACCOUNT_LIMIT=10",
                    "LOGIN_IP_LIMIT=30",
                    "GOOGLE_OAUTH_CLIENT_ID=",
                    "GOOGLE_OAUTH_CLIENT_SECRET=",
                    "GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/google/callback",
                    "META_APP_ID=",
                    "META_APP_SECRET=",
                    "META_REDIRECT_URI=http://127.0.0.1:8000/api/v1/integrations/meta/callback",
                    "META_GRAPH_API_VERSION=v26.0",
                    "TELEGRAM_BOT_TOKEN=",
                    "PROVIDER_TOKEN_ENCRYPTION_KEY=",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )

    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_file, override=False)
    except Exception as exc:
        raise RuntimeError(f"Could not load local settings file: {exc}") from exc

    from cryptography.fernet import Fernet
    provider_key = os.environ.get("PROVIDER_TOKEN_ENCRYPTION_KEY", "").strip()
    if not provider_key:
        provider_key = Fernet.generate_key().decode("ascii")
        env_text = env_file.read_text(encoding="utf-8")
        import re
        key_line = re.compile(r"(?m)^PROVIDER_TOKEN_ENCRYPTION_KEY=.*$")
        if key_line.search(env_text):
            env_text = key_line.sub("PROVIDER_TOKEN_ENCRYPTION_KEY=" + provider_key, env_text, count=1)
        else:
            env_text += "\nPROVIDER_TOKEN_ENCRYPTION_KEY=" + provider_key + "\n"
        temporary_env = env_file.with_suffix(".env.tmp")
        temporary_env.write_text(env_text, encoding="utf-8", newline="\n")
        temporary_env.replace(env_file)
        os.environ["PROVIDER_TOKEN_ENCRYPTION_KEY"] = provider_key
    try:
        Fernet(provider_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise RuntimeError("The provider token encryption key in the active M support folder is invalid. It was not replaced; restore the original key or set a valid Fernet key.")

    secret = os.environ.get("SECRET_KEY", "").strip()
    if len(secret) < 32 or secret == "dev-only-change-this-secret-before-any-real-use":
        raise RuntimeError(
            "The local SECRET_KEY is missing or insecure. Open the M settings file and set a random secret of at least 32 characters."
        )

    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{database_file.as_posix()}")
    os.environ.setdefault("MEDIA_DIR", str(media_dir))
    os.environ["M_PROJECT_DIR"] = str(install_dir)
    return support_dir, data_dir, log_dir


def is_port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def is_existing_m_server() -> bool:
    try:
        with urlopen(f"{BASE_URL}/openapi.json", timeout=1.5) as response:
            document = json.loads(response.read().decode("utf-8"))
        return document.get("info", {}).get("title") == "M API"
    except Exception:
        return False


class MDesktop:
    def __init__(self) -> None:
        self.support_dir, self.data_dir, self.log_dir = configure_local_environment()
        logging.basicConfig(
            filename=str(self.log_dir / "m-desktop.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        self.server = None
        self.server_thread: threading.Thread | None = None
        self.started_by_me = False
        self.existing_server = False
        self.stopping = False
        self.poll_count = 0

        self.root = tk.Tk()
        self.root.title("M — Digital Business Management")
        self.root.geometry("520x350")
        self.root.minsize(460, 320)
        self.root.configure(bg="#0B1020")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status = tk.StringVar(value="Preparing your M workspace…")
        self.url = tk.StringVar(value=BASE_URL)
        self._build_ui()
        self.root.after(100, self.start)

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg="#0B1020", padx=28, pady=24)
        outer.pack(fill="both", expand=True)

        mark = tk.Label(
            outer, text="M", fg="#F4F7FF", bg="#0B1020",
            font=("Segoe UI", 31, "bold"),
        )
        mark.pack(anchor="w")
        tk.Label(
            outer, text="Manage. Connect. Grow.",
            fg="#9BAFD1", bg="#0B1020", font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(0, 18))

        tk.Label(
            outer, textvariable=self.status, anchor="w", justify="left",
            wraplength=455, fg="#E6EEFF", bg="#17243B",
            font=("Segoe UI", 10), padx=14, pady=13,
        ).pack(fill="x", pady=(0, 12))

        url_row = tk.Frame(outer, bg="#0B1020")
        url_row.pack(fill="x", pady=(0, 12))
        tk.Label(url_row, text="Local address", fg="#9BAFD1", bg="#0B1020").pack(side="left")
        tk.Label(url_row, textvariable=self.url, fg="#6BE1F1", bg="#0B1020").pack(side="right")

        buttons = tk.Frame(outer, bg="#0B1020")
        buttons.pack(fill="x", pady=(6, 0))
        self.open_button = tk.Button(
            buttons, text="Open M", command=self.open_m,
            state="disabled", relief="flat", cursor="hand2",
            bg="#5366FF", fg="white", activebackground="#6A79FF",
            activeforeground="white", padx=16, pady=9,
        )
        self.open_button.pack(side="left")
        tk.Button(
            buttons, text="Open data folder", command=self.open_data,
            relief="flat", cursor="hand2", bg="#17243B", fg="#E6EEFF",
            activebackground="#223452", activeforeground="white",
            padx=12, pady=9,
        ).pack(side="left", padx=8)
        tk.Button(
            buttons, text="Local settings", command=self.open_settings,
            relief="flat", cursor="hand2", bg="#17243B", fg="#E6EEFF",
            activebackground="#223452", activeforeground="white",
            padx=10, pady=9,
        ).pack(side="left", padx=8)
        tk.Button(
            buttons, text="Close", command=self.close,
            relief="flat", cursor="hand2", bg="#17243B", fg="#E6EEFF",
            activebackground="#223452", activeforeground="white",
            padx=14, pady=9,
        ).pack(side="right")

        tk.Label(
            outer, text="Your database and settings stay under your Windows user profile.",
            fg="#7184A6", bg="#0B1020", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(18, 0))

    def start(self) -> None:
        try:
            if is_port_open():
                if is_existing_m_server():
                    self.existing_server = True
                    self.status.set("M is already running on this computer. This window will reuse the active local server.")
                    self.open_button.configure(state="normal")
                    self.open_m()
                    return
                raise RuntimeError(
                    "Port 8000 is already in use by another application. Close the other program or stop the existing M server, then reopen M."
                )

            if not getattr(sys, "frozen", False):
                backend_dir = Path(__file__).resolve().parent / "backend"
                if backend_dir.is_dir():
                    sys.path.insert(0, str(backend_dir))

            self.status.set("Starting the local M server…")
            self.server_thread = threading.Thread(target=self._run_server, name="m-api", daemon=True)
            self.server_thread.start()
            self.root.after(400, self._check_ready)
        except Exception as exc:
            logging.exception("M desktop startup failed")
            self.status.set("M could not start. See the local log file for details.")
            messagebox.showerror(
                "M could not start",
                f"{exc}\n\nLog file:\n{self.log_dir / 'm-desktop.log'}",
                parent=self.root,
            )

    def _run_server(self) -> None:
        try:
            import uvicorn
            from app.main import app
            config = uvicorn.Config(
                app, host=HOST, port=PORT, log_level="info",
                access_log=False, log_config=None, workers=1,
            )
            self.server = uvicorn.Server(config)
            self.started_by_me = True
            logging.info("Starting local M server at %s", BASE_URL)
            self.server.run()
        except Exception:
            logging.exception("M API server stopped unexpectedly")
            if not self.stopping:
                logging.error("Server thread ended while the desktop window was still open.")

    def _check_ready(self) -> None:
        if self.stopping:
            return
        self.poll_count += 1
        try:
            with urlopen(f"{BASE_URL}/api/v1/health", timeout=1) as response:
                data = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and data.get("database") == "ok":
                self.status.set("M is ready. Your local workspace is running.")
                self.open_button.configure(state="normal")
                if self.poll_count == 1:
                    self.open_m()
                return
        except Exception:
            pass

        if self.server is not None and not self.server_thread.is_alive():
            self.status.set("The API server exited. Review the log file in the M data folder.")
            return
        if self.poll_count > 90:
            self.status.set("M is taking too long to start. Review the local log file.")
            return
        self.root.after(500, self._check_ready)

    def open_m(self) -> None:
        try:
            import webbrowser
            webbrowser.open(BASE_URL, new=2)
        except Exception as exc:
            messagebox.showerror("Open M", str(exc), parent=self.root)

    def open_data(self) -> None:
        try:
            os.startfile(str(self.data_dir))  # Windows only
        except Exception as exc:
            messagebox.showerror("Open data folder", str(exc), parent=self.root)

    def open_settings(self) -> None:
        try:
            os.startfile(str(self.support_dir / ".env"))  # Opens the local configuration in the default editor.
        except Exception as exc:
            messagebox.showerror("Open local settings", str(exc), parent=self.root)

    def close(self) -> None:
        if self.stopping:
            return
        self.stopping = True
        if self.server is not None and self.started_by_me:
            self.status.set("Stopping the local M server…")
            self.server.should_exit = True
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=4)
        self.root.destroy()


def main() -> int:
    try:
        app = MDesktop()
        app.root.mainloop()
        return 0
    except Exception as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("M startup error", str(exc), parent=root)
            root.destroy()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
