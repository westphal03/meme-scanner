#!/usr/bin/env python3
"""Scanner de nouveaux tokens Solana (GeckoTerminal). OBSERVATION SEULEMENT : aucun ordre, aucune cle.

Chaque execution (aux 5 minutes via GitHub Actions) :
 1. lit les nouvelles pools et enregistre chaque pool jamais vue dans data/seen.csv (releve initial)
 2. pour les pools vues il y a ~1 h, ~24 h et ~7 jours, refait un releve dans data/followups.csv
Le but : apprendre quel genre de token meurt et lequel tient. Rien n'est un conseil d'achat.
"""
import csv, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

BASE = "https://api.geckoterminal.com/api/v2/networks/solana"
HEADERS = {"Accept": "application/json;version=20230302", "User-Agent": "meme-scanner-research/1.0"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SEEN = os.path.join(DATA, "seen.csv")
FOLLOW = os.path.join(DATA, "followups.csv")
HORIZONS = {"1h": 3600, "24h": 86400, "7d": 604800}
MAX_FOLLOWUPS_PER_RUN = 20  # reste sous la limite de debit gratuite
FIELDS = ["ts", "address", "name", "created_at", "fdv_usd", "mcap_usd", "liquidity_usd", "price_usd",
          "vol_h1", "vol_h24", "chg_m5", "chg_h1", "chg_h24", "buys_h1", "sells_h1", "buyers_h1", "sellers_h1"]


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            print(f"HTTP {e.code} {url}", file=sys.stderr)
            return None
        except Exception as e:  # reseau
            print(f"erreur {e} {url}", file=sys.stderr)
            time.sleep(2)
    return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return ""


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
        "buyers_h1": tx.get("buyers", ""), "sellers_h1": tx.get("sellers", ""),
    }


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def append(path, rows, extra=()):
    new = not os.path.exists(path)
    cols = FIELDS + list(extra)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerows(rows)


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def main():
    os.makedirs(DATA, exist_ok=True)
    now = time.time()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        append(SEEN, added)

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
            fr = {k: "" for k in FIELDS}
            fr.update({"ts": now_iso, "address": r["address"], "name": r["name"], "horizon": h})
        out.append(fr)
        time.sleep(2.2)
    if out:
        append(FOLLOW, out, extra=["horizon"])
    print(f"{now_iso} nouvelles={len(added)} suivis={len(out)} en_attente={max(0, len(due) - len(out))}")


if __name__ == "__main__":
    main()
