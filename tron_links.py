#!/usr/bin/env python3
"""
tron_links.py : verbanden tussen Tron wallets in kaart brengen (USDT TRC20 + TRX)

Installeren:
    pip install requests networkx pyvis

Gebruik:
    python tron_links.py TAdres1 TAdres2 TAdres3
    python tron_links.py --file wallets.txt --depth 2

Gratis API key (sterk aangeraden, veel sneller): maak een account op https://www.trongrid.io
    PowerShell:  $env:TRONGRID_API_KEY="jouw-key"
    of:          --api-key jouw-key

Resultaat:
    tron_graaf.html  -> interactieve grafiek (openen in je browser)
    tron_rapport.txt -> welke wallets verbonden zijn en via welke route
"""
import argparse
import hashlib
import html as htmlmod
import re
import itertools
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import networkx as nx
import requests
from pyvis.network import Network

API = "https://api.trongrid.io"
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# ---------- hulpfuncties ----------

def hex_to_b58(h: str) -> str:
    """Tron hex adres (41...) omzetten naar T... adres."""
    if h.startswith("T"):
        return h
    raw = bytes.fromhex(h)
    raw += hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def kort(a: str) -> str:
    return f"{a[:5]}…{a[-4:]}"


def datum(ts_ms) -> str:
    if not ts_ms:
        return "?"
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------- TronGrid API ----------

