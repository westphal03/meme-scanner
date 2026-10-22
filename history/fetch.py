#!/usr/bin/env python3
"""Telecharge l'historique public Binance Vision (bougies 1d et 1h) et ecrit un CSV compact par symbole/intervalle.
Lecture seule de donnees publiques. Colonnes: open_time_ms,open,high,low,close,volume"""
import io, sys, zipfile, urllib.request, urllib.error, gzip, datetime as dt
SYMS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT"]
INTERVALS = ["1d", "1h"]
START = (2019, 1)
now = dt.datetime.utcnow()
def months():
    y, m = START
    while (y, m) <= (now.year, now.month):
        yield y, m
        m += 1
        if m == 13: y, m = y + 1, 1
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r: return r.read()
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else (_ for _ in ()).throw(e)
def rows(z):
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        for line in zf.read(zf.namelist()[0]).decode().splitlines():
            p = line.split(",")
            if not p[0].isdigit(): continue
            t = int(p[0]); t = t // 1000 if t > 1e15 else t  # microsecondes -> ms (donnees 2025+)
            yield t, p[1], p[2], p[3], p[4], p[5]
for s in SYMS:
    for iv in INTERVALS:
        out, first, miss = {}, None, 0
        for y, m in months():
            ym = f"{y}-{m:02d}"
            z = get(f"https://data.binance.vision/data/spot/monthly/klines/{s}/{iv}/{s}-{iv}-{ym}.zip")
            if z is None:
                # mois en cours ou pas encore publie : fichiers journaliers
                if (y, m) == (now.year, now.month) or (y, m) >= ((now - dt.timedelta(days=45)).year, (now - dt.timedelta(days=45)).month):
                    d = dt.date(y, m, 1)
                    while d.month == m and d < now.date():
                        zd = get(f"https://data.binance.vision/data/spot/daily/klines/{s}/{iv}/{s}-{iv}-{d.isoformat()}.zip")
                        if zd:
                            for r in rows(zd): out[r[0]] = r
                        d += dt.timedelta(days=1)
                else: miss += 1
                continue
            for r in rows(z): out[r[0]] = r
        if not out:
            print(f"{s} {iv}: aucune donnee", file=sys.stderr); continue
        ks = sorted(out)
        with gzip.open(f"history/{s}_{iv}.csv.gz", "wt") as f:
            f.write("open_time_ms,open,high,low,close,volume\n")
            for k in ks: f.write(",".join(map(str, out[k])) + "\n")
        a = dt.datetime.utcfromtimestamp(ks[0]/1000); b = dt.datetime.utcfromtimestamp(ks[-1]/1000)
        print(f"{s} {iv}: {len(ks)} bougies {a:%F %H:%M} -> {b:%F %H:%M} (mois manquants: {miss})")
