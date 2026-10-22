# meme-scanner

Observation seulement : aucun ordre, aucune cle, aucun portefeuille.

Toutes les 5 minutes, le scanner relève les nouvelles pools Solana (GeckoTerminal) dans `data/seen.csv`,
puis refait un relevé de chaque pool environ 1 h, 24 h et 7 jours plus tard dans `data/followups.csv`
(une ligne vide avec l'horizon = la pool a disparu, donc probablement morte).

Installation : créer un dépôt public (l'accès gratuit aux Actions est illimité en public), y déposer ces fichiers,
puis Actions > scanner > Run workflow pour un premier test. Le dossier `data/` se remplit tout seul.

Après une semaine, on regarde : quelles caractéristiques au départ (liquidité, volume, achats/ventes,
nombre d'acheteurs) précèdent les tokens qui tiennent à 24 h et 7 jours, et lesquelles précèdent les morts.
Pas un conseil financier.
