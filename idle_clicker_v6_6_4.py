#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Idle Clicker v6.6.4 — CPC coût dynamique + TAP visible immédiatement
- Le coût d'**Améliorer le TAP (+1)** se met à jour en temps réel.
- Le bouton **TAPER !** s'affiche dès le lancement (redraw sur <Configure> + after(0)).
- Sauvegarde robuste (schéma v670), anti-jiggle conservé.
"""
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from tkinter import font as tkfont
import time, json, os, math, random, sys, shutil

try:
    import ttkbootstrap as tb
    THEME_AVAILABLE = True
except Exception:
    THEME_AVAILABLE = False

APP_TITLE = "Idle Clicker v6.6.4 — Python"
SAVE_FILE = "idle_save.json"
SCHEMA_VERSION = 670
OFFLINE_HOURS_CAP = 12
BASE_PARTICLE_CAP = 120

def format_num(n: float) -> str:
    try: n = float(n)
    except Exception: return "0"
    suffixes = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "De"]
    if abs(n) < 1000:
        if abs(n - int(n)) < 1e-6: return str(int(n))
        return f"{n:.1f}"
    magnitude = int(math.log(max(abs(n), 1), 1000))
    magnitude = min(magnitude, len(suffixes)-1)
    value = n / (1000 ** magnitude)
    if value >= 100: return f"{value:.0f}{suffixes[magnitude]}"
    if value >= 10:  return f"{value:.1f}{suffixes[magnitude]}"
    return f"{value:.2f}{suffixes[magnitude]}"

def clamp01(x: float) -> float:
    try: return max(0.0, min(1.0, float(x)))
    except Exception: return 0.0

class FancyTap(tk.Canvas):
    """Canvas button with ripple click animation (pure paint, no geometry change)."""
    def __init__(self, master, text, command, **kw):
        super().__init__(master, width=200, height=56, highlightthickness=0, bg=kw.get("bg","#0b0f24"))
        self.command = command; self.text = text; self._pressed = False
        self.bind("<Button-1>", self._on_press); self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._draw(hover=True)); self.bind("<Leave>", lambda e: self._draw(hover=False))
        self.bind("<Configure>", lambda e: self._draw())  # redraw when getting real size
        self._ripples = []  # (r, maxr, alpha)
        self._draw()
        self.after(0, self._draw)  # ensure first paint after layout

    def _rounded_rect(self, x1,y1,x2,y2,r, **kw):
        self.create_arc(x1, y1, x1+2*r, y1+2*r, start=90, extent=90, style="pieslice", **kw)
        self.create_arc(x2-2*r, y1, x2, y1+2*r, start=0, extent=90, style="pieslice", **kw)
        self.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90, style="pieslice", **kw)
        self.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90, style="pieslice", **kw)
        self.create_rectangle(x1+r, y1, x2-r, y2, **kw); self.create_rectangle(x1, y1+r, x2, y2-r, **kw)
    def _draw(self, hover=False):
        self.delete("all")
        w = self.winfo_width() or 200; h = self.winfo_height() or 56; r = 16
        for i in range(h):
            t = i/max(1,h-1)
            base = 95 if self._pressed else (120 if hover else 105)
            rcol = 20 + int(20*t); gcol = 30 + int(30*t); bcol = base + int(60*t)
            self.create_line(6, i+6, w-6, i+6, fill=f"#{rcol:02x}{gcol:02x}{bcol:02x}")
        self._rounded_rect(4,4,w-4,h-4,r, outline="#7c83ff", width=2)
        self.create_text(w//2, h//2, text=self.text, fill="#e6e9ff", font=("Arial", 15, "bold"))
        if self._ripples:
            cx, cy = w//2, h//2
            for r_now, r_max, a in list(self._ripples):
                self.create_oval(cx-r_now, cy-r_now, cx+r_now, cy+r_now, outline="#7c83ff", width=2)
    def _on_press(self, e): self._pressed = True; self._draw(hover=True)
    def _on_release(self, e):
        if self._pressed and self.command:
            self._spawn_ripple()
            self.command()
        self._pressed = False; self._draw(hover=True)
    def _spawn_ripple(self):
        w = self.winfo_width() or 200; h = self.winfo_height() or 56
        maxr = int(min(w, h)/2)-6
        self._ripples.append((6, maxr, 1.0))
        def step():
            new = []
            for r_now, r_max, a in self._ripples:
                r_now += max(2, r_max/10.0); a -= 0.12
                if a > 0 and r_now < r_max: new.append((r_now, r_max, a))
            self._ripples[:] = new
            self._draw(hover=True)
            if new: self.after(16, step)
        self.after(0, step)

class IdleGame:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("760x860"); self.root.minsize(660, 740)

        # --- State ---
        self.gold = 0.0; self.total_earned = 0.0
        self.cpc = 1.0; self.cpc_level = 0
        self.prestige_shards = 0; self.prestige_spent_levels = 0
        self.achievements = set(); self.last_time = time.time()

        # Display values
        self._disp_gold = 0.0; self._disp_cps  = 0.0; self._disp_cpc  = 1.0; self._disp_pb = 0.0
        self._decay = {"active": False, "dur": 3.0, "t": 0.0, "start": {}, "target": {}}

        # Upgrades
        self.upgrade_defs = [
            ("Assistant", 15, 1.15, 0.1), ("Mine", 150, 1.15, 1.0), ("Usine", 1200, 1.15, 8.0),
            ("Ville", 15000, 1.15, 50.0), ("Fusée", 250000, 1.15, 350.0), ("Station Orbitale", 2_500_000, 1.15, 2_000.0),
            ("Colonies Lunaires", 20_000_000, 1.15, 12_000.0), ("Réacteur à Fusion", 150_000_000, 1.15, 75_000.0),
            ("IA Générative", 1_200_000_000, 1.15, 520_000.0), ("Ascenseur Spatial", 9_500_000_000, 1.15, 3_600_000.0),
            ("Terraformeur", 75_000_000_000, 1.15, 24_000_000.0), ("Portail Interstellaire", 620_000_000_000, 1.15, 170_000_000.0),
            ("Essaim Dyson", 5_000_000_000_000, 1.15, 1_250_000_000.0), ("Matériau Exotique", 40_000_000_000_000, 1.15, 9_500_000_000.0),
            ("Fonderie Quantique", 320_000_000_000_000, 1.15, 70_000_000_000.0), ("Ancrage Dimensionnel", 2_600_000_000_000_000, 1.15, 520_000_000_000.0),
            ("Chantier d'Étoiles", 21_000_000_000_000_000, 1.15, 3_900_000_000_000.0), ("Moteur d'Alcubierre", 170_000_000_000_000_000, 1.15, 29_000_000_000_000.0),
            ("Oracle Chronique", 1_350_000_000_000_000_000, 1.15, 220_000_000_000_000.0), ("Forge Cosmique", 10_800_000_000_000_000_000, 1.15, 1_650_000_000_000_000.0),
        ]
        self.upgrades = {name: 0 for (name, *_rest) in self.upgrade_defs}
        self.cps = 0.0
        self.discovered = set()

        # Achievements
        self.ach_defs = {
            "first_click": {"name": "Premier Tap", "desc": "Fais ton premier clic.", "check": lambda g: g.total_earned >= 1},
            "cpc5": {"name": "Doigt musclé", "desc": "Atteins CPC ≥ 5.", "check": lambda g: g.cpc >= 5},
            "cpc20": {"name": "Index d'acier", "desc": "Atteins CPC ≥ 20.", "check": lambda g: g.cpc >= 20},
            "cps100": {"name": "Ça tourne tout seul", "desc": "Atteins CPS ≥ 100.", "check": lambda g: g.cps >= 100},
            "cps10k": {"name": "Usine à or", "desc": "Atteins CPS ≥ 10K.", "check": lambda g: g.cps >= 10_000},
            "mine10": {"name": "Mineur confirmé", "desc": "Avoir 10 Mines.", "check": lambda g: g.upgrades.get("Mine",0) >= 10},
            "fusion1": {"name": "Allumage Fusion", "desc": "Acheter 1 Réacteur à Fusion.", "check": lambda g: g.upgrades.get("Réacteur à Fusion",0) >= 1},
            "billionaire": {"name": "Milliardaire", "desc": "Gagner 1B au total.", "check": lambda g: g.total_earned >= 1_000_000_000},
            "shard1": {"name": "Renaissance", "desc": "Gagner 1 shard.", "check": lambda g: g.prestige_shards >= 1},
            "shard5": {"name": "Conquérant du temps", "desc": "Gagner 5 shards.", "check": lambda g: g.prestige_shards >= 5},
            "shard10": {"name": "Seigneur des runs", "desc": "Gagner 10 shards.", "check": lambda g: g.prestige_shards >= 10},
        }

        # UI
        self._build_ui()

        # Trackers BEFORE any UI updates
        self._last_values = {"gold": self.gold, "cps": self.cps, "cpc": self.cpc, "mult": self.prestige_multiplier}
        self._last_upgrade_counts = dict(self.upgrades)
        self._gold_float_labels = []

        # Load & init
        self.load()
        self._recompute_discovery(from_save=True)
        self._snap_display()
        self._update_ach_btn()
        self._sync_particles_to_shards()

        # Loops
        self._last_anim_time = time.time()
        self._logic_tick()
        self._anim_tick_30fps()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        if THEME_AVAILABLE:
            try: tb.Style("superhero")
            except Exception: pass
        self.root.configure(bg="#0b0f24")
        self.accent="#7c83ff"; self.fg_primary="#e6e9ff"; self.fg_muted="#b8bdff"
        self.card_bg="#111635"; self.btn_bg="#171d43"; self.btn_active="#222a5b"

        chips = tk.Frame(self.root, bg="#0b0f24"); chips.pack(fill="x", padx=12, pady=(6,4))

        self.font_val = tkfont.Font(family="Arial", size=13, weight="bold")

        def chip(label_text):
            c = tk.Frame(chips, bg=self.card_bg)
            hdr = tk.Label(c, text=label_text, font=("Arial",9,"bold"), fg="#9fb1ff", bg=self.card_bg)
            hdr.pack(anchor="w", padx=8, pady=(6,0))
            v = tk.StringVar(value="-")
            val = tk.Label(c, textvariable=v, font=self.font_val, fg=self.fg_primary, bg=self.card_bg, width=14, anchor="w", justify="left")
            val.pack(anchor="w", padx=8, pady=(0,6))
            c.pack(side="left", padx=6, ipadx=6, ipady=2, fill="x", expand=True)
            return v, c, val, hdr

        self.gold_chip, self.gold_chip_frame, self.gold_chip_value, self.gold_chip_hdr = chip("OR")
        self.cps_chip,  self.cps_chip_frame,  self.cps_chip_value,  self.cps_chip_hdr  = chip("CPS")
        self.cpc_chip,  self.cpc_chip_frame,  self.cpc_chip_value,  self.cpc_chip_hdr  = chip("CPC")
        self.mult_chip, self.mult_chip_frame, self.mult_chip_value, self.mult_chip_hdr = chip("MULT")

        info = tk.Frame(self.root, bg="#0b0f24"); info.pack(fill="x", padx=16)
        self.total_var=tk.StringVar(value="Gagné au total : 0")
        self.shard_info_var=tk.StringVar(value="Shards : 0  |  Prochain palier : 10^7")
        tk.Label(info, textvariable=self.total_var, font=("Arial", 10), fg=self.fg_muted, bg="#0b0f24").pack(side="left")
        tk.Label(info, textvariable=self.shard_info_var, font=("Arial", 10), fg=self.fg_muted, bg="#0b0f24").pack(side="right")
        pb_frame=tk.Frame(self.root, bg="#0b0f24"); pb_frame.pack(fill="x", padx=16, pady=(4,6))
        self.pb=ttk.Progressbar(pb_frame, orient="horizontal", mode="determinate"); self.pb.pack(fill="x")

        meta=tk.Frame(self.root, bg="#0b0f24"); meta.pack(fill="x", padx=16, pady=(0,4))
        self.ach_btn=tk.Button(meta, text="Succès (0)", font=("Arial", 11, "bold"),
                               fg=self.fg_primary, bg=self.btn_bg, activebackground=self.btn_active,
                               relief="flat", bd=0, padx=10, pady=8, command=self.open_achievements, cursor="hand2")
        self.ach_btn.pack(side="left")
        self.prestige_btn_var=tk.StringVar(value="Prestige (0 shards)")
        self.prestige_btn=tk.Button(meta, textvariable=self.prestige_btn_var, font=("Arial", 11, "bold"),
                                    fg="#ffe8a3", bg=self.btn_bg, activebackground=self.btn_active,
                                    relief="flat", bd=0, padx=12, pady=8, command=self.try_prestige, cursor="hand2", state="disabled")
        self.prestige_btn.pack(side="right", padx=(0,8))

        self.anim_canvas=tk.Canvas(self.root, height=52, bg="#0b0f24", highlightthickness=0)
        self.anim_canvas.pack(fill="x", padx=0, pady=(0,4)); self._particles=[]

        first_row=tk.Frame(self.root, bg="#0b0f24"); first_row.pack(fill="x", padx=16, pady=(0,8))
        self.cpc_cost_var=tk.StringVar(value="Améliorer le TAP (+1) — Coût : 10")
        self.cpc_btn=tk.Button(first_row, textvariable=self.cpc_cost_var, font=("Arial", 12, "bold"),
                               fg=self.fg_primary, bg=self.btn_bg, activebackground=self.btn_active,
                               relief="flat", bd=0, padx=12, pady=8, command=self.buy_cpc, cursor="hand2")
        self.cpc_btn.pack(side="left")
        self.tap_btn=FancyTap(first_row, "TAPER !", command=self.on_tap, bg="#0b0f24"); self.tap_btn.pack(side="right")

        list_container=tk.Frame(self.root, bg="#0b0f24"); list_container.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        tk.Label(list_container, text="Améliorations Passives (CPS)", font=("Arial", 14, "bold"), fg=self.fg_primary, bg="#0b0f24").pack(anchor="w", pady=(0,8))

        canvas=tk.Canvas(list_container, bg="#0b0f24", highlightthickness=0)
        scrollbar=tk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        self.scroll_frame=tk.Frame(canvas, bg="#0b0f24")
        self.scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True); scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            if sys.platform.startswith("darwin"): delta = -1 * int(event.delta)
            else: delta = -1 * int(event.delta/120) if event.delta else 0
            canvas.yview_scroll(delta, "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

        self.upgrade_widgets={}
        for name, base_cost, mult, unit_cps in self.upgrade_defs:
            row=tk.Frame(self.scroll_frame, bg=self.card_bg, padx=12, pady=10, bd=0)
            left=tk.Frame(row, bg=self.card_bg); left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=name, font=("Arial", 12, "bold"), fg=self.fg_primary, bg=self.card_bg).pack(anchor="w")
            tk.Label(left, text=f"+{format_num(unit_cps)} CPS par {name.lower()}", font=("Arial", 10), fg="#9fb1ff", bg=self.card_bg).pack(anchor="w")
            right=tk.Frame(row, bg=self.card_bg); right.pack(side="right")

            count_var=tk.StringVar(value="x0"); line_cps_var=tk.StringVar(value="+0 CPS"); cost_var=tk.StringVar(value=f"Coût : {format_num(base_cost)}")
            count_lbl = tk.Label(right, textvariable=count_var, width=6, font=("Arial", 11, "bold"), fg=self.accent, bg=self.card_bg)
            count_lbl.pack(side="left", padx=(0,8))
            tk.Label(right, textvariable=line_cps_var, width=12, font=("Arial", 10, "bold"), fg=self.fg_muted, bg=self.card_bg, anchor="e").pack(side="left", padx=(0,8))

            buy_btn=tk.Button(right, textvariable=cost_var, font=("Arial", 11, "bold"), fg=self.fg_primary, bg=self.btn_bg, activebackground=self.btn_active,
                              relief="flat", bd=0, padx=10, pady=6, cursor="hand2", command=lambda n=name: self.buy_upgrade_one(n), state="disabled", disabledforeground="#6b6f99")
            buy_btn.pack(side="left", padx=(0,6))
            max_label = tk.StringVar(value="Max (0)")
            max_btn=tk.Button(right, textvariable=max_label, font=("Arial", 11, "bold"), fg=self.fg_primary, bg=self.btn_bg, activebackground=self.btn_active,
                              relief="flat", bd=0, padx=10, pady=6, cursor="hand2", command=lambda n=name: self.buy_upgrade_max(n), state="disabled", disabledforeground="#6b6f99")
            max_btn.pack(side="left")

            for b in (buy_btn, max_btn):
                b.bind("<Enter>", lambda e, b=b: b.configure(bg=self.btn_active if str(b['state'])=='normal' else self.btn_bg))
                b.bind("<Leave>", lambda e, b=b: b.configure(bg=self.btn_bg))

            self.upgrade_widgets[name]={"row": row,"count_var": count_var,"count_lbl":count_lbl,"line_cps_var": line_cps_var,"cost_var": cost_var,
                                        "buy_btn": buy_btn,"max_btn": max_btn,"max_label": max_label,
                                        "base_cost": base_cost, "mult": mult, "unit_cps": unit_cps}

        # Footer
        footer=tk.Frame(self.root, bg="#0b0f24"); footer.pack(fill="x", pady=(0,10))
        tk.Button(footer, text="Sauvegarder", command=self.save, font=("Arial", 10, "bold"), fg=self.fg_primary, bg=self.btn_bg,
                  activebackground=self.btn_active, relief="flat", bd=0, padx=10, pady=6, cursor="hand2").pack(side="left", padx=16)
        tk.Button(footer, text="Réinitialiser", command=self.reset_confirm, font=("Arial", 10, "bold"), fg="#ffb3b3", bg=self.btn_bg,
                  activebackground=self.btn_active, relief="flat", bd=0, padx=10, pady=6, cursor="hand2").pack(side="right", padx=16)

        self.banner=tk.Label(self.root, text="", font=("Arial", 14, "bold"), fg="#0b0f24", bg="#b5ffb8")
        self.banner.place_forget()

        self._refresh_all_labels()

    # ---------------- Logic ----------------
    @property
    def prestige_multiplier(self) -> float:
        return 1.0 + 0.25 * float(self.prestige_shards)

    def on_tap(self):
        gain = self.cpc * (1.0 + 0.05 * self.prestige_shards)
        self.gold += gain; self.total_earned += gain
        self._snap_numbers()
        self._floating_text_btn(f"+{format_num(gain)}")
        self._float_over_gold(f"+{format_num(gain)}")
        self._check_achievements(); self._update_upgrade_visibility()

    def buy_cpc(self):
        cost=self._cpc_cost()
        if self.gold >= cost:
            self.gold -= cost; self.cpc_level += 1; self.cpc = 1.0 + self.cpc_level * 1.0
            self._recalc_cps(); self._snap_numbers()
            self._show_banner("TAP amélioré !"); self._check_achievements()
        else: self._show_banner("Pas assez d'or.", ok=False)
        self._update_upgrade_visibility()

    def buy_upgrade_one(self, name: str):
        c = self._upgrade_cost(name)
        if self.gold >= c:
            self.gold -= c; self.upgrades[name] += 1; self.discovered.add(name)
            self._recalc_cps(); self._snap_numbers(); self._check_achievements()
            self._flash_label(self.upgrade_widgets[name]["count_lbl"])
        else: self._show_banner("Pas assez d'or.", ok=False)
        self._update_upgrade_visibility()

    def buy_upgrade_max(self, name: str):
        bought = 0
        while True:
            c = self._upgrade_cost(name)
            if self.gold >= c:
                self.gold -= c; self.upgrades[name] += 1; bought += 1
            else: break
        if bought > 0:
            self.discovered.add(name); self._recalc_cps(); self._snap_numbers(); self._check_achievements()
            self._flash_label(self.upgrade_widgets[name]["count_lbl"])
        else: self._show_banner("Pas assez d'or.", ok=False)
        self._update_upgrade_visibility()

    def _recalc_cps(self):
        cps = 0.0
        for name, data in getattr(self, "upgrade_widgets", {}).items():
            cps += self.upgrades.get(name, 0) * data["unit_cps"]
        self.cps = cps * self.prestige_multiplier

    def _cpc_cost(self) -> int:
        try: return int(round(10 * (1.5 ** int(self.cpc_level))))
        except Exception: return 10

    def _upgrade_cost(self, name: str) -> int:
        data = self.upgrade_widgets[name]; count = self.upgrades.get(name, 0)
        try: return int(round(data["base_cost"] * (data["mult"] ** count)))
        except Exception: return int(data["base_cost"])

    def _max_affordable_qty(self, name: str) -> int:
        data = self.upgrade_widgets[name]; count = self.upgrades.get(name, 0)
        base = data["base_cost"] * (data["mult"] ** count); m = data["mult"]
        g = self.gold
        if g < base: return 0
        if abs(m - 1.0) < 1e-9:
            return int(g // base)
        k = int(math.floor(math.log(1 + (m - 1) * (g / base), m)))
        return max(0, k)

    # Prestige -----------------------------------------
    def _current_level(self) -> int:
        t = max(1.0, float(self.total_earned))
        try: lv = int(max(0, math.floor(math.log10(t)) - 6))
        except Exception: lv = 0
        return lv
    def _potential_shards_gain(self) -> int:
        return max(0, self._current_level() - int(self.prestige_spent_levels))
    def try_prestige(self):
        gain = self._potential_shards_gain()
        if gain <= 0: return
        nxt = 6 + self.prestige_spent_levels + 1
        if messagebox.askyesno("Prestige", f"Confirmer ? Vous gagnerez +{gain} shard(s).\n"
                                           f"Multiplicateur CPS +25% par shard.\n"
                                           f"Reset : or, upgrades, CPC.\n\n"
                                           f"Palier suivant à 10^{int(nxt)} de total gagné."):
            self._do_prestige(gain)
    def _do_prestige(self, gain: int):
        self.prestige_shards += gain; self.prestige_spent_levels += gain
        self.gold = 0.0; self.cpc = 1.0; self.cpc_level = 0
        self.upgrades = {name: 0 for (name, *_rest) in self.upgrade_defs}
        self.discovered = set()
        self._confetti(); self._show_banner(f"+{gain} shard(s) ! Mult x{self.prestige_multiplier:.2f}")
        self._start_decay({"gold":0.0,"cps":0.0,"cpc":1.0,"pb":0.0}, dur=3.0)
        self._sync_particles_to_shards(); self._refresh_all_labels(); self._update_upgrade_visibility()

    # Decay & progress ---------------------------------
    def _start_decay(self, targets: dict, dur: float = 3.0):
        self._decay = {"active": True, "dur": dur, "t": 0.0,
                       "start": {"gold": self._disp_gold, "cps": self._disp_cps, "cpc": self._disp_cpc, "pb": self._disp_pb},
                       "target": targets}
    def _step_decay(self, dt: float):
        if not self._decay["active"]: return
        self._decay["t"] += dt; t = clamp01(self._decay["t"] / max(0.001, self._decay["dur"]))
        lerp = lambda a,b,t: a + (b-a)*t
        self._disp_gold = lerp(self._decay["start"]["gold"], self._decay["target"]["gold"], t)
        self._disp_cps  = lerp(self._decay["start"]["cps"],  self._decay["target"]["cps"],  t)
        self._disp_cpc  = lerp(self._decay["start"]["cpc"],  self._decay["target"]["cpc"],  t)
        self._disp_pb   = lerp(self._decay["start"]["pb"],   self._decay["target"]["pb"],   t)
        if t >= 1.0: self._decay["active"] = False
    def _update_progress_disp(self):
        cur = max(0.0, math.log10(max(self.total_earned, 1)) - 6.0)
        self._disp_pb = clamp01(cur - self.prestige_spent_levels)

    # ---- Achievements ----
    def _check_achievements(self):
        unlocked = 0
        for aid, a in self.ach_defs.items():
            try:
                if aid not in self.achievements and a["check"](self):
                    self.achievements.add(aid); unlocked += 1
                    self._show_banner(f"Succès : {a['name']} ✓", ok=True)
            except Exception:
                continue
        if unlocked: self._update_ach_btn()

    def _update_ach_btn(self):
        known = set(self.ach_defs.keys())
        current = len([a for a in self.achievements if a in known])
        total = len(self.ach_defs)
        try:
            self.ach_btn.configure(text=f"Succès ({current}/{total})")
        except Exception:
            pass

    def open_achievements(self):
        win = tk.Toplevel(self.root); win.title("Succès"); win.configure(bg="#0b0f24")
        known = set(self.ach_defs.keys()); self.achievements = set([a for a in self.achievements if a in known])
        header = tk.Frame(win, bg="#0b0f24"); header.pack(fill="x", padx=12, pady=8)
        current = len(self.achievements); total = len(self.ach_defs)
        tk.Label(header, text=f"Succès débloqués : {current}/{total}", font=("Arial", 12, "bold"), fg=self.fg_primary, bg="#0b0f24").pack(anchor="w")
        canvas = tk.Canvas(win, bg="#0b0f24", highlightthickness=0, height=420)
        sc = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        frame = tk.Frame(canvas, bg="#0b0f24")
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=sc.set)
        canvas.pack(side="left", fill="both", expand=True); sc.pack(side="right", fill="y")
        def _on_mousewheel(event):
            if sys.platform.startswith("darwin"): delta = -1 * int(event.delta)
            else: delta = -1 * int(event.delta/120) if event.delta else 0
            canvas.yview_scroll(delta, "units")
        win.bind("<MouseWheel>", _on_mousewheel); win.bind("<Button-4>", lambda e: canvas.yview_scroll(-1, "units")); win.bind("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        for aid, a in self.ach_defs.items():
            got = aid in self.achievements
            row = tk.Frame(frame, bg=(self.card_bg if not got else "#b5ffb8")); row.pack(fill="x", padx=12, pady=4)
            tk.Label(row, text=("✓" if got else "•"), font=("Arial", 12, "bold"),
                     fg=("#0b0f24" if got else self.fg_primary), bg=("#b5ffb8" if got else self.card_bg), width=2).pack(side="left", padx=(8,4))
            tk.Label(row, text=a["name"], font=("Arial", 11, "bold"),
                     fg=("#0b0f24" if got else self.fg_primary), bg=("#b5ffb8" if got else self.card_bg)).pack(side="left", padx=(0,6))
            tk.Label(row, text=a["desc"], font=("Arial", 10),
                     fg=("#264d2a" if got else self.fg_muted), bg=("#b5ffb8" if got else self.card_bg)).pack(side="left")

    # Animations (non-intrusives) ----------------------
    def _flash_label(self, lbl, color="#dbe6ff", dur=220):
        old_fg = lbl.cget("fg"); old_bg = lbl.cget("bg")
        lbl.configure(fg=color)
        lbl.after(dur, lambda: (lbl.configure(fg=old_fg, bg=old_bg)))

    def _float_over_gold(self, text: str):
        # place closer to the "OR" header
        if len(self._gold_float_labels) >= 8:
            try:
                lbl = self._gold_float_labels.pop(0); lbl.destroy()
            except Exception: pass
        self.root.update_idletasks()
        hdr = self.gold_chip_hdr if hasattr(self, "gold_chip_hdr") else self.gold_chip_value
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        x = hdr.winfo_rootx() - rx + hdr.winfo_width() + 6
        y = hdr.winfo_rooty() - ry + max(0, (hdr.winfo_height()//2) - 6)
        lbl = tk.Label(self.root, text=text, font=("Arial", 10, "bold"), fg="#cfe3ff", bg="#0b0f24")
        lbl.place(x=x, y=y)
        self._gold_float_labels.append(lbl)
        steps = 18
        def anim(i=0):
            if i >= steps:
                try: self._gold_float_labels.remove(lbl)
                except Exception: pass
                lbl.destroy(); return
            lbl.place(y=y - i*3); self.root.after(14, lambda: anim(i+1))
        anim()

    def _floating_text_btn(self, text: str):
        lbl = tk.Label(self.tap_btn, text=text, font=("Arial", 11, "bold"), fg="#e6e9ff", bg="#0b0f24")
        self.tap_btn.update_idletasks(); w = self.tap_btn.winfo_width(); h = self.tap_btn.winfo_height()
        lbl.place(x=w//2 + random.randint(-20,20), y=h//2)
        steps = 16
        def animate(i=0):
            if i >= steps: lbl.destroy(); return
            lbl.place(y=h//2 - i*3); self.root.after(14, lambda: animate(i+1))
        animate()

    # Discovery / visibility ---------------------------
    def _recompute_discovery(self, from_save=False):
        for name in self.upgrades.keys():
            if self.upgrades.get(name,0) > 0: self.discovered.add(name)
        self._update_upgrade_visibility(initial=True)

    def _next_undiscovered_name(self):
        for name, *_ in self.upgrade_defs:
            if name not in self.discovered:
                return name
        return None

    def _update_upgrade_visibility(self, initial=False):
        next_name = self._next_undiscovered_name()
        if not hasattr(self, "_last_upgrade_counts"): self._last_upgrade_counts = {}
        for name, data in self.upgrade_widgets.items():
            row = data["row"]; buy_btn = data["buy_btn"]; max_btn = data["max_btn"]; max_label = data["max_label"]
            discovered = (name in self.discovered)
            should_show = discovered or (name == next_name)
            visible = getattr(row, "_visible", False)
            if should_show and not visible:
                row.pack(fill="x", pady=6); row._visible = True
            elif not should_show and visible:
                row.pack_forget(); row._visible = False

            count = self.upgrades.get(name, 0)
            line_cps = count * data["unit_cps"] * self.prestige_multiplier
            data["count_var"].set(f"x{count}")
            data["line_cps_var"].set(f"+{format_num(line_cps)} CPS")
            if self._last_upgrade_counts.get(name, 0) != count:
                self._flash_label(data["count_lbl"])
                self._last_upgrade_counts[name] = count

            cost1 = self._upgrade_cost(name)
            data["cost_var"].set(f"Coût : {format_num(cost1)}")

            affordable1 = self.gold >= cost1
            qty = self._max_affordable_qty(name)
            max_label.set(f"Max ({qty})")
            state_buy = "normal" if affordable1 and should_show else "disabled"
            state_max = "normal" if qty > 0 and should_show else "disabled"
            buy_btn.configure(state=state_buy); max_btn.configure(state=state_max)

        try: self.scroll_frame.update_idletasks()
        except Exception: pass

    # UI helpers ---------------------------------------
    def _snap_numbers(self):
        self._recalc_cps()
        self._disp_gold = float(self.gold); self._disp_cps = float(self.cps); self._disp_cpc = float(self.cpc)
        self._update_progress_disp(); self._refresh_all_labels()

    def _snap_display(self):
        self._snap_numbers(); self.root.update_idletasks(); self._update_upgrade_visibility(initial=True)

    def _refresh_all_labels(self):
        # Primary chips
        self.gold_chip.set(format_num(self._disp_gold)); self.cps_chip.set(format_num(self._disp_cps))
        self.cpc_chip.set(format_num(self._disp_cpc)); self.mult_chip.set(f"x{self.prestige_multiplier:.2f}")
        # Dynamic CPC cost text
        try:
            self.cpc_cost_var.set(f"Améliorer le TAP (+1) — Coût : {format_num(self._cpc_cost())}")
        except Exception:
            pass
        # Footer infos + progress
        self.total_var.set(f"Gagné au total : {format_num(self.total_earned)}")
        next_exp = 6 + self.prestige_spent_levels + 1
        self.shard_info_var.set(f"Shards : {self.prestige_shards}  |  Prochain palier : 10^{int(next_exp)}")
        self.pb['value'] = clamp01(self._disp_pb) * 100

        # Subtle flash (color only)
        cur_vals = {"gold": self._disp_gold, "cps": self._disp_cps, "cpc": self._disp_cpc, "mult": self.prestige_multiplier}
        if not hasattr(self, "_last_values"): self._last_values = {}
        for key, val in cur_vals.items():
            last = self._last_values.get(key, None)
            if last is None or abs(val - last) > 1e-9:
                self._last_values[key] = val
                if key == "gold":   self._flash_label(self.gold_chip_value)
                if key == "cps":    self._flash_label(self.cps_chip_value)
                if key == "cpc":    self._flash_label(self.cpc_chip_value)
                if key == "mult":   self._flash_label(self.mult_chip_value)

    # Particles ----------------------------------------
    def _desired_particle_cap(self):
        w = max(1, self.anim_canvas.winfo_width()); density_scale = w / 760.0
        return int(BASE_PARTICLE_CAP * max(0.6, min(1.5, density_scale)))
    def _sync_particles_to_shards(self):
        cap = min(self.prestige_shards, self._desired_particle_cap())
        current = len(self._particles) if hasattr(self, "_particles") else 0
        if not hasattr(self, "_particles"): self._particles = []
        if cap > current:
            for _ in range(cap - current):
                x = random.randint(10, max(20, self.anim_canvas.winfo_width()-10)); y = random.randint(8, 44)
                vx = random.uniform(-0.2, 0.2); vy = random.uniform(-0.1, 0.1); life = random.uniform(1.0, 3.0)
                self._particles.append([x,y,vx,vy,life])
        elif cap < current:
            self._particles = self._particles[:cap]
    def _update_particles(self, dt):
        self._sync_particles_to_shards()
        self.anim_canvas.delete("p")
        w = max(1, self.anim_canvas.winfo_width()); h = max(1, self.anim_canvas.winfo_height())
        alive = []
        for (x,y,vx,vy,life) in self._particles:
            life -= dt
            if life <= 0:
                x = random.randint(10, w-10); y = random.randint(6, h-6)
                vx = random.uniform(-0.2, 0.2); vy = random.uniform(-0.1, 0.1); life = random.uniform(1.0, 3.0)
            x += vx * 60 * dt; y += vy * 60 * dt
            size = 2 + (y/h)*2.5
            self.anim_canvas.create_oval(x-size, y-size, x+size, y+size, fill="#8aa5ff", outline="", tags="p")
            alive.append([x,y,vx,vy,life])
        self._particles = alive
    def _confetti(self):
        w = max(1, self.anim_canvas.winfo_width()); burst = min(50, 10 + self.prestige_shards//5)
        for _ in range(burst):
            x = random.randint(0, w); y = 0
            vx = random.uniform(-1.0, 1.0); vy = random.uniform(1.0, 2.5); life = random.uniform(0.8, 1.8)
            self._particles.append([x,y,vx,vy,life])

    # Loops --------------------------------------------
    def _logic_tick(self):
        self.gold += self.cps; self.total_earned += self.cps
        if self.cps > 0: self._float_over_gold(f"+{format_num(self.cps)}")
        if not self._decay["active"]:
            self._disp_gold=self.gold; self._disp_cps=self.cps; self._disp_cpc=self.cpc; self._update_progress_disp()
        self._refresh_all_labels(); self._update_ach_btn(); self._update_upgrade_visibility()
        self.root.after(1000, self._logic_tick)
    def _anim_tick_30fps(self):
        now = time.time(); dt = now - getattr(self, "_last_anim_time", now); self._last_anim_time = now
        self._step_decay(min(dt, 0.05)); self._update_particles(min(dt, 0.05)); self.root.after(33, self._anim_tick_30fps)

    # Persistence --------------------------------------
    def save(self, silent: bool = False):
        data = {
            "schema_version": SCHEMA_VERSION,
            "gold": float(self.gold), "cpc_level": int(self.cpc_level),
            "upgrades": {k:int(v) for k,v in self.upgrades.items()},
            "last_time": time.time(), "total_earned": float(self.total_earned),
            "prestige_shards": int(self.prestige_shards), "achievements": list(self.achievements),
            "prestige_spent_levels": int(self.prestige_spent_levels),
            "discovered": list(self.discovered),
        }
        tmp = SAVE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f)
            if os.path.exists(SAVE_FILE):
                os.replace(tmp, SAVE_FILE)
            else:
                shutil.move(tmp, SAVE_FILE)
            if not silent: self._show_banner("Sauvegardé ✓")
        except Exception as e:
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            if not silent: messagebox.showerror("Erreur", f"Impossible de sauvegarder : {e}")

    def load(self):
        if not os.path.exists(SAVE_FILE): return
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f: data = json.load(f)
        except Exception as e:
            try:
                bad = SAVE_FILE + ".bak"
                if os.path.exists(bad): os.remove(bad)
                shutil.move(SAVE_FILE, bad)
                messagebox.showwarning("Sauvegarde corrompue", f"Le fichier a été renommé en {bad}.\nNouveau départ.")
            except Exception:
                messagebox.showwarning("Sauvegarde corrompue", "Impossible de lire la sauvegarde. Nouveau départ.")
            return
        try:
            self.gold = float(data.get("gold", 0.0))
            self.cpc_level = int(data.get("cpc_level", 0)); self.cpc = 1.0 + self.cpc_level * 1.0
            saved_upgrades = data.get("upgrades", {})
            if isinstance(saved_upgrades, dict):
                for name in self.upgrades.keys():
                    self.upgrades[name] = int(saved_upgrades.get(name, 0))
            self.total_earned = float(data.get("total_earned", self.gold))
            self.prestige_shards = int(data.get("prestige_shards", 0))
            known = set(self.ach_defs.keys())
            self.achievements = set([a for a in data.get("achievements", []) if a in known])
            self.prestige_spent_levels = int(data.get("prestige_spent_levels", 0))
            disc = data.get("discovered")
            if isinstance(disc, list):
                self.discovered = set([n for n in disc if n in self.upgrades])
            else:
                self.discovered = set([n for n,c in self.upgrades.items() if c>0])
            now = time.time(); last_time = float(data.get("last_time", now))
            elapsed = max(0.0, now - last_time); cap = OFFLINE_HOURS_CAP * 3600.0
            self._recalc_cps(); offline = self.cps * min(elapsed, cap)
            if offline > 0:
                self.gold += offline; self.total_earned += offline
                hrs = elapsed / 3600.0; hrs_shown = min(hrs, OFFLINE_HOURS_CAP)
                self._show_banner(f"Gains hors-ligne : +{format_num(offline)} (≈{hrs_shown:.1f}h)")
        except Exception as e:
            try:
                bad = SAVE_FILE + ".bak"
                if os.path.exists(bad): os.remove(bad)
                shutil.move(SAVE_FILE, bad)
            except Exception:
                pass
            messagebox.showwarning("Migration", f"Sauvegarde incompatible, nouveau départ.\nDétails : {e}")

    # Misc ---------------------------------------------
    def _show_banner(self, text: str, ok: bool=True, dur: int=1200):
        self.banner.configure(text=text, bg=("#b5ffb8" if ok else "#ffb3b3"), fg="#0b0f24")
        self.banner.update_idletasks()
        x = (self.root.winfo_width() - self.banner.winfo_reqwidth())//2
        self.banner.place(x=x, y=8)
        self.root.after(dur, self.banner.place_forget)

    def reset_confirm(self):
        if messagebox.askyesno("Réinitialiser", "Voulez-vous vraiment tout remettre à zéro ?"): self._reset()
    def _reset(self):
        self.gold = 0.0; self.cpc = 1.0; self.cpc_level = 0; self.total_earned = 0.0
        self.prestige_shards = 0; self.prestige_spent_levels = 0; self.achievements = set()
        self.upgrades = {name: 0 for (name, *_rest) in self.upgrade_defs}; self.discovered = set()
        try:
            if os.path.exists(SAVE_FILE): os.remove(SAVE_FILE)
        except Exception: pass
        self._show_banner("Partie réinitialisée."); self._start_decay({"gold":0.0,"cps":0.0,"cpc":1.0,"pb":0.0}, dur=3.0)
        self._sync_particles_to_shards(); self._update_upgrade_visibility()

    def on_close(self):
        self.save(silent=True); self.root.destroy()

def main():
    root = tk.Tk()
    try:
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "logo.ico")
        if os.path.exists(icon_path): root.iconbitmap(icon_path)
    except Exception: pass
    app = IdleGame(root); root.mainloop()

if __name__ == "__main__":
    main()
