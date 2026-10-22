#!/usr/bin/env python3
"""Scanner de nouveaux tokens Solana (GeckoTerminal) + enrichissement securite (RugCheck, GoPlus).
OBSERVATION SEULEMENT : aucun ordre, aucune cle, aucun portefeuille.

Chaque execution :
 1. lit les nouvelles pools et enregistre chaque pool jamais vue dans data/seen.csv (releve initial, avec l'adresse du token)
 2. enrichit les tokens neufs (RugCheck + GoPlus) dans data/enrich.csv ; jusqu'a 3 essais si l'analyse n'est pas prete
 3. pour les pools vues il y a ~1 h, ~24 h et ~7 jours, refait un releve dans data/followups.csv
Le but : mesurer quels signaux de depart precedent les tokens qui tiennent. Rien n'est un conseil d'achat.

NOTE : les noms de champs de GoPlus (Solana) n'ont pas ete verifies dans la doc ; data/enrich_raw.jsonl garde des
echantillons bruts des premieres reponses pour verifier et corriger l'extraction.
"""
import csv, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = "https://api.geckoterminal.com/api/v2/networks/solana"
RUG = "https://api.rugcheck.xyz/v1/tokens/{}/report"
GOPLUS = "https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={}"
HEADERS = {"Accept": "application/json;version=20230302", "User-Agent": "meme-scanner-research/1.0"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SEEN = os.path.join(DATA, "seen.csv")
FOLLOW = os.path.join(DATA, "followups.csv")
ENRICH = os.path.join(DATA, "enrich.csv")
RAW = os.path.join(DATA, "enrich_raw.jsonl")
HORIZONS = {"1h": 3600, "24h": 86400, "7d": 604800}
MAX_FOLLOWUPS_PER_RUN = 20
MAX_ENRICH_PER_RUN = 12
MAX_ATTEMPTS = 3
RAW_SAMPLE_LIMIT = 40
FIELDS = ["ts", "address", "name", "created_at", "fdv_usd", "mcap_usd", "liquidity_usd", "price_usd",
          "vol_h1", "vol_h24", "chg_m5", "chg_h1", "chg_h24", "buys_h1", "sells_h1", "buyers_h1", "sellers_h1"]
SEEN_FIELDS = FIELDS + ["token"]
FOLLOW_FIELDS = FIELDS + ["horizon"]
ENRICH_FIELDS = ["ts", "address", "token", "attempt", "rc_status", "rc_score", "rc_risks", "rc_mint_auth",
                 "rc_freeze_auth", "rc_top1_pct", "rc_top10_pct", "rc_lp_locked_pct", "rc_creator_bal",
                 "rc_rugged", "rc_creator_rugged", "rc_danger_n", "rc_insider_n", "rc_holders_n",
                 "gp_status", "gp_mintable", "gp_freezable", "gp_transfer_fee", "gp_trusted", "gp_non_transferable",
                 "gp_closable", "gp_balance_mutable", "gp_metadata_mutable"]


def fetch(url):
    """Retourne (statut, json). statut : ok, http_404, http_429, http_XXX ou error."""
    req = urllib.request.Request(url, headers=HEADERS)
    status = "error"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return "ok", json.load(r)
        except urllib.error.HTTPError as e:
            status = f"http_{e.code}"
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            print(f"HTTP {e.code} {url}", file=sys.stderr)
            return status, None
        except Exception as e:  # reseau
            print(f"erreur {e} {url}", file=sys.stderr)
            status = "error"
            time.sleep(2)
    return status, None


def get(url):
    return fetch(url)[1]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return ""


def mint_of(p):
    try:
        i = p["relationships"]["base_token"]["data"]["id"]
    except (KeyError, TypeError):
        return ""
    return i.split("_", 1)[1] if "_" in i else i


def row(p, now_iso):
    a = p.get("attributes", {})
    vol = a.get("volume_usd") or {}
    chg = a.get("price_change_percentage") or {}
    tx = (a.get("transactions") or {}).get("h1") or {}
    return {
        "ts": now_iso, "address": a.get("address", ""), "name": a.get("name", ""),
        "created_at": a.get("pool_created_at", ""), "fdv_usd": num(a.get("fdv_usd")),
        "mcap_usd": num(a.get("market_cap_usd")), "liquidity_usd": num(a.get("reserve_in_usd")),
        "price_usd": num(a.get("base_token_price_usd")), "vol_h1": num(vol.get("h1")),
        "vol_h24": num(vol.get("h24")), "chg_m5": num(chg.get("m5")), "chg_h1": num(chg.get("h1")),
        "chg_h24": num(chg.get("h24")), "buys_h1": tx.get("buys", ""), "sells_h1": tx.get("sells", ""),
        "buyers_h1": tx.get("buyers", ""), "sellers_h1": tx.get("sellers", ""), "token": mint_of(p),
    }


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def ensure_schema(path, cols):
    """Migre un ancien fichier (colonnes manquantes) sans perdre de lignes."""
    if not os.path.exists(path):
        return
    with open(path, newline="") as f:
        header = next(csv.reader(f), [])
    if header == cols:
        return
    rows = read(path)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def append(path, rows, cols):
    ensure_schema(path, cols)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


_ABSENT = object()


def flag(v):
    """1 si une valeur (autorite, etc.) est presente, 0 si nulle, vide si le champ n'existe pas."""
    if v is _ABSENT:
        return ""
    return 1 if v else 0


def status_of(x):
    if isinstance(x, dict):
        return x.get("status", "")
    return "" if x is None else x


def parse_rug(d):
    tok = d.get("token") if isinstance(d.get("token"), dict) else {}
    mint_a = d.get("mintAuthority", tok.get("mintAuthority", _ABSENT))
    freeze_a = d.get("freezeAuthority", tok.get("freezeAuthority", _ABSENT))
    pcts = [num(h.get("pct")) for h in (d.get("topHolders") or []) if isinstance(h, dict)]
    pcts = [p for p in pcts if p != ""]
    risks = [str(r.get("name", "")) for r in (d.get("risks") or []) if isinstance(r, dict)]
    lp = d.get("lpLockedPct")
    if lp is None:  # pas verifie : le pourcentage de LP verrouille est peut-etre dans markets[].lp
        lps = [num((m.get("lp") or {}).get("lpLockedPct")) for m in (d.get("markets") or []) if isinstance(m, dict)]
        lps = [x for x in lps if x != ""]
        lp = max(lps) if lps else None
    holders = [h for h in (d.get("topHolders") or []) if isinstance(h, dict)]
    risk_objs = [r for r in (d.get("risks") or []) if isinstance(r, dict)]
    return {
        "rc_creator_rugged": 1 if any("rugged" in str(r.get("name", "")).lower() for r in risk_objs) else 0,
        "rc_danger_n": sum(1 for r in risk_objs if r.get("level") == "danger"),
        "rc_insider_n": sum(1 for h in holders if h.get("insider")), "rc_holders_n": len(holders),
        "rc_score": num(d.get("score_normalised")), "rc_risks": "|".join(risks),
        "rc_mint_auth": flag(mint_a), "rc_freeze_auth": flag(freeze_a),
        "rc_top1_pct": pcts[0] if pcts else "", "rc_top10_pct": round(sum(pcts[:10]), 4) if pcts else "",
        "rc_lp_locked_pct": num(lp), "rc_creator_bal": num(d.get("creatorBalance")),
        "rc_rugged": flag(d["rugged"]) if "rugged" in d else "",
    }


def parse_goplus(d, mint):
    res = (d or {}).get("result") or {}
    t = res.get(mint) or {}
    if not t:
        return {}
    return {
        "gp_mintable": status_of(t.get("mintable")), "gp_freezable": status_of(t.get("freezable")),
        "gp_transfer_fee": "" if not t.get("transfer_fee") else json.dumps(t.get("transfer_fee"))[:80],
        "gp_trusted": t.get("trusted_token", ""), "gp_non_transferable": t.get("non_transferable", ""),
        "gp_closable": status_of(t.get("closable")), "gp_balance_mutable": status_of(t.get("balance_mutable_authority")),
        "gp_metadata_mutable": status_of(t.get("metadata_mutable")),
    }


def enrich_one(mint, address, attempt, now_iso):
    out = {"ts": now_iso, "address": address, "token": mint, "attempt": attempt}
    rs, rd = fetch(RUG.format(mint))
    out["rc_status"] = rs
    if rs == "ok" and isinstance(rd, dict):
        out.update(parse_rug(rd))
    time.sleep(1.0)
    gs, gd = fetch(GOPLUS.format(mint))
    gp = parse_goplus(gd, mint) if gs == "ok" else {}
    out["gp_status"] = gs if gs != "ok" else ("ok" if gp else "empty")
    out.update(gp)
    # echantillons bruts pour verifier les noms de champs apres le premier essai
    try:
        n = sum(1 for _ in open(RAW)) if os.path.exists(RAW) else 0
        if n < RAW_SAMPLE_LIMIT and (rd or gd):
            with open(RAW, "a") as f:
                f.write(json.dumps({"ts": now_iso, "token": mint, "rc_status": rs, "gp_status": gs,
                                    "rugcheck_keys": sorted(rd.keys()) if isinstance(rd, dict) else None,
                                    "rugcheck_markets0": json.dumps((rd.get("markets") or [None])[0])[:2500] if isinstance(rd, dict) else None,
                                    "rugcheck_risks": rd.get("risks") if isinstance(rd, dict) else None,
                                    "goplus_head": json.dumps(gd)[:2000] if gd else None}) + "\n")
    except OSError:
        pass
    time.sleep(1.0)
    return out


def main():
    os.makedirs(DATA, exist_ok=True)
    now = time.time()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    ensure_schema(SEEN, SEEN_FIELDS)
    seen = read(SEEN)
    known = {r["address"] for r in seen}
    d = get(f"{BASE}/new_pools?page=1")
    added = []
    for p in (d or {}).get("data", []):
        r = row(p, now_iso)
        if r["address"] and r["address"] not in known:
            added.append(r)
            known.add(r["address"])
    if added:
        append(SEEN, added, SEEN_FIELDS)

    # --- enrichissement securite ---
    attempts, ok = {}, set()
    for e in read(ENRICH):
        attempts[e["address"]] = attempts.get(e["address"], 0) + 1
        if e.get("rc_status") == "ok":
            ok.add(e["address"])
    todo = []
    for r in seen + added:
        if not r.get("token") or r["address"] in ok:
            continue
        a = attempts.get(r["address"], 0)
        age = now - parse(r["ts"])
        if a < MAX_ATTEMPTS and age < 7200:
            todo.append((a, -parse(r["ts"]), r))
    todo.sort(key=lambda x: (x[0], x[1]))
    enr = []
    for a, _, r in todo[:MAX_ENRICH_PER_RUN]:
        enr.append(enrich_one(r["token"], r["address"], a + 1, now_iso))
    if enr:
        append(ENRICH, enr, ENRICH_FIELDS)

    # --- suivis ---
    follow = read(FOLLOW)
    done = {(r["address"], r["horizon"]) for r in follow}
    due = []
    for r in seen + added:
        t0 = parse(r["ts"])
        for h, secs in HORIZONS.items():
            # fenetre de 6 h pour ne pas rater un suivi si une execution saute
            if (r["address"], h) not in done and secs <= now - t0 <= secs + 21600:
                due.append((t0 + secs, r, h))
    due.sort(key=lambda x: x[0])
    out = []
    for _, r, h in due[:MAX_FOLLOWUPS_PER_RUN]:
        d = get(f"{BASE}/pools/{r['address']}")
        if d and d.get("data"):
            fr = row(d["data"], now_iso)
            fr["horizon"] = h
        else:  # pool disparue ou illisible : on le note, c'est une information (mort probable)
            fr = {k: "" for k in FOLLOW_FIELDS}
            fr.update({"ts": now_iso, "address": r["address"], "name": r["name"], "horizon": h})
        out.append(fr)
        time.sleep(2.2)
    if out:
        append(FOLLOW, out, FOLLOW_FIELDS)
    print(f"{now_iso} nouvelles={len(added)} enrichies={len(enr)} suivis={len(out)} "
          f"en_attente={max(0, len(due) - len(out))}")


if __name__ == "__main__":
    main()
