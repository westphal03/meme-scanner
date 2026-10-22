#!/usr/bin/env python3
"""Strategie PAPIER « doubler puis sortir » sur les nouveaux tokens Solana. Aucun ordre, aucune cle.

Regle (celle de l'utilisateur) :
 1. Achat de 100 $ (papier) quand les achats 1 h sont superieurs aux ventes 1 h (ratio > MIN_RATIO), liquidite assez
    grosse pour que 100 $ ne bouge pas le prix.
 2. Des que le prix double (x2 du prix d'entree) : on vend 90 % des jetons (on retire l'argent), 10 % restent en attente.
 3. Verification chaque jour (24 h apres la vente, puis toutes les 24 h) : si le prix est toujours au moins x2 l'entree
    et la liquidite saine, on REINVESTIT une partie (REINV_FRAC) du profit encaisse. Sinon on ferme le reste.
 4. Pas doubles apres 24 h : on ferme au prix du moment. Pool morte (liquidite < 300 $ ou prix <= 5 % de l'entree) : perte.

Hypotheses non mesurees : cout 2 % par cote (frais + glissement), prix observe toutes les ~5 min seulement
(un doublement qui retombe entre deux releves est manque). Chaque trade est enregistre dans data/double_book.csv.

Usage : python3 double.py           (un cycle : ouvre, suit, ferme, ecrit rapport-double.md)
        python3 double.py retro     (rejeu sur les bougies minute deja collectees, pas d'ecriture du carnet)"""
import csv, os, sys, time, statistics as st
from datetime import datetime, timezone
import scanner as S

STAKE, COST = 100.0, 0.02
MIN_RATIO, MIN_BUYS, MIN_LIQ = 1.0, 5, 2000.0
TARGET, SELL_FRAC, REINV_FRAC = 2.0, 0.9, 0.5
ENTRY_WINDOW = 900            # on n'achete que les pools vues il y a moins de 15 min
EXPIRE = 86400                # pas double en 24 h : on ferme
RUNNER_MAX = 7 * 86400
POLLS_PER_RUN, MAX_OPEN = 20, 60
BOOK = os.path.join(S.DATA, "double_book.csv")
REPORT = os.path.join(S.DATA, "rapport-double.md")
COLS = ["address", "name", "opened", "ratio", "buys", "sells", "liq", "entry_px", "tokens", "state", "t2x", "banked",
        "runner_tokens", "tokens2", "cost2", "last_ts", "last_px", "last_liq", "next_check", "closed", "reason",
        "pnl_usd", "polls", "max_px"]


def now_ts():
    return datetime.now(timezone.utc).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def load():
    return {r["address"]: r for r in S.read(BOOK)}