class Tron:
    def __init__(self, api_key: str | None, max_pages: int):
        self.s = requests.Session()
        if api_key:
            self.s.headers["TRON-PRO-API-KEY"] = api_key
        self.max_pages = max_pages
        self.delay = 0.25 if api_key else 1.1

    def _get(self, path, params):
        for poging in range(6):
            try:
                r = self.s.get(API + path, params=params, timeout=30)
            except requests.RequestException:
                time.sleep(2 * (poging + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (poging + 1))
                continue
            r.raise_for_status()
            time.sleep(self.delay)
            return r.json()
        raise RuntimeError(f"API blijft weigeren voor {path}")

    def _paged(self, path, params, max_pages=None):
        params = dict(params, limit=200)
        items = []
        for _ in range(max_pages or self.max_pages):
            j = self._get(path, params)
            items += j.get("data", [])
            fp = j.get("meta", {}).get("fingerprint")
            if not fp:
                return items, False
            params["fingerprint"] = fp
        return items, True  # afgekapt: er zijn meer transacties dan opgehaald

    @staticmethod
    def _trx_transfer(t):
        try:
            c = t["raw_data"]["contract"][0]
            if c["type"] != "TransferContract":
                return None
            v = c["parameter"]["value"]
            return (hex_to_b58(v["owner_address"]), hex_to_b58(v["to_address"]),
                    v["amount"] / 1e6, t.get("block_timestamp", 0), t.get("txID"))
        except (KeyError, IndexError, ValueError, TypeError):
            return None

    def transfers(self, addr):
        """Lijst van (van, naar, munt, bedrag, timestamp) + of de lijst afgekapt is."""
        out = []
        usdt, t1 = self._paged(f"/v1/accounts/{addr}/transactions/trc20",
                               {"contract_address": USDT_CONTRACT, "only_confirmed": "true"})
        for t in usdt:
            try:
                dec = int((t.get("token_info") or {}).get("decimals", 6))
                out.append((t["from"], t["to"], "USDT", int(t["value"]) / 10 ** dec,
                            t.get("block_timestamp", 0), t.get("transaction_id")))
            except (KeyError, ValueError, TypeError):
                continue
        trx, t2 = self._paged(f"/v1/accounts/{addr}/transactions",
                              {"only_confirmed": "true", "search_internal": "false"})
        for t in trx:
            x = self._trx_transfer(t)
            if x:
                out.append((x[0], x[1], "TRX", x[2], x[3], x[4]))
        return out, (t1 or t2)

    def eerste_funder(self, addr):
        """Wie stuurde als eerste TRX naar dit adres (activeert de wallet)."""
        items, _ = self._paged(f"/v1/accounts/{addr}/transactions",
                               {"only_confirmed": "true", "order_by": "block_timestamp,asc"},
                               max_pages=1)
        for t in items:
            x = self._trx_transfer(t)
            if x and x[1] == addr and x[0] != addr:
                return x[0], x[2], x[3]
        return None


# ---------- crawlen ----------

def crawl(api, seeds, depth, top_n, hub_limit, max_addr, min_usdt, min_trx):
    edges = defaultdict(lambda: {"USDT": 0.0, "TRX": 0.0, "n": 0, "first": None})
    depth_of = {s: 0 for s in seeds}
    hubs = set()
    queue = list(seeds)
    fetched = set()
    gezien = set()  # transactie ID's, zodat niets dubbel telt

    while queue and len(fetched) < max_addr:
        addr = queue.pop(0)
        if addr in fetched:
            continue
        fetched.add(addr)
        print(f"[{len(fetched)}/{max_addr}] hop {depth_of[addr]}  {addr}")
        try:
            txs, afgekapt = api.transfers(addr)
        except Exception as e:  # noqa: BLE001
            print(f"    fout, overgeslagen: {e}")
            continue

        tegenpartij = defaultdict(int)
        for frm, to, munt, bedrag, ts, txid in txs:
            tegen = to if frm == addr else frm
            if frm == to or bedrag < (min_usdt if munt == "USDT" else min_trx):
                continue  # ook stofjes / address poisoning eruit filteren
            tegenpartij[tegen] += 1
            sleutel = (txid, munt, frm, to)
            if txid and sleutel in gezien:
                continue
            gezien.add(sleutel)
            e = edges[(frm, to)]
            e[munt] += bedrag
            e["n"] += 1
            e["first"] = ts if e["first"] is None else min(e["first"], ts)

        is_hub = afgekapt or len(tegenpartij) > hub_limit
        if is_hub and addr not in seeds:
            hubs.add(addr)
            print(f"    druk adres ({len(tegenpartij)} tegenpartijen), waarschijnlijk exchange/dienst: niet verder gevolgd")
            continue
        if is_hub:
            print(f"    let op: seed is zelf een druk adres")

        if depth_of[addr] < depth:
            beste = sorted(tegenpartij, key=tegenpartij.get, reverse=True)[:top_n]
            for o in beste:
                if o not in depth_of:
                    depth_of[o] = depth_of[addr] + 1
                    queue.append(o)

    G = nx.DiGraph()
    for (a, b), d in edges.items():
        G.add_edge(a, b, **d)
    G.add_nodes_from(seeds)
    return G, hubs


# ---------- wallets + namen inlezen ----------

def parse_wallets(lines):
    """Lijnen zoals 'Jan, TXXX' of 'TXXX Jan' of alleen 'TXXX' -> (adressen, {adres: naam})."""
    seeds, namen = [], {}
    for l in lines:
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        delen = [d for d in re.split(r"[,;\t ]+", l) if d]
        adres = next((d for d in delen if d.startswith("T") and len(d) == 34), None)
        if not adres:
            raise ValueError(f"Geen geldig Tron adres in lijn: {l}")
        naam = " ".join(d for d in delen if d != adres).strip()
        seeds.append(adres)
        if naam:
            namen[adres] = naam
    return list(dict.fromkeys(seeds)), namen


# ---------- analyse ----------

def bedrag_tekst(d):
    delen = []
    if d["USDT"]:
        delen.append(f"{d['USDT']:,.0f} USDT")
    if d["TRX"]:
        delen.append(f"{d['TRX']:,.0f} TRX")
    return " + ".join(delen) or "0"


def analyse(G, seeds, hubs, funders, namen):
    def lab(x):
        return f"{namen[x]} ({kort(x)})" if x in namen else x

    U = G.to_undirected()
    zonder_hubs = U.copy()
    zonder_hubs.remove_nodes_from(hubs - set(seeds))
    samenvatting, details, pad_nodes, pad_edges = [], [], set(), set()

    per_funder = defaultdict(list)
    for s, f in funders.items():
        if f:
            per_funder[f[0]].append(s)
    for f, ss in per_funder.items():
        if len(ss) > 1:
            zwak = " (exchange?, zwak)" if f in hubs else ""
            samenvatting.append(f"GEDEELDE FUNDER{zwak}: {', '.join(namen.get(x, kort(x)) for x in ss)} "
                                f"kregen eerste TRX van {kort(f)}")

    for a, b in itertools.combinations(seeds, 2):
        na, nb = namen.get(a, kort(a)), namen.get(b, kort(b))
        details.append(f"\n{lab(a)}  <->  {lab(b)}")
        pad, soort = None, None
        for graaf, label in ((zonder_hubs, "STERK"), (U, "ZWAK (via exchange)")):
            if a in graaf and b in graaf:
                try:
                    pad, soort = nx.shortest_path(graaf, a, b), label
                    break
                except nx.NetworkXNoPath:
                    pass
        if pad:
            hops = len(pad) - 1
            samenvatting.append(f"{soort}: {na} <-> {nb} via {hops} hop{'s' if hops != 1 else ''}")
            details.append(f"  {soort}: {hops} hop(s)")
            for x, y in zip(pad, pad[1:]):
                d = G.get_edge_data(x, y) or G.get_edge_data(y, x)
                v, n = (x, y) if G.has_edge(x, y) else (y, x)
                details.append(f"    {lab(v)} -> {lab(n)}   {bedrag_tekst(d)} | {d['n']} tx | vanaf {datum(d['first'])}")
                pad_edges.add(frozenset((x, y)))
            pad_nodes.update(pad)
        else:
            samenvatting.append(f"GEEN: {na} <-> {nb}")
            details.append("  geen verband gevonden binnen de gekozen diepte")
        gemeen = (set(U[a]) & set(U[b])) if a in U and b in U else set()
        if gemeen:
            details.append(f"  gemeenschappelijke tegenpartijen: {len(gemeen)}")
            for g in list(gemeen)[:10]:
                details.append(f"    {g}{'  (druk adres)' if g in hubs else ''}")

    details.append("\n=== FUNDERS (eerste TRX) ===")
    for s, f in funders.items():
        details.append(f"{lab(s)}: van {f[0]} ({f[1]} TRX op {datum(f[2])})" if f
                       else f"{lab(s)}: niet gevonden")
    return samenvatting, details, pad_nodes, pad_edges


# ---------- visualisatie ----------

def teken(G, seeds, hubs, funders, pad_nodes, pad_edges, out, namen, samenvatting,
          alleen_verbanden=True):
    U = G.to_undirected()
    funder_set = {f[0] for f in funders.values() if f}
    if alleen_verbanden:
        houden = set(seeds) | pad_nodes | funder_set
        for n in U.nodes:
            if n not in houden and sum(1 for s in seeds if s in U and U.has_edge(n, s)) >= 2:
                houden.add(n)  # tegenpartij die met 2+ van jouw wallets handelt
        H = G.subgraph(houden)
    else:
        H = G

    net = Network(height="100vh", width="100%", directed=True, bgcolor="#111", font_color="#eee")
    net.barnes_hut(gravity=-9000, spring_length=220, central_gravity=0.2)

    for n in H.nodes:
        link = f"https://tronscan.org/#/address/{n}"
        if n in seeds:
            net.add_node(n, label=namen.get(n, kort(n)), shape="box", color="#e63946",
                         font={"size": 22, "color": "#fff", "face": "arial", "bold": True},
                         title=f"{namen.get(n, '')}\n{n}\n{link}", mass=3)
        elif n in hubs:
            net.add_node(n, label=f"Exchange?\n{kort(n)}", shape="square", color="#666", size=16,
                         title=f"{n}\nDruk adres, waarschijnlijk exchange/dienst\n{link}")
        elif n in funder_set:
            net.add_node(n, label=f"Funder\n{kort(n)}", shape="diamond", color="#c77dff", size=22,
                         title=f"{n}\nStuurde eerste TRX naar jouw wallet(s)\n{link}")
        elif n in pad_nodes:
            net.add_node(n, label=kort(n), color="#ffa500", size=16, title=f"{n}\nOp verbindingspad\n{link}")
        else:
            net.add_node(n, label=kort(n) if alleen_verbanden else "", color="#4da6ff", size=9,
                         title=f"{n}\n{link}")

    for a, b, d in H.edges(data=True):
        op_pad = frozenset((a, b)) in pad_edges
        kleur = "#ffa500" if op_pad else ("#2ecc71" if d["USDT"] > 0 else "#3498db")
        breedte = 5 if op_pad else 1 + math.log10(1 + d["USDT"] + d["TRX"] / 5)
        toon_label = op_pad or alleen_verbanden
        net.add_edge(a, b, color=kleur, width=breedte,
                     label=bedrag_tekst(d) if toon_label else None,
                     font={"color": "#ddd", "size": 12, "strokeWidth": 3, "strokeColor": "#111"},
                     title=f"USDT {d['USDT']:,.2f}\nTRX {d['TRX']:,.2f}\n{d['n']} transacties\nvanaf {datum(d['first'])}")

    net.save_graph(out)

    # legende + samenvatting + grafiek stilzetten na het schikken
    items = "".join(f"<li>{htmlmod.escape(r)}</li>" for r in samenvatting) or "<li>geen paren</li>"
    paneel = f"""
<div style="position:fixed;top:10px;left:10px;max-width:420px;max-height:90vh;overflow:auto;
background:rgba(20,20,20,.92);color:#eee;font:13px arial;padding:12px 14px;border:1px solid #444;border-radius:8px;z-index:10">
<b style="font-size:15px">Samenvatting</b><ul style="padding-left:18px;margin:6px 0 10px">{items}</ul>
<b>Legende</b><div style="line-height:1.8">
<span style="background:#e63946;padding:1px 6px">naam</span> jouw wallet &nbsp;
<span style="color:#c77dff">&#9670;</span> funder (eerste TRX) &nbsp;
<span style="color:#ffa500">&#9679;</span> verbindingspad<br>
<span style="color:#888">&#9632;</span> druk adres / exchange &nbsp;
<span style="color:#2ecc71">&#9473;</span> USDT &nbsp; <span style="color:#3498db">&#9473;</span> alleen TRX &nbsp;
<span style="color:#ffa500">&#9473;</span> pad</div>
<div style="color:#999;margin-top:6px">Hover = details, sleep nodes om te ordenen</div></div>
<script>
if (typeof network !== "undefined") {{
  network.once("stabilizationIterationsDone", function () {{ network.setOptions({{physics: false}}); }});
  setTimeout(function () {{ network.setOptions({{physics: false}}); }}, 8000);
}}
</script>
"""
    with open(out, encoding="utf-8") as f:
        h = f.read()
    h = h.replace("</body>", paneel + "</body>", 1)
    with open(out, "w", encoding="utf-8") as f:
        f.write(h)


# ---------- main ----------

def run(lines, api_key=None, depth=2, top=15, hub_limit=60, max_addr=120, pages=3,
        min_usdt=1.0, min_trx=0.5, out="tron_graaf.html", rapport_pad="tron_rapport.txt",
        alleen_verbanden=True):
    """lines: lijnen met 'naam, adres' of alleen adres. Geeft (html pad, rapport tekst)."""
    seeds, namen = parse_wallets(lines)
    if not seeds:
        raise ValueError("Geef minstens 1 adres op.")
    if not api_key:
        print("Geen API key: werkt, maar trager. Gratis key via trongrid.io\n")

    api = Tron(api_key, pages)
    print("Funders van je wallets zoeken...")
    funders = {}
    for s in seeds:
        try:
            funders[s] = api.eerste_funder(s)
        except Exception as e:  # noqa: BLE001
            print(f"  {namen.get(s, s)}: fout {e}")
            funders[s] = None

    print("\nTransacties ophalen...")
    G, hubs = crawl(api, seeds, depth, top, hub_limit, max_addr, min_usdt, min_trx)
    for s, f in funders.items():
        if f and not G.has_edge(f[0], s):
            G.add_edge(f[0], s, USDT=0.0, TRX=f[1], n=1, first=f[2])

    samenvatting, details, pad_nodes, pad_edges = analyse(G, seeds, hubs, funders, namen)
    rapport = "=== SAMENVATTING ===\n" + "\n".join(samenvatting) + "\n\n=== DETAILS ===" + "\n".join(details)
    print("\n" + rapport)
    with open(rapport_pad, "w", encoding="utf-8") as f:
        f.write(rapport)
    teken(G, seeds, hubs, funders, pad_nodes, pad_edges, out, namen, samenvatting, alleen_verbanden)
    print(f"\nKlaar: {G.number_of_nodes()} adressen, {G.number_of_edges()} verbindingen")
    return os.path.abspath(out), rapport


def main():
    p = argparse.ArgumentParser(description="Verbanden tussen Tron wallets (USDT + TRX) visualiseren")
    p.add_argument("wallets", nargs="*", help="Tron adressen (T...)")
    p.add_argument("--file", help="tekstbestand: per lijn 'naam, adres' of alleen adres")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--hub-limit", type=int, default=60)
    p.add_argument("--max-addr", type=int, default=120)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--min-usdt", type=float, default=1.0)
    p.add_argument("--min-trx", type=float, default=0.5)
    p.add_argument("--alles", action="store_true", help="alle tegenpartijen tonen, niet alleen verbanden")
    p.add_argument("--api-key", default=os.getenv("TRONGRID_API_KEY"))
    p.add_argument("--out", default="tron_graaf.html")
    a = p.parse_args()
    lines = list(a.wallets)
    if a.file:
        with open(a.file, encoding="utf-8") as f:
            lines += f.readlines()
    try:
        html, _ = run(lines, a.api_key, a.depth, a.top, a.hub_limit, a.max_addr, a.pages,
                      a.min_usdt, a.min_trx, a.out, alleen_verbanden=not a.alles)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Open {html} in je browser.")


if __name__ == "__main__":
    main()
