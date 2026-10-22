"""Comité de 4 agents (papier seulement). Tout est écrit d'avance, rien n'est ajusté après coup.
Chercheur : positions actuelles des écoles A/C/D (+B, X) par crypto, depuis l'historique à jour.
Sceptique : essaie de prouver que chaque pari est mauvais avec des seuils fixes.
Chef : tranche (GO papier / ATTENDRE / NON).
Trader : seul à écrire dans le journal, en papier. Aucun ordre réel n'est possible ici."""
import io, contextlib, numpy as np, datetime as dt
with contextlib.redirect_stdout(io.StringIO()):
    import lab
W, res = lab.W, {r["acc"]: r for r in lab.res}
bench = res["BENCH-BTC-50%vol"]
SEUILS = dict(annees_pos_min=5, dd_max=-0.25, annee_recente_min=-0.12, trades_an_max=25, meme_crypto_max=3)
today = dt.datetime.fromtimestamp(lab.days[-1]*86400, dt.timezone.utc).date()
fresh = (dt.datetime.now(dt.timezone.utc).date() - today).days <= 2
def annees(a):
    eq, y = W[a]["eq"], W[a]["years"]; out = {}
    for Y in range(2019, 2027):
        m = np.where(y == Y)[0]
        if len(m) > 20: out[Y] = eq[m[-1]]/eq[max(m[0]-1, 0)]-1
    return out
rows = []
for a in W:
    if a.startswith("BENCH") or a[0] in "R": continue
    pos = float(W[a]["tgt"][-1]); k = a.split("-")[1]
    obj = []
    ay = annees(a); npos = sum(v > 0 for v in ay.values())
    if npos < SEUILS["annees_pos_min"]: obj.append(f"seulement {npos}/{len(ay)} années positives")
    if res[a]["mdd"] < SEUILS["dd_max"]: obj.append(f"baisse max {res[a]['mdd']:.0%} sous {SEUILS['dd_max']:.0%}")
    rec = min(ay.get(2025, 0), ay.get(2026, 0))
    if rec < SEUILS["annee_recente_min"]: obj.append(f"mauvaise année récente ({rec:+.0%})")
    if k == "BTC" and res[a]["total"] < bench["total"] and res[a]["mdd"] <= bench["mdd"]: obj.append("ne bat pas BTC 50 % vol")
    yrs = max(len(ay), 1)
    if res[a]["trades"]/yrs > SEUILS["trades_an_max"]: obj.append(f"{res[a]['trades']/yrs:.0f} entrées/an, frais trop lourds")
    if k == "BNB": obj.append("BNB : pas de prix sur Crypto.com, forward impossible aujourd'hui")
    if not fresh: obj.append("données périmées")
    rows.append(dict(acc=a, coin=k, pos=pos, obj=obj, npos=npos, n=len(ay), mdd=res[a]["mdd"]))
long_by_coin = {}
for r in rows:
    if r["pos"] > 0: long_by_coin.setdefault(r["coin"], []).append(r)
for k, v in long_by_coin.items():
    if len(v) > SEUILS["meme_crypto_max"]:
        for r in v: r["obj"].append(f"{len(v)} écoles longues sur {k} : un seul pari répété")
L = [f"# Comité du {today} (données jusqu'au {today})", "", "Papier seulement. Seuils écrits d'avance : " + ", ".join(f"{k}={v}" for k, v in SEUILS.items()), ""]
L += ["| Compte | Position | Objections du Sceptique | Décision du Chef |", "|---|---|---|---|"]
go = 0
for r in sorted(rows, key=lambda r: (-(r["pos"] > 0), len(r["obj"]), r["acc"])):
    if r["pos"] > 0:
        d = "GO papier" if len(r["obj"]) == 0 else ("GO papier, taille réduite" if len(r["obj"]) == 1 else "NON")
    else: d = "Attendre (à plat)"
    go += d.startswith("GO")
    L.append(f"| {r['acc']} | {'long %.2f' % r['pos'] if r['pos'] > 0 else 'plat'} | {'; '.join(r['obj']) or '—'} | {d} |")
L += ["", f"Le Trader ne reçoit que les lignes GO papier ({go}). Les ordres réels restent à toi, à la main, après les 7 portes."]
open("comite-du-jour.md", "w").write("\n".join(L)); print("\n".join(L))