def save(book):
    with open(BOOK, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(book.values(), key=lambda r: r["opened"]):
            w.writerow({c: r.get(c, "") for c in COLS})


def value_now(p, px):
    """Valeur de sortie des jetons restants + gain deja encaisse, net des couts de vente."""
    held = f(p["runner_tokens"]) + f(p["tokens2"]) if p["state"] == "runner" else f(p["tokens"]) if p["state"] == "open" else 0.0
    return f(p["banked"]) + held * px * (1 - COST)


def pnl(p, px):
    return value_now(p, px) - STAKE - f(p["cost2"])


def close(p, t, px, reason):
    p.update(state="closed", closed=iso(t), reason=reason)
    p["pnl_usd"] = f"{pnl(p, px):.2f}"
    p["runner_tokens"] = p["tokens2"] = "0"
    p["tokens"] = "0" if p.get("t2x") else p["tokens"]


def open_new(book, t):
    opened = 0
    n_open = sum(1 for p in book.values() if p["state"] != "closed")
    for r in reversed(S.read(S.SEEN)):
        a = r["address"]
        if a in book or n_open >= MAX_OPEN:
            continue
        t0 = S.parse(r["ts"])
        if t - t0 > ENTRY_WINDOW:
            break
        b, s, px, liq = f(r["buys_h1"]), f(r["sells_h1"]), f(r["price_usd"]), f(r["liquidity_usd"])
        if px <= 0 or b < MIN_BUYS or liq < MIN_LIQ or b <= MIN_RATIO * max(s, 1e-9):
            continue
        tokens = STAKE * (1 - COST) / px
        book[a] = dict(address=a, name=r["name"], opened=r["ts"], ratio=f"{b / max(s, 1):.2f}", buys=r["buys_h1"],
                       sells=r["sells_h1"], liq=f"{liq:.0f}", entry_px=repr(px), tokens=repr(tokens), state="open",
                       t2x="", banked="0", runner_tokens="0", tokens2="0", cost2="0", last_ts=r["ts"], last_px=repr(px),
                       last_liq=f"{liq:.0f}", next_check="", closed="", reason="", pnl_usd="", polls="0", max_px=repr(px))
        opened += 1
        n_open += 1
    return opened


def poll(book, t):
    todo = sorted((p for p in book.values() if p["state"] != "closed"), key=lambda p: S.parse(p["last_ts"]))[:POLLS_PER_RUN]
    for p in todo:
        d = S.get(f"{S.BASE}/pools/{p['address']}")
        time.sleep(2.2)
        if not d or not d.get("data"):
            if t - S.parse(p["opened"]) > 3600 and f(p["polls"]) > 0 and f(p["last_liq"]) < 1000:
                close(p, t, 0.0, "pool_disparue")
            continue
        r = S.row(d["data"], iso(t))
        px, liq = f(r["price_usd"]), f(r["liquidity_usd"])
        if px <= 0:
            continue
        p.update(last_ts=iso(t), last_px=repr(px), last_liq=f"{liq:.0f}", polls=str(int(f(p["polls"])) + 1))
        p["max_px"] = repr(max(px, f(p["max_px"])))
        e = f(p["entry_px"])
        age = t - S.parse(p["opened"])
        if p["state"] == "open":
            if px >= TARGET * e and liq >= 500:           # doublé : on retire l'argent
                sold = f(p["tokens"]) * SELL_FRAC
                p.update(state="runner", t2x=iso(t), banked=f"{sold * px * (1 - COST):.4f}",
                         runner_tokens=repr(f(p["tokens"]) - sold), next_check=iso(t + 86400))
            elif liq < 300 or px <= 0.05 * e:
                close(p, t, px, "mort")
            elif age >= EXPIRE:
                close(p, t, px, "expire_24h")
        else:
            since = t - S.parse(p["t2x"])
            if liq < 300 or px <= 0.05 * e:
                close(p, t, px, "mort_apres_x2")
            elif t >= S.parse(p["next_check"]):
                if px >= TARGET * e and liq >= 1000 and f(p["tokens2"]) == 0:   # ça marche encore : on réinvestit une partie
                    add = max(0.0, (f(p["banked"]) - STAKE)) * REINV_FRAC
                    if add > 0:
                        p["cost2"] = f"{add:.4f}"
                        p["tokens2"] = repr(add * (1 - COST) / px)
                    p["next_check"] = iso(t + 86400)
                elif px < TARGET * e or liq < 1000:
                    close(p, t, px, "sortie_verif_jour")
                else:
                    p["next_check"] = iso(t + 86400)
            if p["state"] == "runner" and since >= RUNNER_MAX:
                close(p, t, px, "fin_7j")


def summarize(book):
    pos = list(book.values())
    L = ["# Strategie « doubler puis sortir » : papier, en continu", "",
         "Règle : achat de 100 $ papier quand les achats 1 h dépassent les ventes 1 h (liquidité au moins 2 000 $, au moins 5 achats). "
         "À x2 on vend 90 %, 10 % reste en attente, vérifié chaque jour, réinvestissement d'une partie du profit si le prix tient encore x2. "
         "Coûts supposés 2 % par côté, prix relevé toutes les 5 minutes (un x2 qui retombe entre deux relevés est manqué).", ""]
    if not pos:
        return "\n".join(L + ["Aucune position pour l'instant."])
    def px_last(p): return f(p["last_px"])
    def pn(p): return f(p["pnl_usd"]) if p["state"] == "closed" else pnl(p, px_last(p))
    n = len(pos)
    x2 = [p for p in pos if p["t2x"]]
    tot = sum(pn(p) for p in pos)
    L += [f"Positions : {n} (ouvertes {sum(p['state']=='open' for p in pos)}, en attente 10 % {sum(p['state']=='runner' for p in pos)}, fermées {sum(p['state']=='closed' for p in pos)}).",
          f"Ont doublé : {len(x2)} sur {n} ({len(x2)/n:.0%}).",
          f"Gain/perte papier total : {tot:+.0f} $ sur {n*STAKE:.0f} $ misés ({tot/(n*STAKE):+.1%} par position). Positions ouvertes évaluées au dernier prix.", ""]
    L += ["| ratio achats/ventes | positions | ont doublé | gain moyen par 100 $ | pire |", "|---|---|---|---|---|"]
    for lo, hi in ((1, 1.5), (1.5, 2), (2, 3), (3, 1e9)):
        g = [p for p in pos if lo <= f(p["ratio"]) < hi]
        if g:
            L.append(f"| {lo}–{'+' if hi>1e8 else hi} | {len(g)} | {sum(bool(p['t2x']) for p in g)} ({sum(bool(p['t2x']) for p in g)/len(g):.0%}) | {st.mean(pn(p) for p in g):+.1f} $ | {min(pn(p) for p in g):+.0f} $ |")
    L += ["", "Règle de lecture : moins de 30 positions fermées, c'est du bruit. Une moyenne positive portée par un seul gros x10 n'est pas une preuve."]
    return "\n".join(L)


def retro():
    """Rejeu sur les bougies minute deja collectees (2 premieres heures), meme regle d'entree, x2 = sortie."""
    seen = {r["address"]: r for r in S.read(S.SEEN)}
    paths = {}
    for r in S.read(S.PATHS):
        if r["t"]:
            paths.setdefault(r["address"], []).append((int(r["t"]), f(r["o"]), f(r["h"]), f(r["l"]), f(r["c"])))
    rows = []
    for a, pth in paths.items():
        s = seen.get(a)
        if not s:
            continue
        b, se, liq = f(s["buys_h1"]), f(s["sells_h1"]), f(s["liquidity_usd"])
        if b < MIN_BUYS or liq < MIN_LIQ or b <= MIN_RATIO * max(se, 1e-9):
            continue
        pth.sort()
        t0 = S.parse(s["ts"]) + 60
        c = [x for x in pth if x[0] >= t0 and x[1] > 0]
        if len(c) < 3:
            continue
        e = c[0][1]
        hit = next((x for x in c if x[2] >= TARGET * e), None)
        last = c[-1][4]
        if hit:
            banked = STAKE * (1 - COST) / e * SELL_FRAC * TARGET * e * (1 - COST)
            left = STAKE * (1 - COST) / e * (1 - SELL_FRAC) * last * (1 - COST)
            res = banked + left - STAKE
        else:
            res = STAKE * (1 - COST) / e * last * (1 - COST) - STAKE
        rows.append((a, s["name"], b / max(se, 1), bool(hit), res, len(c)))
    return rows


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "retro":
        R = retro()
        if not R:
            print("rien a rejouer")
            sys.exit()
        print(f"{len(R)} pools, {sum(r[3] for r in R)} ont double, moyenne {st.mean(r[4] for r in R):+.1f} $ par 100 $, "
              f"somme {sum(r[4] for r in R):+.0f} $, pire {min(r[4] for r in R):+.0f} $, meilleur {max(r[4] for r in R):+.0f} $")
        for r in sorted(R, key=lambda r: -r[4])[:8]:
            print(f"  {r[1][:22]:22} ratio {r[2]:.1f} x2={'oui' if r[3] else 'non'} {r[4]:+.0f} $ ({r[5]} bougies)")
        sys.exit()
    t = now_ts()
    book = load()
    k = open_new(book, t)
    poll(book, t)
    save(book)
    txt = summarize(book)
    open(REPORT, "w").write(txt)
    print(f"{iso(t)} double: nouvelles={k} total={len(book)}")
