"""ARÈNE : 580 comptes papier, 100 $ chacun, départ commun. 516 comptes sur barres journalières (6 écoles x variantes x 5 cryptos)
+ 64 comptes meme coins (voir meme_arena.py). Rejeu sans état depuis la date de départ : relancé chaque nuit, même résultat.
Aucun ordre réel. Les signaux sont ceux des écoles du laboratoire ; seuls leurs réglages changent d'un compte à l'autre."""
import csv, os, itertools, sys, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
ns = {"__name__": "lab_lib", "__file__": os.path.join(HERE, "lab.py")}
exec(open(os.path.join(HERE, "lab.py")).read().split("res=[];W={}")[0], ns)   # fonctions + historique, sans le rejeu 8 ans
g = lambda k: ns[k]
raw, days, arr, ema, sma, atr, ret, rstd, dret, vscale, donch, run, mdd = (g(k) for k in "raw days arr ema sma atr ret rstd dret vscale donch run mdd".split())
START = os.environ.get("ARENA_START", "2026-10-22")   # jour de départ commun
COINS = ["BTC", "ETH", "XRP", "BNB", "SOL"]

def sigA(h, l, c, start, en, ka, tr):
    e, a14 = ema(c, en), atr(h, l, c); sd = rstd(dret(c), 30); r7 = ret(c, 7)
    n = len(c); out = np.zeros(n); side = 0; hi = 0; age = 0; prev = False
    for i in range(n):
        ok = not (np.isnan(a14[i]) or np.isnan(sd[i]) or np.isnan(r7[i]))
        cond = bool(ok and c[i] > e[i] + ka * a14[i] and r7[i] > 1.5 * sd[i] * np.sqrt(7))
        if i > start:
            if side == 1:
                age += 1; hi = max(hi, c[i])
                if c[i] < e[i] or c[i] < hi - tr * a14[i] or age >= 30: side = 0
            if side == 0 and cond and not prev: side = 1; hi = c[i]; age = 0
        out[i] = 1.0 if (side == 1 and i > start) else 0.0; prev = cond
    return out
def sigB(c, en, sn, pb):
    e, s = ema(c, en), sma(c, sn); out = np.zeros(len(c))
    for i in range(pb, len(c)):
        if np.isnan(s[i]): continue
        out[i] = 1.0 if (c[i] > s[i] and c[i] > e[i] and np.any(c[i-pb:i] < e[i-pb:i])) else 0.0
    return out
def sigD(c, hs):
    R = [ret(c, k) for k in hs]; ok = ~np.any([np.isnan(r) for r in R], axis=0)
    return np.where(ok & np.all([r > 0 for r in R], axis=0), 1.0, 0.0)
def sigR(c, start, w, z0):
    m, s = sma(c, w), rstd(c, w); n = len(c); out = np.zeros(n); side = 0
    for i in range(start + 1, n):
        if np.isnan(m[i]) or s[i] <= 0: continue
        z = (c[i] - m[i]) / s[i]
        if side == 1 and z > 0: side = 0
        if side == 0 and z < -z0: side = 1
        out[i] = 1.0 if side else 0.0
    return out

def variants():
    V = []
    for en, ka, tr in itertools.product((8, 10, 14), (1.0, 1.5, 2.0), (3, 5)): V.append(("A", dict(en=en, ka=ka, tr=tr)))
    for en, sn, pb in itertools.product((8, 10, 14), (20, 30, 50), (5, 7)): V.append(("B", dict(en=en, sn=sn, pb=pb)))
    for ch, mix in itertools.product(((10, 20), (20, 30), (20, 55), (30, 60)), (1.0, 0.5)): V.append(("C", dict(ch=ch, mix=mix)))
    for hs in ((3, 7, 14), (7, 14, 28), (14, 28, 56), (7, 14)): V.append(("D", dict(hs=hs)))
    for w, z0 in itertools.product((10, 20, 30), (1.5, 2.0, 2.5)): V.append(("R", dict(w=w, z0=z0)))
    for lb, k in itertools.product((7, 14, 28), (1, 2)): V.append(("X", dict(lb=lb, k=k)))
    return V   # 63 par crypto

