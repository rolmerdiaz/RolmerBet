from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from .config import ASSETS_DIR, DB_PATH, DIAGNOSTICS_DIR, load_config, save_config
from .demo import DemoProvider, demo_matches
from .domain import Combo, Evaluation, Match
from .engine import analyze_matches, build_combo
from .odds import fmt_decimal, fmt_percent
from .providers.football_data import FootballDataProvider
from .scheduler import install_daily
from .scrapers.triunfobet import TriunfoBetCollector
from .storage import Database
from .providers.football_data import normalize
from .updater import UpdateError, UpdateInfo, check_for_update, download_update, launch_installer


COLORS = {
    "bg": "#07182B", "panel": "#102B45", "panel2": "#153955",
    "nav": "#06111F", "cyan": "#20C7F2", "orange": "#FF9D2E",
    "white": "#F2F7FC", "muted": "#9CB2C8", "border": "#28516E",
    "good": "#35D07F", "bad": "#FF6B65", "warn": "#F5C451",
}


class RolmerBetApp:
    def __init__(self, root: tk.Tk, auto: bool = False):
        self.root = root
        self.root.title("RolmerBet — Análisis conservador")
        self.root.geometry("1240x790")
        self.root.minsize(1050, 680)
        self.root.configure(bg=COLORS["bg"])
        self.config = load_config()
        self.demo_var = tk.BooleanVar(value=bool(self.config.get("demo_mode", True)))
        self.headless_var = tk.BooleanVar(value=bool(self.config.get("headless", True)))
        self.analysis_date_var = tk.StringVar(value=date.today().isoformat())
        self.db = Database(DB_PATH)
        self.matches: list[Match] = []
        self.evaluations: list[Evaluation] = []
        self.combo = Combo([], 1.0, 1.0, 0.0, "VACÍA", "Todavía no hay análisis.")
        self.queue: queue.Queue = queue.Queue()
        self.busy = False
        self.available_update: UpdateInfo | None = None
        self.images: dict[str, ImageTk.PhotoImage] = {}
        self._setup_styles()
        self._build()
        self.root.after(150, self._poll)
        self._load_latest()
        if self.config.get("check_updates", True):
            self.root.after(1800, self.check_updates)
        if auto:
            self.root.after(1200, self.start_analysis)

    def _setup_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=COLORS["bg"], foreground=COLORS["white"],
                        fieldbackground=COLORS["panel"], font=("Segoe UI", 10))
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["panel"], foreground=COLORS["muted"],
                        padding=(14, 8), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", COLORS["cyan"])],
                  foreground=[("selected", COLORS["nav"])])
        style.configure("Treeview", background=COLORS["panel"], foreground=COLORS["white"],
                        fieldbackground=COLORS["panel"], rowheight=29, borderwidth=0)
        style.configure("Treeview.Heading", background=COLORS["panel2"], foreground=COLORS["white"],
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#17658A")])
        style.configure("TEntry", fieldbackground="#0B2238", foreground=COLORS["white"],
                        insertcolor=COLORS["white"])
        style.configure("TCombobox", fieldbackground="#0B2238", foreground=COLORS["white"])
        style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["white"])
        style.configure("Horizontal.TProgressbar", troughcolor=COLORS["panel"],
                        background=COLORS["orange"])

    def _button(self, parent, text: str, command, kind: str = "cyan", **kwargs) -> tk.Button:
        color = COLORS[kind]
        fg = COLORS["nav"] if kind in {"cyan", "orange", "good", "warn"} else COLORS["white"]
        kwargs.setdefault("padx", 14)
        kwargs.setdefault("pady", 7)
        return tk.Button(parent, text=text, command=command, bg=color, fg=fg,
                         activebackground=color, activeforeground=fg, relief="flat",
                         cursor="hand2", font=("Segoe UI", 10, "bold"), **kwargs)

    def _build(self) -> None:
        top = tk.Frame(self.root, bg=COLORS["nav"], height=68)
        top.pack(fill="x")
        tk.Label(top, text="ROLMER", bg=COLORS["nav"], fg=COLORS["white"],
                 font=("Segoe UI", 20, "bold")).pack(side="left", padx=(18, 0), pady=14)
        tk.Label(top, text="BET", bg=COLORS["nav"], fg=COLORS["orange"],
                 font=("Segoe UI", 20, "bold")).pack(side="left", pady=14)
        self.mode_badge = tk.Label(top, text=" DEMO ", bg=COLORS["warn"], fg=COLORS["nav"],
                                   font=("Segoe UI", 9, "bold"))
        self.mode_badge.pack(side="left", padx=16)
        self.status = tk.StringVar(value="Listo.")
        tk.Label(top, textvariable=self.status, bg=COLORS["nav"], fg=COLORS["muted"],
                 font=("Segoe UI", 10)).pack(side="left", padx=10)
        self.progress = ttk.Progressbar(top, mode="indeterminate", length=120)
        self.progress.pack(side="right", padx=16)
        self._button(top, "ANALIZAR FECHA", self.start_analysis, "orange").pack(side="right", pady=11)
        self.update_button = self._button(top, "ACTUALIZAR", self.install_update, "cyan", padx=10)
        self.update_button.pack(side="right", padx=8, pady=11)

        filters = tk.Frame(self.root, bg=COLORS["panel"], height=48)
        filters.pack(fill="x")
        tk.Label(filters, text="Fecha del análisis:", bg=COLORS["panel"], fg=COLORS["white"],
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(18, 7), pady=8)
        ttk.Entry(filters, textvariable=self.analysis_date_var, width=12).pack(side="left", padx=4, pady=8)
        self._button(filters, "HOY", lambda: self._set_analysis_date(0), "cyan", pady=3).pack(side="left", padx=4)
        self._button(filters, "MAÑANA", lambda: self._set_analysis_date(1), "orange", pady=3).pack(side="left", padx=4)
        ttk.Checkbutton(filters, text="Usar datos de demostración", variable=self.demo_var,
                        command=self._sync_mode_badge).pack(side="right", padx=18)
        tk.Label(filters, text="Formato: AAAA-MM-DD", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=8)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        self.home_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.matches_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.analysis_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.combo_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.history_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        self.settings_tab = tk.Frame(self.notebook, bg=COLORS["bg"])
        for tab, title in ((self.home_tab, "⌂ Inicio"), (self.matches_tab, "⚽ Partidos"),
                           (self.analysis_tab, "★ Análisis"), (self.combo_tab, "◎ Combinada"),
                           (self.history_tab, "✔ Historial"), (self.settings_tab, "⚙ Configuración")):
            self.notebook.add(tab, text=title)
        self._home_page()
        self._matches_page()
        self._analysis_page()
        self._combo_page()
        self._history_page()
        self._settings_page()

    def _banner(self, parent, filename: str, title: str, subtitle: str) -> None:
        wrap = tk.Frame(parent, bg=COLORS["panel"], height=145)
        wrap.pack(fill="x", padx=8, pady=(8, 10))
        wrap.pack_propagate(False)
        path = ASSETS_DIR / filename
        if path.exists():
            image = Image.open(path).convert("RGB")
            image = ImageOps.fit(image, (1060, 145), method=Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.images[filename] = photo
            label = tk.Label(wrap, image=photo, bg=COLORS["panel"])
            label.place(relx=0, rely=0, relwidth=1, relheight=1)
        shade = tk.Frame(wrap, bg="#07182B")
        shade.place(x=0, y=0, width=430, height=145)
        tk.Label(shade, text=title, bg="#07182B", fg=COLORS["cyan"],
                 font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=20, pady=(24, 4))
        tk.Label(shade, text=subtitle, bg="#07182B", fg=COLORS["white"],
                 font=("Segoe UI", 10), wraplength=370, justify="left").pack(anchor="w", padx=20)

    def _home_page(self) -> None:
        self._banner(self.home_tab, "portada.png", "ANÁLISIS CONSERVADOR",
                     "Cuotas verificadas en Triunfobet, filtros estadísticos y una sola combinada.")
        body = tk.Frame(self.home_tab, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=10)
        cards = [
            ("1", "Leer Triunfobet", "El navegador trabaja en modo oculto y conserva el nombre exacto de los mercados."),
            ("2", "Evaluar", "Compara probabilidades, forma reciente, goles y córners cuando existen datos suficientes."),
            ("3", "Decidir", "Si alcanzar cuota 3–4 exige bajar los filtros, la aplicación indica NO APOSTAR."),
        ]
        for number, title, text in cards:
            card = tk.Frame(body, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=7, pady=8)
            tk.Label(card, text=number, bg=COLORS["orange"], fg=COLORS["nav"],
                     font=("Segoe UI", 18, "bold"), width=3).pack(anchor="w", padx=15, pady=(18, 9))
            tk.Label(card, text=title, bg=COLORS["panel"], fg=COLORS["cyan"],
                     font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=15)
            tk.Label(card, text=text, bg=COLORS["panel"], fg=COLORS["muted"],
                     font=("Segoe UI", 10), wraplength=270, justify="left").pack(anchor="w", padx=15, pady=10)
        action = tk.Frame(self.home_tab, bg=COLORS["bg"])
        action.pack(pady=12)
        self._button(action, "INICIAR ANÁLISIS", self.start_analysis, "cyan").pack(side="left", padx=6)
        self._button(action, "VER ÚLTIMA COMBINADA", lambda: self.notebook.select(self.combo_tab), "orange").pack(side="left", padx=6)
        tk.Label(self.home_tab, text="La aplicación analiza; no realiza apuestas ni pulsa confirmar boletos.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(pady=(0, 10))

    def _matches_page(self) -> None:
        self._banner(self.matches_tab, "partidos.png", "PARTIDOS LEÍDOS",
                     "Eventos y cuotas que la aplicación encontró directamente en Triunfobet.")
        cols = ("fecha", "torneo", "partido", "mercados")
        self.matches_tree = ttk.Treeview(self.matches_tab, columns=cols, show="headings")
        widths = (135, 210, 500, 90)
        for col, width in zip(cols, widths):
            self.matches_tree.heading(col, text=col.capitalize())
            self.matches_tree.column(col, width=width, anchor="w")
        self.matches_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _analysis_page(self) -> None:
        self._banner(self.analysis_tab, "analisis.png", "COMPARACIÓN DE MERCADOS",
                     "Probabilidad implícita, estimación prudente, calidad de datos y decisión.")
        pane = tk.PanedWindow(self.analysis_tab, orient="horizontal", bg=COLORS["bg"], sashwidth=6)
        pane.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        left = tk.Frame(pane, bg=COLORS["panel"])
        right = tk.Frame(pane, bg=COLORS["panel"])
        pane.add(left, minsize=650)
        pane.add(right, minsize=340)
        cols = ("partido", "mercado", "cuota", "implícita", "ajustada", "calidad", "decisión")
        self.analysis_tree = ttk.Treeview(left, columns=cols, show="headings")
        widths = (215, 170, 62, 68, 68, 60, 80)
        for col, width in zip(cols, widths):
            self.analysis_tree.heading(col, text=col.capitalize())
            self.analysis_tree.column(col, width=width, anchor="w")
        self.analysis_tree.pack(fill="both", expand=True)
        self.analysis_tree.tag_configure("yes", foreground=COLORS["good"])
        self.analysis_tree.tag_configure("no", foreground=COLORS["muted"])
        self.analysis_tree.bind("<<TreeviewSelect>>", self._show_evaluation)
        tk.Label(right, text="Detalle", bg=COLORS["panel"], fg=COLORS["orange"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=14, pady=(12, 5))
        self.analysis_detail = tk.Text(right, wrap="word", bg=COLORS["panel"], fg=COLORS["white"],
                                       insertbackground=COLORS["white"], relief="flat",
                                       font=("Segoe UI", 10), padx=12, pady=8)
        self.analysis_detail.pack(fill="both", expand=True)

    def _combo_page(self) -> None:
        self._banner(self.combo_tab, "combinadas.png", "COMBINADA DE LA FECHA ELEGIDA",
                     "Una recomendación o una indicación clara de no apostar.")
        summary = tk.Frame(self.combo_tab, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        summary.pack(fill="x", padx=12, pady=(0, 10))
        self.combo_status = tk.StringVar(value="SIN ANALIZAR")
        self.combo_odds = tk.StringVar(value="1.00")
        self.combo_prob = tk.StringVar(value="0.0%")
        for caption, variable, color in (("Estado", self.combo_status, COLORS["orange"]),
                                         ("Cuota total", self.combo_odds, COLORS["cyan"]),
                                         ("Probabilidad prudente", self.combo_prob, COLORS["good"])):
            box = tk.Frame(summary, bg=COLORS["panel"])
            box.pack(side="left", padx=24, pady=12)
            tk.Label(box, text=caption, bg=COLORS["panel"], fg=COLORS["muted"],
                     font=("Segoe UI", 9)).pack(anchor="w")
            tk.Label(box, textvariable=variable, bg=COLORS["panel"], fg=color,
                     font=("Segoe UI", 17, "bold")).pack(anchor="w")
        self._button(summary, "COPIAR", self.copy_combo, "cyan").pack(side="right", padx=16)
        cols = ("torneo", "hora", "partido", "mercado", "original", "decimal", "probabilidad")
        self.combo_tree = ttk.Treeview(self.combo_tab, columns=cols, show="headings", height=7)
        widths = (155, 135, 250, 170, 70, 65, 90)
        for col, width in zip(cols, widths):
            self.combo_tree.heading(col, text=col.capitalize())
            self.combo_tree.column(col, width=width, anchor="w")
        self.combo_tree.pack(fill="x", padx=12)
        self.combo_text = tk.Text(self.combo_tab, height=9, wrap="word", bg=COLORS["panel"],
                                  fg=COLORS["white"], relief="flat", padx=14, pady=10,
                                  font=("Segoe UI", 10))
        self.combo_text.pack(fill="both", expand=True, padx=12, pady=10)

    def _history_page(self) -> None:
        tk.Label(self.history_tab, text="HISTORIAL DE COMBINADAS", bg=COLORS["bg"], fg=COLORS["cyan"],
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
        cols = ("id", "fecha", "modo", "estado", "cuota", "probabilidad", "resultado", "balance")
        self.history_tree = ttk.Treeview(self.history_tab, columns=cols, show="headings")
        widths = (45, 150, 75, 105, 70, 90, 90, 90)
        for col, width in zip(cols, widths):
            self.history_tree.heading(col, text=col.capitalize())
            self.history_tree.column(col, width=width, anchor="w")
        self.history_tree.pack(fill="both", expand=True, padx=14, pady=8)
        buttons = tk.Frame(self.history_tab, bg=COLORS["bg"])
        buttons.pack(fill="x", padx=14, pady=(0, 12))
        self._button(buttons, "MARCAR GANADA", lambda: self._mark_history("Ganada"), "good").pack(side="left", padx=4)
        self._button(buttons, "MARCAR PERDIDA", lambda: self._mark_history("Perdida"), "bad").pack(side="left", padx=4)
        self._button(buttons, "PENDIENTE", lambda: self._mark_history("Pendiente"), "warn").pack(side="left", padx=4)
        self._refresh_history()

    def _settings_page(self) -> None:
        tk.Label(self.settings_tab, text="CONFIGURACIÓN", bg=COLORS["bg"], fg=COLORS["cyan"],
                 font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=18, pady=(18, 14))
        ttk.Checkbutton(self.settings_tab, text="Modo demostración", variable=self.demo_var).grid(row=1, column=0, sticky="w", padx=20, pady=6)
        ttk.Checkbutton(self.settings_tab, text="Navegador oculto (headless)", variable=self.headless_var).grid(row=1, column=1, sticky="w", padx=20, pady=6)
        self.updates_var = tk.BooleanVar(value=bool(self.config.get("check_updates", True)))
        ttk.Checkbutton(self.settings_tab, text="Buscar actualizaciones al iniciar",
                        variable=self.updates_var).grid(row=1, column=2, columnspan=2,
                                                        sticky="w", padx=20, pady=6)
        fields = [
            ("Cuota mínima", "target_odds_min"), ("Cuota máxima", "target_odds_max"),
            ("Máx. selecciones", "max_legs"), ("Prob. mínima por selección", "min_leg_probability"),
            ("Calidad mínima", "min_quality"), ("Ventaja mínima", "min_edge"),
        ]
        self.setting_vars: dict[str, tk.StringVar] = {}
        for i, (label, key) in enumerate(fields):
            row = 2 + i // 2
            col = (i % 2) * 2
            tk.Label(self.settings_tab, text=label, bg=COLORS["bg"], fg=COLORS["muted"]).grid(row=row, column=col, sticky="w", padx=20, pady=8)
            var = tk.StringVar(value=str(self.config.get(key, "")))
            self.setting_vars[key] = var
            ttk.Entry(self.settings_tab, textvariable=var, width=18).grid(row=row, column=col + 1, sticky="w", padx=8)
        row = 5
        tk.Label(self.settings_tab, text="Token Football-Data.org", bg=COLORS["bg"], fg=COLORS["muted"]).grid(row=row, column=0, sticky="w", padx=20, pady=8)
        self.token_var = tk.StringVar(value=str(self.config.get("football_data_token", "")))
        ttk.Entry(self.settings_tab, textvariable=self.token_var, width=42, show="•").grid(row=row, column=1, columnspan=2, sticky="w", padx=8)
        tk.Label(self.settings_tab, text="Se usa solo para forma y resultados; las cuotas salen de Triunfobet.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).grid(row=row + 1, column=0, columnspan=4, sticky="w", padx=20)
        buttons = tk.Frame(self.settings_tab, bg=COLORS["bg"])
        buttons.grid(row=row + 2, column=0, columnspan=4, sticky="w", padx=16, pady=20)
        self._button(buttons, "GUARDAR", self.save_settings, "cyan").pack(side="left", padx=4)
        self._button(buttons, "PROGRAMAR 8:00 A. M.", self.schedule_daily, "orange").pack(side="left", padx=4)
        self._button(buttons, "BUSCAR ACTUALIZACIÓN", lambda: self.check_updates(manual=True),
                     "good").pack(side="left", padx=4)
        tk.Label(self.settings_tab,
                 text=("Modo real: instala Playwright, desactiva demostración y agrega el token estadístico. "
                       "Si faltan estadísticas, la app mostrará los mercados pero no recomendará apostar."),
                 bg=COLORS["panel"], fg=COLORS["white"], wraplength=850, justify="left",
                 padx=14, pady=12).grid(row=row + 3, column=0, columnspan=4, sticky="we", padx=20)

    def start_analysis(self) -> None:
        if self.busy:
            messagebox.showinfo("RolmerBet", "Ya hay un análisis en curso.")
            return
        try:
            self.save_settings(silent=True)
            target_date = self._selected_date()
        except ValueError as exc:
            messagebox.showerror("Revisa la fecha o configuración", str(exc))
            return
        self.busy = True
        self.progress.start(12)
        self.status.set("Iniciando análisis…")

        def progress(message: str) -> None:
            self.queue.put(("progress", message))

        def worker() -> None:
            try:
                if self.config["demo_mode"]:
                    matches, contexts = demo_matches(target_date)
                    provider = DemoProvider(contexts)
                    mode = "DEMO"
                else:
                    collector = TriunfoBetCollector(self.config["triunfobet_url"], DIAGNOSTICS_DIR,
                                                    bool(self.config["headless"]))
                    matches = collector.collect(progress, target_date,
                                                self.config.get("competitions", []))
                    enabled = [normalize(x) for x in self.config.get("competitions", [])]
                    matches = [m for m in matches
                               if datetime.fromisoformat(m.kickoff_iso).date() == target_date
                               and any(c in normalize(m.competition) or normalize(m.competition) in c
                                       for c in enabled)]
                    provider = FootballDataProvider(self.config.get("football_data_token", ""),
                                                    int(self.config.get("recent_games", 10)))
                    mode = "REAL"
                evaluations = analyze_matches(matches, provider, self.config, progress)
                combo = build_combo(evaluations, self.config)
                self.db.save_run(mode, matches, evaluations, combo)
                self.queue.put(("done", (matches, evaluations, combo, mode, target_date)))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.status.set(payload)
                elif kind == "done":
                    self.busy = False
                    self.progress.stop()
                    self.matches, self.evaluations, self.combo, mode, target_date = payload
                    self.mode_badge.configure(text=f" {mode} ", bg=COLORS["warn"] if mode == "DEMO" else COLORS["good"])
                    self.status.set(f"{target_date.strftime('%d/%m/%Y')}: {len(self.matches)} partidos, "
                                    f"{len(self.evaluations)} mercados.")
                    self._refresh_all()
                    self.notebook.select(self.combo_tab)
                elif kind == "error":
                    self.busy = False
                    self.progress.stop()
                    self.status.set("Análisis detenido.")
                    messagebox.showerror("No se pudo completar", payload)
                elif kind == "update_available":
                    self.available_update = payload
                    self.update_button.configure(text=f"ACTUALIZAR A {payload.version}")
                    self.status.set(f"Actualización {payload.version} disponible.")
                elif kind == "update_none":
                    self.available_update = None
                    self.update_button.configure(text="ACTUALIZADO")
                    if payload:
                        messagebox.showinfo("Actualizaciones", "Ya tienes la versión más reciente.")
                elif kind == "update_error":
                    self.progress.stop()
                    self.update_button.configure(state="normal")
                    self.status.set("No se pudo consultar la actualización.")
                    if payload[1]:
                        messagebox.showerror("Actualizaciones", payload[0])
                elif kind == "update_progress":
                    self.status.set(payload)
                elif kind == "update_ready":
                    self.progress.stop()
                    self.status.set("Instalando actualización…")
                    launch_installer(payload)
                    self.root.after(250, self.root.destroy)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _refresh_all(self) -> None:
        self._refresh_matches()
        self._refresh_analysis()
        self._refresh_combo()
        self._refresh_history()

    def _refresh_matches(self) -> None:
        self.matches_tree.delete(*self.matches_tree.get_children())
        for m in self.matches:
            when = datetime.fromisoformat(m.kickoff_iso).strftime("%d/%m · %I:%M %p")
            self.matches_tree.insert("", "end", values=(when, m.competition, m.name, len(m.quotes)))

    def _refresh_analysis(self) -> None:
        self.analysis_tree.delete(*self.analysis_tree.get_children())
        for index, e in enumerate(self.evaluations):
            decision = "INCLUIR" if e.accepted else "DESCARTAR"
            self.analysis_tree.insert("", "end", iid=str(index), tags=("yes" if e.accepted else "no",),
                                      values=(e.match_name, f"{e.market}: {e.selection}", fmt_decimal(e.decimal),
                                              fmt_percent(e.implied), fmt_percent(e.adjusted_probability),
                                              e.quality, decision))

    def _show_evaluation(self, _event=None) -> None:
        selected = self.analysis_tree.selection()
        if not selected:
            return
        e = self.evaluations[int(selected[0])]
        text = (f"{e.competition}\n{e.match_name}\n\nMercado: {e.market}\nSelección: {e.selection}\n"
                f"Cuota Triunfobet visible: {e.american} / decimal: {e.decimal:.2f}\n"
                f"Probabilidad implícita: {fmt_percent(e.implied)}\n"
                f"Probabilidad del modelo: {fmt_percent(e.model_probability)}\n"
                f"Probabilidad prudente: {fmt_percent(e.adjusted_probability)}\n"
                f"Calidad de datos: {e.quality}/100\n\nRazón\n{e.reason}\n\nRiesgo principal\n"
                f"{e.main_risk}\n\nRuta\n{e.route}")
        self.analysis_detail.delete("1.0", "end")
        self.analysis_detail.insert("1.0", text)

    def _refresh_combo(self) -> None:
        self.combo_tree.delete(*self.combo_tree.get_children())
        self.combo_status.set("LISTA" if self.combo.status == "LISTA" else "NO APOSTAR")
        self.combo_odds.set(fmt_decimal(self.combo.total_odds))
        self.combo_prob.set(fmt_percent(self.combo.estimated_probability))
        for e in self.combo.selections:
            when = datetime.fromisoformat(e.kickoff_iso).strftime("%d/%m · %I:%M %p")
            self.combo_tree.insert("", "end", values=(e.competition, when, e.match_name,
                                                       f"{e.market}: {e.selection}", e.american,
                                                       fmt_decimal(e.decimal), fmt_percent(e.adjusted_probability)))
        self.combo_text.delete("1.0", "end")
        lines = [self.combo.message, ""]
        if self.combo.selections:
            calculation = " × ".join(fmt_decimal(e.decimal) for e in self.combo.selections)
            lines += [f"Cálculo: {calculation} = {self.combo.total_odds:.2f}",
                      f"Probabilidad implícita: {fmt_percent(self.combo.implied_probability)}",
                      f"Probabilidad prudente: {fmt_percent(self.combo.estimated_probability)}", ""]
            for i, e in enumerate(self.combo.selections, 1):
                lines += [f"{i}. {e.match_name} — {e.selection} ({e.market}) @ {e.decimal:.2f}",
                          f"   {e.reason}", f"   Ruta: {e.route}", ""]
        lines.append("Conservadora describe los filtros, no garantiza el resultado. No persigas pérdidas.")
        self.combo_text.insert("1.0", "\n".join(lines))

    def _refresh_history(self) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        for row in self.db.history():
            self.history_tree.insert("", "end", iid=str(row["id"]),
                                     values=(row["id"], row["created_at"], row["mode"], row["status"],
                                             f"{row['total_odds']:.2f}", fmt_percent(row["estimated_probability"]),
                                             row["result"], f"{row['profit']:+.2f}"))

    def _mark_history(self, result: str) -> None:
        selected = self.history_tree.selection()
        if not selected:
            messagebox.showinfo("Historial", "Selecciona una combinada.")
            return
        self.db.mark_result(int(selected[0]), result)
        self._refresh_history()

    def copy_combo(self) -> None:
        text = self.combo_text.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set("Combinada copiada.")

    def save_settings(self, silent: bool = False) -> None:
        try:
            self.config["demo_mode"] = bool(self.demo_var.get())
            self.config["headless"] = bool(self.headless_var.get())
            self.config["check_updates"] = bool(self.updates_var.get())
            self.config["football_data_token"] = self.token_var.get().strip()
            self.config["target_odds_min"] = float(self.setting_vars["target_odds_min"].get())
            self.config["target_odds_max"] = float(self.setting_vars["target_odds_max"].get())
            self.config["max_legs"] = int(float(self.setting_vars["max_legs"].get()))
            self.config["min_leg_probability"] = float(self.setting_vars["min_leg_probability"].get())
            self.config["min_quality"] = int(float(self.setting_vars["min_quality"].get()))
            self.config["min_edge"] = float(self.setting_vars["min_edge"].get())
            if self.config["target_odds_max"] <= self.config["target_odds_min"]:
                raise ValueError("La cuota máxima debe ser mayor que la mínima.")
            save_config(self.config)
            if not silent:
                messagebox.showinfo("Configuración", "Configuración guardada.")
        except ValueError as exc:
            if silent:
                raise
            messagebox.showerror("Configuración", str(exc))

    def _set_analysis_date(self, days_ahead: int) -> None:
        self.analysis_date_var.set((date.today() + timedelta(days=days_ahead)).isoformat())

    def _selected_date(self) -> date:
        try:
            selected = date.fromisoformat(self.analysis_date_var.get().strip())
        except ValueError as exc:
            raise ValueError("Escribe la fecha como AAAA-MM-DD, por ejemplo 2026-10-23.") from exc
        if selected < date.today():
            raise ValueError("Triunfobet ya no muestra las cuotas históricas. Elige hoy o una fecha futura.")
        return selected

    def _sync_mode_badge(self) -> None:
        demo = bool(self.demo_var.get())
        self.mode_badge.configure(text=" DEMO " if demo else " REAL ",
                                  bg=COLORS["warn"] if demo else COLORS["good"])

    def schedule_daily(self) -> None:
        try:
            message = install_daily("08:00")
            messagebox.showinfo("Programación", message + "\nComprueba que coincide con las 8:00 a. m. de Venezuela.")
        except Exception as exc:
            messagebox.showerror("Programación", str(exc))

    def check_updates(self, manual: bool = False) -> None:
        self.status.set("Consultando actualizaciones…")

        def worker() -> None:
            try:
                info = check_for_update()
                self.queue.put(("update_available", info) if info else ("update_none", manual))
            except UpdateError as exc:
                self.queue.put(("update_error", (str(exc), manual)))

        threading.Thread(target=worker, daemon=True).start()

    def install_update(self) -> None:
        if self.available_update is None:
            self.check_updates(manual=True)
            return
        info = self.available_update
        detail = f"\n\n{info.notes}" if info.notes else ""
        if not messagebox.askyesno(
            "Actualizar RolmerBet",
            f"Se instalará RolmerBet {info.version}. La aplicación se cerrará y volverá a abrir.{detail}\n\n"
            "Tu configuración e historial se conservarán. ¿Continuar?",
        ):
            return
        self.progress.start(12)
        self.update_button.configure(state="disabled")

        def progress(message: str) -> None:
            self.queue.put(("update_progress", message))

        def worker() -> None:
            try:
                plan = download_update(info, progress)
                self.queue.put(("update_ready", plan))
            except UpdateError as exc:
                self.queue.put(("update_error", (str(exc), True)))

        threading.Thread(target=worker, daemon=True).start()

    def _load_latest(self) -> None:
        self._sync_mode_badge()
        payload = self.db.latest_combo()
        if payload:
            try:
                self.combo = Combo.from_dict(payload)
                self._refresh_combo()
                self.status.set("Última combinada cargada. Puedes ejecutar un análisis nuevo.")
            except (KeyError, TypeError, ValueError):
                self.status.set("El historial existe, pero la última combinada no pudo reconstruirse.")


def run(auto: bool = False) -> None:
    root = tk.Tk()
    RolmerBetApp(root, auto=auto)
    root.mainloop()

