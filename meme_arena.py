#!/usr/bin/env python3
"""ARENE meme coins : 64 comptes papier de 100 $, mises de 10 $ par token. Rejeu sans etat sur data/double_book.csv + data/double_px.csv.
Reglages : ratio achats/ventes minimal {1,1.5,2,3} x objectif {1.5,2,3,5} x part vendue a l'objectif {0.5,0.9} x stop {aucun,-30 %}.
Apres l'objectif, le reste attend jusqu'a 7 jours ; il sort si le prix repasse sous l'entree ou si la pool meurt. Pas de reinvestissement ici.
Cout 2 % par cote, prix releves toutes les ~5 min. Ecrit arene-meme.csv (+ arene-meme-courbes.csv). Papier seulement."""
import csv, os, sys, itertools
from datetime import datetime
import scanner as S
COST, CAP, STAKE, EXPIRE, RUN_MAX = 0.02, 100.0, 10.0, 86400, 7 * 86400
def t(x): return S.parse(x)
def f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d
def trade(e, series, tgt, frac, stop, t0):
    """series trie [(t,px,liq)] a partir de l'entree. Retourne (t_sortie, produit_net, motif) ; produit_net = valeur recuperee pour STAKE mis (apres couts)."""
    tok = STAKE * (1 - COST) / e; bank = 0.0; left = tok; hit = None
    for ts, px, liq in series[1:]:
        if hit is None:
            if px >= tgt * e and liq >= 500:
                sold = tok * frac; bank = sold * px * (1 - COST); left = tok - sold; hit = ts
                if left <= 0: return ts, bank, "objectif"
            elif liq < 300 or px <= 0.05 * e: return ts, 0.0, "mort"
            elif stop and px <= (1 - stop) * e: return ts, tok * px * (1 - COST), "stop"
            elif ts - t0 >= EXPIRE: return ts, tok * px * (1 - COST), "expire"
        else:
            if liq < 300 or px <= 0.05 * e: return ts, bank, "mort_apres"
            if px < e or ts - hit >= RUN_MAX: return ts, bank + left * px * (1 - COST), "sortie_reste"
    ts, px, _ = series[-1]
    return None, bank + left * px * (1 - COST), "ouvert"     # evalue au dernier prix
def main(out="."):
    book = {r["address"]: r for r in S.read(os.path.join(S.DATA, "double_book.csv"))}
    px = {}
    for r in S.read(os.path.join(S.DATA, "double_px.csv")): px.setdefault(r["address"], []).append((t(r["ts"]), f(r["px"]), f(r["liq"])))
    for a in px: px[a].sort()
    pools = sorted((p for p in book.values() if p["address"] in px), key=lambda p: p["opened"])
    rows, curves = [], []
    grid = list(itertools.product((1.0, 1.5, 2.0, 3.0), (1.5, 2.0, 3.0, 5.0), (0.5, 0.9), (0.0, 0.30)))
    for n, (rmin, tgt, frac, stop) in enumerate(grid, 1):
        ev = []
        for p in pools:
            if f(p["ratio"]) < rmin: continue
            s = px[p["address"]]; e = s[0][1]
            if e <= 0: continue
            tx, val, why = trade(e, s, tgt, frac, stop, s[0][0]); ev.append((s[0][0], tx, val, why))
        cash, openp, done, ntr, wins = CAP, [], 0, 0, 0
        for t0, tx, val, why in sorted(ev):
            openp = [(a, v) for a, v in openp if not (a is not None and a <= t0) or (cash := cash + v) < 0]
            if cash < STAKE: continue
            cash -= STAKE; ntr += 1
            if tx is None: openp.append((None, val))
            else:
                openp.append((tx, val)); wins += val > STAKE
        eq = cash + sum(v for _, v in openp)
        rows.append(dict(compte=f"ARENE-M{n:02d}", ratio_min=rmin, objectif=f"x{tgt:g}", part_vendue=f"{frac:.0%}", stop=f"-{stop:.0%}" if stop else "aucun",
                         trades=ntr, gagnants=wins, equite=f"{eq:.2f}", rendement=f"{eq/CAP-1:.4f}"))
    with open(os.path.join(out, "arene-meme.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["compte"]); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} comptes meme, {len(pools)} pools avec prix, {sum(int(r['trades']) for r in rows)} trades au total")
if __name__ == "__main__": main(sys.argv[1] if len(sys.argv) > 1 else ".")
