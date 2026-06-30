import logging
import math
import tkinter as tk
from tkinter import ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from ble_controller import BLEController, DiscoveredDevice

logger = logging.getLogger(__name__)


class ArmyBombGUI:
    def __init__(self):
        self.controller = BLEController()
        self.controller.set_callbacks(
            on_device_found=self._on_device_found,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
            on_error=self._on_error,
        )

        self.root = tb.Window(themename="darkly")
        self.root.title("Army Bomb Controller")
        self.root.geometry("520x740")
        self.root.minsize(480, 650)

        self._discovered: dict[str, DiscoveredDevice] = {}
        self._current_r = 255
        self._current_g = 128
        self._current_b = 0
        self._hue = 30
        self._saturation = 1.0
        self._value = 1.0

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=BOTH, expand=True)

        self._build_scan_section(main)
        self._build_device_list(main)
        self._build_status(main)
        self._build_color_section(main)
        self._build_log_section(main)

    def _build_scan_section(self, parent):
        frame = ttk.Labelframe(parent, text="Device", padding=8)
        frame.pack(fill=X, pady=(0, 8))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=X)

        self._scan_btn = ttk.Button(
            btn_row, text="Scan", command=self._toggle_scan, style="primary.TButton"
        )
        self._scan_btn.pack(side=LEFT, padx=(0, 6))

        self._stop_scan_btn = ttk.Button(
            btn_row, text="Stop", command=self._stop_scan, state=DISABLED
        )
        self._stop_scan_btn.pack(side=LEFT, padx=(0, 6))

        self._disconnect_btn = ttk.Button(
            btn_row, text="Disconnect", command=self._disconnect, state=DISABLED, style="danger.TButton"
        )
        self._disconnect_btn.pack(side=LEFT)

    def _build_device_list(self, parent):
        frame = ttk.Labelframe(parent, text="Discovered Devices", padding=4)
        frame.pack(fill=X, pady=(0, 8))

        columns = ("name", "type", "rssi")
        self._tree = ttk.Treeview(frame, columns=columns, show="headings", height=5)
        self._tree.heading("name", text="Name")
        self._tree.heading("type", text="Type")
        self._tree.heading("rssi", text="RSSI")
        self._tree.column("name", width=260)
        self._tree.column("type", width=80, anchor=CENTER)
        self._tree.column("rssi", width=70, anchor=CENTER)
        self._tree.pack(fill=X)

        self._tree.bind("<Double-1>", self._on_double_click)
        self._connect_btn = ttk.Button(
            frame, text="Connect Selected", command=self._connect_selected, style="success.TButton"
        )
        self._connect_btn.pack(pady=(4, 0))

    def _build_status(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill=X, pady=(0, 8))

        self._status_label = ttk.Label(frame, text="Status: Idle", font=("", 10, "bold"))
        self._status_label.pack(side=LEFT)

        self._color_preview = tk.Canvas(frame, width=28, height=28, highlightthickness=0)
        self._color_preview.pack(side=RIGHT)
        self._update_preview()

    def _build_color_section(self, parent):
        frame = ttk.Labelframe(parent, text="Color Control", padding=8)
        frame.pack(fill=BOTH, expand=True)

        wheel_frame = ttk.Frame(frame)
        wheel_frame.pack(pady=(0, 8))

        wheel_size = 220
        self._wheel = tk.Canvas(wheel_frame, width=wheel_size, height=wheel_size, highlightthickness=0)
        self._wheel.pack(side=LEFT, padx=(0, 12))

        self._slider_frame = ttk.Frame(wheel_frame)
        self._slider_frame.pack(side=LEFT, fill=Y)

        self._r_var = tk.IntVar(value=255)
        self._g_var = tk.IntVar(value=128)
        self._b_var = tk.IntVar(value=0)

        for label, var, color in [
            ("R", self._r_var, "#e74c3c"),
            ("G", self._g_var, "#2ecc71"),
            ("B", self._b_var, "#3498db"),
        ]:
            row = ttk.Frame(self._slider_frame)
            row.pack(fill=X, pady=2)
            ttk.Label(row, text=label, width=2, foreground=color, font=("", 10, "bold")).pack(side=LEFT)
            scale = ttk.Scale(
                row, from_=0, to=255, variable=var,
                command=lambda v, vn=var: self._on_slider(vn)
            )
            scale.pack(side=LEFT, fill=X, expand=True, padx=6)
            spin = ttk.Spinbox(
                row, from_=0, to=255, width=4, textvariable=var,
                command=lambda vn=var: self._on_slider(vn)
            )
            spin.pack(side=LEFT)

        self._hex_label = ttk.Label(frame, text="#FF8000", font=("", 16, "bold"))
        self._hex_label.pack(pady=(4, 0))

        self._draw_wheel()
        self._wheel.bind("<B1-Motion>", self._on_wheel_drag)
        self._wheel.bind("<Button-1>", self._on_wheel_drag)

        preset_frame = ttk.Frame(frame)
        preset_frame.pack(fill=X, pady=(6, 0))
        ttk.Label(preset_frame, text="Presets:").pack(side=LEFT, padx=(0, 4))
        presets = [
            ("Red", 255, 0, 0),
            ("Pink", 255, 105, 180),
            ("Blue", 0, 100, 255),
            ("Green", 0, 255, 50),
            ("Yellow", 255, 220, 0),
            ("White", 255, 255, 255),
            ("Off", 0, 0, 0),
        ]
        for name, r, g, b in presets:
            btn = ttk.Button(
                preset_frame, text=name,
                command=lambda r=r, g=g, b=b: self._set_color(r, g, b),
                style="secondary.Outline.TButton",
                width=6,
            )
            btn.pack(side=LEFT, padx=1)

    def _draw_wheel(self):
        self._wheel.delete("all")
        w = 220
        self._wheel_cx = self._wheel_cy = w // 2
        self._wheel_radius = 90
        steps = 360
        for i in range(steps):
            angle = math.radians(i)
            r, g, b = self._hsv_to_rgb(i / steps, 1.0, 1.0)
            color = f"#{r:02x}{g:02x}{b:02x}"
            x1 = self._wheel_cx + int(self._wheel_radius * math.cos(angle))
            y1 = self._wheel_cy - int(self._wheel_radius * math.sin(angle))
            self._wheel.create_line(self._wheel_cx, self._wheel_cy, x1, y1, fill=color, width=3)
        self._draw_wheel_indicator()

    def _draw_wheel_indicator(self):
        self._wheel.delete("indicator")
        angle = math.radians(self._hue)
        dist = self._wheel_radius * self._saturation
        ix = self._wheel_cx + int(dist * math.cos(angle))
        iy = self._wheel_cy - int(dist * math.sin(angle))
        self._wheel.create_oval(ix - 6, iy - 6, ix + 6, iy + 6, fill="white", outline="black", width=2, tags="indicator")

    def _pick_wheel(self, x, y):
        w = 220
        cx = cy = w // 2
        dx = x - cx
        dy = cy - y
        dist = math.sqrt(dx * dx + dy * dy)
        radius = 90
        self._saturation = max(0.0, min(1.0, dist / radius))
        angle = math.degrees(math.atan2(dy, dx))
        self._hue = (angle + 360) % 360
        r, g, b = self._hsv_to_rgb(self._hue / 360, self._saturation, self._value)
        self._set_color(r, g, b)

    def _on_wheel_drag(self, event):
        self._pick_wheel(event.x, event.y)

    def _on_slider(self, var):
        val = var.get()
        self._current_r = self._r_var.get()
        self._current_g = self._g_var.get()
        self._current_b = self._b_var.get()
        self._hue, self._saturation, self._value = self._rgb_to_hsv(
            self._current_r / 255, self._current_g / 255, self._current_b / 255
        )
        self._hue = int(self._hue * 360)
        self._draw_wheel_indicator()
        self._update_preview()
        self._hex_label.config(text=f"#{self._current_r:02X}{self._current_g:02X}{self._current_b:02X}")
        self._send_to_device()

    def _set_color(self, r, g, b):
        self._current_r = r
        self._current_g = g
        self._current_b = b
        self._r_var.set(r)
        self._g_var.set(g)
        self._b_var.set(b)
        self._hue, self._saturation, self._value = self._rgb_to_hsv(r / 255, g / 255, b / 255)
        self._hue = int(self._hue * 360)
        self._update_preview()
        self._hex_label.config(text=f"#{r:02X}{g:02X}{b:02X}")
        self._draw_wheel_indicator()
        self._send_to_device()

    def _update_preview(self):
        color = f"#{self._current_r:02x}{self._current_g:02x}{self._current_b:02x}"
        self._color_preview.config(bg=color)

    def _send_to_device(self):
        if self.controller.connected:
            import asyncio
            asyncio.get_running_loop().create_task(
                self.controller.send_color(self._current_r, self._current_g, self._current_b)
            )

    def _toggle_scan(self):
        if not self.controller.scanning:
            self._scan_btn.config(state=DISABLED, text="Scanning...")
            self._stop_scan_btn.config(state=NORMAL)
            self._status_label.config(text="Status: Scanning...")
            self._discovered.clear()
            for item in self._tree.get_children():
                self._tree.delete(item)
            import asyncio
            asyncio.create_task(self.controller.start_scan())
        else:
            self._stop_scan()

    def _stop_scan(self):
        self.controller.stop_scan()
        self._scan_btn.config(state=NORMAL, text="Scan")
        self._stop_scan_btn.config(state=DISABLED)
        if not self.controller.connected:
            self._status_label.config(text="Status: Idle")

    def _on_device_found(self, device: DiscoveredDevice):
        self._discovered[device.address] = device
        self.root.after(0, self._refresh_tree)

    def _refresh_tree(self):
        current_ids = set(self._tree.get_children())
        for item_id in current_ids:
            self._tree.delete(item_id)

        for addr, dev in sorted(self._discovered.items(), key=lambda x: x[1].rssi, reverse=True):
            rssi_str = f"{dev.rssi} dBm"
            self._tree.insert(
                "", END, iid=addr,
                values=(dev.name, dev.device_type.value if dev.device_type else "?", rssi_str)
            )

    def _on_double_click(self, event):
        self._connect_selected()

    def _connect_selected(self):
        selection = self._tree.selection()
        if not selection:
            return
        addr = selection[0]
        dev = self._discovered.get(addr)
        if not dev:
            return
        import asyncio
        asyncio.create_task(self._do_connect(dev))

    def _on_connected(self, device_type):
        self.root.after(0, lambda: self._handle_connected(device_type))

    def _handle_connected(self, device_type):
        self._append_log(f"[INFO] Connected — device type: {device_type.value}", "info")
        self._status_label.config(text=f"Status: Connected — {device_type.value}")
        self._scan_btn.config(state=DISABLED)
        self._stop_scan_btn.config(state=DISABLED)
        self._disconnect_btn.config(state=NORMAL)
        self._connect_btn.config(state=DISABLED)
        self._send_to_device()

    def _on_disconnected(self):
        self.root.after(0, self._handle_disconnected)

    def _handle_disconnected(self):
        self._append_log("[INFO] Disconnected", "info")
        self._status_label.config(text="Status: Disconnected")
        self._scan_btn.config(state=NORMAL)
        self._stop_scan_btn.config(state=DISABLED)
        self._disconnect_btn.config(state=DISABLED)
        self._connect_btn.config(state=NORMAL)

    def _disconnect(self):
        import asyncio
        asyncio.create_task(self.controller.disconnect())

    def _build_log_section(self, parent):
        frame = ttk.Labelframe(parent, text="Log", padding=4)
        frame.pack(fill=BOTH, expand=True, pady=(8, 0))

        self._log_text = tk.Text(
            frame, height=6, wrap=tk.WORD, state=DISABLED,
            bg="#1a1a1a", fg="#aaaaaa", font=("Consolas", 9),
            borderwidth=0, highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(frame, orient=VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scrollbar.set)
        self._log_text.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self._log_text.tag_config("error", foreground="#e74c3c")
        self._log_text.tag_config("warn", foreground="#f39c12")
        self._log_text.tag_config("info", foreground="#3498db")

    def _append_log(self, message: str, level: str = "info"):
        def _do():
            self._log_text.configure(state=NORMAL)
            self._log_text.insert(END, message + "\n", level)
            self._log_text.see(END)
            self._log_text.configure(state=DISABLED)
        self.root.after(0, _do)

    def _on_error(self, message: str):
        self._append_log(f"[ERROR] {message}", "error")
        self.root.after(0, lambda: self._status_label.config(text=f"Status: {message}"))

    async def _do_connect(self, dev: DiscoveredDevice):
        self._status_label.config(text=f"Status: Connecting to {dev.name}...")
        self._connect_btn.config(state=DISABLED)
        self._scan_btn.config(state=DISABLED)
        try:
            await self.controller.connect(dev.address, dev.name)
        except Exception as e:
            logger.exception("Failed to connect to %s", dev.name)
            self._append_log(f"[ERROR] Failed to connect to {dev.name}: {e}", "error")
            self._status_label.config(text=f"Status: Error — {e}")
            self._scan_btn.config(state=NORMAL)
            self._connect_btn.config(state=NORMAL)

    @staticmethod
    def _hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
        h = h % 1.0
        i = int(h * 6)
        f = h * 6 - i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        i = i % 6
        if i == 0:
            r, g, b = v, t, p
        elif i == 1:
            r, g, b = q, v, p
        elif i == 2:
            r, g, b = p, v, t
        elif i == 3:
            r, g, b = p, q, v
        elif i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

    @staticmethod
    def _rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
        mx = max(r, g, b)
        mn = min(r, g, b)
        d = mx - mn
        if d == 0:
            h = 0.0
        elif mx == r:
            h = ((g - b) / d) % 6
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h = (h / 6) % 1.0
        s = 0.0 if mx == 0 else d / mx
        v = mx
        return h, s, v

    def run(self):
        self.root.mainloop()