def accounts():
    """516 comptes journaliers : 315 de base (63 x 5, risque 2 %/jour) + 201 variantes à risque 3 %/jour (les 201 premières)."""
    base = [(s, p, k, 0.02) for k in COINS for s, p in variants()]
    extra = [(s, p, k, 0.03) for (s, p, k, _) in base[:201]]
    return base + extra

def main():
    i0 = days.index(next(d for d in days if str(np.datetime64(d, "D")) >= START)) if any(str(np.datetime64(d, "D")) >= START for d in days) else len(days) - 1
    acc = accounts(); assert len(acc) == 516
    cache = {}
    def series(k):
        if k not in cache:
            kd = [d for d in days if d in raw[k]]; a = arr(k, kd); cache[k] = (kd, a["h"], a["l"], a["c"])
        return cache[k]
    cons = {}
    def consensus(ch):
        if ch not in cons:
            s = []
            for k in ("BTC", "ETH"):
                kd, h, l, c = series(k); s.append(dict(zip(kd, donch(h, l, c, ch))))
            cons[ch] = {d: (s[0].get(d, 0) + s[1].get(d, 0)) / 2 for d in days}
        return cons[ch]
    rows, curves = [], []
    for n, (s, p, k, tv) in enumerate(acc, 1):
        kd, h, l, c = series(k); st = kd.index(next(d for d in kd if str(np.datetime64(d, "D")) >= START)) if any(str(np.datetime64(d, "D")) >= START for d in kd) else len(kd) - 1
        if s == "A": t = sigA(h, l, c, st, **p)
        elif s == "B": t = sigB(c, **p)
        elif s == "C":
            own = donch(h, l, c, p["ch"]); cs = consensus(p["ch"]); cv = np.array([cs.get(d, 0.0) for d in kd])
            t = np.maximum(p["mix"] * own + (1 - p["mix"]) * cv, 0.0)
        elif s == "D": t = sigD(c, p["hs"])
        elif s == "R": t = sigR(c, st, p["w"], p["z0"])
        else:
            M = np.array([ret(series(q)[3], p["lb"])[-len(c):] if len(series(q)[3]) >= len(c) else np.full(len(c), np.nan) for q in COINS]).T
            t = np.zeros(len(c))
            for i in range(len(c)):
                if np.isnan(M[i]).any(): continue
                order = np.argsort(-M[i])[:p["k"]]
                t[i] = 1.0 if (COINS.index(k) in order and M[i][COINS.index(k)] > 0) else 0.0
        tgt = t * vscale(c, tv)
        eq, tr = run(c[st:], tgt[st:])     # 100 $ au départ commun, frais 0,15 %
        aid = f"ARENE-{n:04d}"; fam = f"{s}-{k}"
        rows.append(dict(compte=aid, famille=fam, ecole=s, crypto=k, risque=f"{tv:.0%}", reglage=";".join(f"{a}={b}" for a, b in p.items()).replace(" ", ""),
                         depart=str(np.datetime64(kd[st], "D")), jours=len(eq) - 1, equite=f"{eq[-1]:.2f}", rendement=f"{eq[-1]/100-1:.4f}",
                         baisse_max=f"{mdd(eq):.4f}", entrees=tr, position_cible=f"{tgt[-1]:.2f}", en_position=int(tgt[-1] > 0)))
        for j, v in enumerate(eq): curves.append((aid, str(np.datetime64(kd[st + j], "D")), f"{v:.2f}"))
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    with open(os.path.join(out, "arene-comptes.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with open(os.path.join(out, "arene-courbes.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["compte", "date", "equite"]); w.writerows(curves)
    inpos = sum(r["en_position"] for r in rows)
    print(f"{len(rows)} comptes journaliers, depart {rows[0]['depart']}, en position maintenant : {inpos}")
if __name__ == "__main__": main()
