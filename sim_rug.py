#!/usr/bin/env python3
"""Simulation PAPIER d'entrees/sorties rapides sur les nouveaux tokens (avant un rug pull).
Aucun ordre, aucune cle. Lit data/seen.csv, data/enrich.csv, data/paths.csv, data/followups.csv.
Hypotheses (a corriger avec des chiffres reels) : latence 60 s, cout 2 % par cote (frais + glissement),
sortie sur stop = cloture de la bougie qui casse le stop moins 5 % de glissement supplementaire.
Dans une meme bougie, si stop et objectif sont tous deux touches, le stop est suppose touche en premier.
Usage: python3 sim_rug.py [dossier_data]  -> ecrit rapport-rug.md"""
import csv, os, sys, random, itertools, statistics as st
from datetime import datetime
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LAT, SIDE, STOP_EXTRA = 60, 0.02, 0.05
def rd(n):
    p = os.path.join(D, n)
    return list(csv.DictReader(open(p, newline=""))) if os.path.exists(p) else []
def ts(x): return datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
def f(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def trade(path, t_enter, tp, sl, hold):
    """path: liste triee de (t,o,h,l,c). Retourne (rendement net, motif) ou None si pas d'entree possible."""
    cand = [b for b in path if b[0] >= t_enter]
    if not cand: return None
    e = cand[0][1]
    if not e or e <= 0: return None
    cost_in = 1 + SIDE
    for b in cand:
        age = b[0] - cand[0][0]
        lo, hi = b[3] / e - 1, b[2] / e - 1
        if lo <= -sl:  # stop touche (prioritaire dans la meme bougie)
            px = min(b[4], e * (1 - sl)) * (1 - STOP_EXTRA)
            return px / e / cost_in * (1 - SIDE) - 1, "stop"
        if hi >= tp:
            return (1 + tp) / cost_in * (1 - SIDE) - 1, "objectif"
        if age >= hold * 60:
            return b[4] / e / cost_in * (1 - SIDE) - 1, "temps"
    b = cand[-1]
    return b[4] / e / cost_in * (1 - SIDE) - 1, "fin_donnees"

def main():
    seen = {r["address"]: r for r in rd("seen.csv")}
    enr = {}
    for r in rd("enrich.csv"):
        if r.get("rc_status") == "ok": enr[r["address"]] = r
    paths = {}
    for r in rd("paths.csv"):
        if r["t"] == "": continue
        paths.setdefault(r["address"], []).append((int(r["t"]), f(r["o"]), f(r["h"]), f(r["l"]), f(r["c"])))
    for a in paths: paths[a].sort()
    dead = {r["address"] for r in rd("followups.csv") if r["horizon"] in ("24h", "7d") and (r["liquidity_usd"] in ("", "0") or (f(r["liquidity_usd"]) or 0) < 500)}
    def safe(a):
        e = enr.get(a)
        return bool(e) and (e.get("rc_creator_rugged") in ("", "0", "False", "false", "None")) and (e.get("rc_danger_n") in ("", "0"))
    filters = {"aucun": lambda a: True, "liquidite>=3000$": lambda a: (f(seen[a].get("liquidity_usd")) or 0) >= 3000,
               "sains(RugCheck)": safe}
    rows = []
    usable = [a for a in paths if a in seen]
    for (fn, ff), delay, tp, sl, hold in itertools.product(filters.items(), (0, 5, 15), (0.25, 0.5, 1.0), (0.2, 0.35), (10, 30, 60)):
        res = []
        for a in usable:
            if not ff(a): continue
            r = trade(paths[a], ts(seen[a]["ts"]) + LAT + delay * 60, tp, sl, hold)
            if r: res.append((r[0], r[1], a))
        if len(res) < 5: continue
        v = [x[0] for x in res]
        random.seed(1)
        boots = sorted(st.mean(random.choices(v, k=len(v))) for _ in range(500))
        rows.append(dict(filtre=fn, delai=delay, tp=tp, sl=sl, hold=hold, n=len(v), moy=st.mean(v), med=st.median(v),
                         gagnants=sum(x > 0 for x in v) / len(v), pire=min(v), lo=boots[12], hi=boots[487],
                         stops=sum(x[1] == "stop" for x in res) / len(res)))
    rows.sort(key=lambda r: -r["moy"])
    n_p = len(usable)
    n_rug = 0
    for a in usable:
        p = paths[a]; pk = max(b[2] for b in p if b[2]); lo = min(b[3] for b in p if b[3] is not None)
        n_rug += (a in dead) or (lo <= 0.3 * pk)
    L = ["# Simulation d'entrees et sorties rapides (papier)", "",
         f"Pools avec trajectoire : {n_p} (sur {len(seen)} vues). Pools qui ont perdu 70 % ou plus de leur sommet, ou dont la liquidite a disparu : {n_rug} ({n_rug/max(n_p,1):.0%}).",
         f"Hypotheses : latence {LAT} s, cout {SIDE:.0%} par cote, glissement de stop {STOP_EXTRA:.0%}. Aucune n'est mesuree.", "",
         "Regle de lecture : une ligne ne compte que si n >= 30 ET que le bas de l'intervalle (95 %) est positif. Sinon c'est du bruit.", "",
         "| filtre | delai min | objectif | stop | tenue max min | n | moyenne | mediane | gagnants | pire | intervalle 95 % | stops |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows[:25]:
        flag = "" if (r["n"] >= 30 and r["lo"] > 0) else " ⚠"
        L.append(f"| {r['filtre']} | {r['delai']} | +{r['tp']:.0%} | -{r['sl']:.0%} | {r['hold']} | {r['n']} | {r['moy']:+.1%}{flag} | {r['med']:+.1%} | {r['gagnants']:.0%} | {r['pire']:+.0%} | [{r['lo']:+.1%} ; {r['hi']:+.1%}] | {r['stops']:.0%} |")
    solid = [r for r in rows if r["n"] >= 30 and r["lo"] > 0]
    L += ["", f"Lignes solides (n>=30 et borne basse > 0) : {len(solid)} sur {len(rows)} combinaisons testees. Avec autant de combinaisons, quelques-unes paraitront bonnes par hasard : meme une ligne solide doit etre confirmee sur une SEMAINE DIFFERENTE avant d'y croire."]
    open("rapport-rug.md", "w").write("\n".join(L)); print("\n".join(L[:12]))
if __name__ == "__main__": main()
