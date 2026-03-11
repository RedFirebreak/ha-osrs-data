"""
Manual test GUI for the OSRS Data pairing + events flow.

Usage:
    python manual_tests/test_pairing_gui.py

Requirements (stdlib only):
    - Python 3.10+
    - tkinter (bundled with Python on Windows/macOS)
    - urllib (stdlib)

No pip dependencies needed.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

MOCK_DATA_PATH = os.path.join(os.path.dirname(__file__), "mock-data.json")


class PairingTestApp:
    def __init__(self, root: tk.Tk) -> None:
        root.title("OSRS Data — Pairing Test Tool")
        root.resizable(False, False)

        self._token: str | None = None
        self._device_id: str | None = None

        # ── HA URL ───────────────────────────────────────────────
        frame_url = ttk.LabelFrame(root, text="Home Assistant", padding=8)
        frame_url.pack(fill="x", padx=10, pady=(10, 4))

        ttk.Label(frame_url, text="Base URL:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value="http://homeassistant.local:8123")
        ttk.Entry(frame_url, textvariable=self.url_var, width=48).grid(
            row=0, column=1, padx=(4, 0)
        )

        # ── Pairing ─────────────────────────────────────────────
        frame_pair = ttk.LabelFrame(root, text="1 — Pair", padding=8)
        frame_pair.pack(fill="x", padx=10, pady=4)

        ttk.Label(frame_pair, text="Pairing Code:").grid(row=0, column=0, sticky="w")
        self.code_var = tk.StringVar()
        ttk.Entry(frame_pair, textvariable=self.code_var, width=12).grid(
            row=0, column=1, padx=(4, 0), sticky="w"
        )
        ttk.Button(frame_pair, text="Pair", command=self._pair).grid(
            row=0, column=2, padx=(8, 0)
        )

        # Status labels
        self.pair_status = tk.StringVar(value="Not paired")
        ttk.Label(frame_pair, textvariable=self.pair_status, foreground="gray").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )

        self.token_display = tk.StringVar(value="")
        ttk.Label(frame_pair, textvariable=self.token_display, foreground="green").grid(
            row=2, column=0, columnspan=3, sticky="w"
        )

        # ── Send Event ──────────────────────────────────────────
        frame_event = ttk.LabelFrame(root, text="2 — Send Event", padding=8)
        frame_event.pack(fill="x", padx=10, pady=4)

        btn_frame = ttk.Frame(frame_event)
        btn_frame.pack(fill="x")

        ttk.Button(btn_frame, text="Send mock-data.json", command=self._send_event).pack(
            side="left"
        )
        ttk.Button(btn_frame, text="Send custom JSON ↓", command=self._send_custom).pack(
            side="left", padx=(8, 0)
        )

        self.event_status = tk.StringVar(value="")
        ttk.Label(frame_event, textvariable=self.event_status).pack(
            anchor="w", pady=(4, 0)
        )

        # ── Custom JSON editor ──────────────────────────────────
        frame_json = ttk.LabelFrame(root, text="Custom JSON (optional)", padding=8)
        frame_json.pack(fill="both", expand=True, padx=10, pady=(4, 4))

        self.json_editor = scrolledtext.ScrolledText(frame_json, height=12, width=60, font=("Consolas", 10))
        self.json_editor.pack(fill="both", expand=True)
        # Pre-fill with mock data
        try:
            with open(MOCK_DATA_PATH, "r") as f:
                self.json_editor.insert("1.0", f.read())
        except FileNotFoundError:
            self.json_editor.insert("1.0", '{"type": "LEVEL", "playerName": "Test"}')

        # ── Response log ────────────────────────────────────────
        frame_log = ttk.LabelFrame(root, text="Response Log", padding=8)
        frame_log.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self.log = scrolledtext.ScrolledText(frame_log, height=8, width=60, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)

    # ── helpers ──────────────────────────────────────────────────

    def _base_url(self) -> str:
        return self.url_var.get().rstrip("/")

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _http(self, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
        """Fire an HTTP request and return parsed JSON response."""
        url = f"{self._base_url()}{path}"
        data = json.dumps(body).encode() if body else None
        hdrs = {
            "Content-Type": "application/json",
            "User-Agent": "OSRS-Data-PairingTest/1.0",
        }
        if headers:
            hdrs.update(headers)

        self._log(f"→ {method} {url}")
        if body:
            self._log(f"  body: {json.dumps(body, indent=2)[:200]}")

        req = Request(url, data=data, headers=hdrs, method=method)
        try:
            with urlopen(req, timeout=10) as resp:
                raw = resp.read().decode()
                self._log(f"← {resp.status}: {raw[:300]}")
                return json.loads(raw)
        except HTTPError as e:
            raw = e.read().decode()
            self._log(f"← {e.code}: {raw[:300]}")
            raise
        except URLError as e:
            self._log(f"← Connection error: {e.reason}")
            raise

    # ── actions ──────────────────────────────────────────────────

    def _pair(self) -> None:
        code = self.code_var.get().strip()
        if not code:
            messagebox.showwarning("Missing code", "Enter the 6-digit pairing code first.")
            return

        try:
            resp = self._http("POST", "/api/osrs-data/pair", {"code": code})
        except Exception as e:
            self.pair_status.set(f"Error: {e}")
            return

        if resp.get("ok"):
            self._token = resp["token"]
            self._device_id = resp["device_id"]
            self.pair_status.set(f"Paired!  device_id={self._device_id}")
            self.token_display.set(f"Token: {self._token[:16]}…{self._token[-8:]}")
            self._log(f"✓ Paired — token saved ({len(self._token)} chars)")
        else:
            self.pair_status.set(f"Failed: {resp.get('error', 'unknown')}")

    def _send_event(self) -> None:
        """Send mock-data.json."""
        try:
            with open(MOCK_DATA_PATH, "r") as f:
                payload = json.load(f)
        except FileNotFoundError:
            messagebox.showerror("File missing", f"Cannot find {MOCK_DATA_PATH}")
            return
        self._do_send(payload)

    def _send_custom(self) -> None:
        """Send whatever is in the custom JSON editor."""
        raw = self.json_editor.get("1.0", "end").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            messagebox.showerror("Invalid JSON", str(e))
            return
        self._do_send(payload)

    def _do_send(self, payload: dict) -> None:
        if not self._token:
            messagebox.showwarning("Not paired", "Pair with a code first.")
            return

        try:
            resp = self._http(
                "POST",
                "/api/osrs-data/events",
                payload,
                headers={"X-Osrs-Token": self._token},
            )
        except Exception as e:
            self.event_status.set(f"Error: {e}")
            return

        if resp.get("ok"):
            dup = " (duplicate)" if resp.get("duplicate") else ""
            self.event_status.set(f"✓ Event accepted{dup}")
        else:
            self.event_status.set(f"✗ {resp.get('error', 'unknown')}")


def main() -> None:
    root = tk.Tk()
    PairingTestApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
