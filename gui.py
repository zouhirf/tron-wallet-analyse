#!/usr/bin/env python3
"""GUI voor tron_links.py: wallets ingeven, analyse starten, grafiek openen."""
import json
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, ttk

import tron_links

MAP = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(MAP, "config.json")
RESULTATEN = os.path.join(MAP, "resultaten")


class QueueWriter:
    """Stuurt print() output naar het logvenster."""
    def __init__(self, q):
        self.q = q

    def write(self, tekst):
        if tekst:
            self.q.put(tekst)

    def flush(self):
        pass


def laad_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tron Wallet Analyse (USDT + TRX)")
        self.geometry("900x720")
        self.q = queue.Queue()
        self.laatste_html = None
        cfg = laad_config()

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Wallets, 1 per lijn:   Naam, Tadres   (naam mag ook weg)").pack(anchor="w")
        self.wallets = scrolledtext.ScrolledText(frm, height=8, font=("Consolas", 10))
        self.wallets.pack(fill="x")
        self.wallets.insert("1.0", "\n".join(cfg.get("laatste_wallets", [])))

        rij = ttk.Frame(frm)
        rij.pack(fill="x", pady=8)
        ttk.Label(rij, text="TronGrid API key:").pack(side="left")
        self.key = tk.StringVar(value=cfg.get("api_key", os.getenv("TRONGRID_API_KEY", "")))
        ttk.Entry(rij, textvariable=self.key, show="*", width=45).pack(side="left", padx=5)
        self.bewaar = tk.BooleanVar(value=bool(cfg.get("api_key")))
        ttk.Checkbutton(rij, text="key onthouden", variable=self.bewaar).pack(side="left")

        inst = ttk.LabelFrame(frm, text="Instellingen", padding=8)
        inst.pack(fill="x")
        self.depth = tk.IntVar(value=cfg.get("depth", 2))
        self.max_addr = tk.IntVar(value=cfg.get("max_addr", 120))
        self.top = tk.IntVar(value=cfg.get("top", 15))
        self.min_usdt = tk.DoubleVar(value=cfg.get("min_usdt", 1.0))
        self.alleen = tk.BooleanVar(value=cfg.get("alleen_verbanden", True))
        velden = [("Diepte (hops)", self.depth, 1, 4, 1),
                  ("Max adressen", self.max_addr, 10, 1000, 10),
                  ("Tegenpartijen per adres", self.top, 3, 50, 1),
                  ("Min USDT (spamfilter)", self.min_usdt, 0, 1000, 1)]
        for i, (label, var, lo, hi, stap) in enumerate(velden):
            ttk.Label(inst, text=label).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            ttk.Spinbox(inst, from_=lo, to=hi, increment=stap, textvariable=var, width=7)\
                .grid(row=0, column=i * 2 + 1, padx=(0, 14))
        ttk.Checkbutton(inst, text="Alleen verbanden tonen (overzichtelijk)", variable=self.alleen)\
            .grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))

        knoppen = ttk.Frame(frm)
        knoppen.pack(fill="x", pady=8)
        self.start_knop = ttk.Button(knoppen, text="▶ Start analyse", command=self.start)
        self.start_knop.pack(side="left")
        self.open_knop = ttk.Button(knoppen, text="Grafiek openen", command=self.open_grafiek,
                                    state="disabled")
        self.open_knop.pack(side="left", padx=6)
        ttk.Button(knoppen, text="Resultatenmap", command=self.open_map).pack(side="left")
        ttk.Button(knoppen, text="API key halen", command=lambda: webbrowser.open(
            "https://www.trongrid.io")).pack(side="right")
        self.status = ttk.Label(knoppen, text="")
        self.status.pack(side="left", padx=10)

        ttk.Label(frm, text="Log en rapport:").pack(anchor="w")
        self.log = scrolledtext.ScrolledText(frm, font=("Consolas", 9), bg="#111", fg="#ddd")
        self.log.pack(fill="both", expand=True)

        self.after(100, self.poll)

    def bewaar_config(self, seeds):
        cfg = {"laatste_wallets": seeds, "depth": self.depth.get(), "max_addr": self.max_addr.get(),
               "top": self.top.get(), "min_usdt": self.min_usdt.get(),
               "alleen_verbanden": self.alleen.get()}
        if self.bewaar.get() and self.key.get().strip():
            cfg["api_key"] = self.key.get().strip()
        try:
            with open(CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except OSError:
            pass

    def start(self):
        seeds = [l.strip() for l in self.wallets.get("1.0", "end").splitlines() if l.strip()]
        if not seeds:
            messagebox.showwarning("Geen wallets", "Geef minstens 1 Tron adres in.")
            return
        try:
            params = dict(depth=self.depth.get(), max_addr=self.max_addr.get(),
                          top=self.top.get(), min_usdt=self.min_usdt.get(),
                          alleen_verbanden=self.alleen.get())
        except tk.TclError:
            messagebox.showerror("Fout", "Controleer de instellingen (alleen getallen).")
            return
        self.bewaar_config(seeds)
        os.makedirs(RESULTATEN, exist_ok=True)
        naam = tron_links.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(RESULTATEN, f"graaf_{naam}.html")
        rapport = os.path.join(RESULTATEN, f"rapport_{naam}.txt")

        self.log.delete("1.0", "end")
        self.start_knop.config(state="disabled")
        self.open_knop.config(state="disabled")
        self.status.config(text="bezig...")
        key = self.key.get().strip() or None

        def werk():
            oud = sys.stdout
            sys.stdout = QueueWriter(self.q)
            try:
                html, _ = tron_links.run(seeds, api_key=key, out=out, rapport_pad=rapport, **params)
                self.q.put(("KLAAR", html))
            except Exception as e:  # noqa: BLE001
                self.q.put(("FOUT", str(e)))
            finally:
                sys.stdout = oud

        threading.Thread(target=werk, daemon=True).start()

    def poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple):
                    soort, waarde = item
                    self.start_knop.config(state="normal")
                    if soort == "KLAAR":
                        self.laatste_html = waarde
                        self.open_knop.config(state="normal")
                        self.status.config(text="klaar")
                        self.open_grafiek()
                    else:
                        self.status.config(text="fout")
                        messagebox.showerror("Fout", waarde)
                else:
                    self.log.insert("end", item)
                    self.log.see("end")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def open_grafiek(self):
        if self.laatste_html:
            webbrowser.open("file:///" + self.laatste_html.replace("\\", "/"))

    def open_map(self):
        os.makedirs(RESULTATEN, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(RESULTATEN)  # noqa: S606
        else:
            webbrowser.open("file://" + RESULTATEN)


if __name__ == "__main__":
    App().mainloop()
