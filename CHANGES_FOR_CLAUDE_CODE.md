# Quant — Changements à implémenter

> Document de spécification pour Claude Code.
> Repo : `csequant` (Casablanca Stock Exchange quant system).
> Objectif : corriger la stratégie `mean_reversion`, durcir l'optimiseur, et
> ajouter de quoi re-tester proprement après le changement de régime de marché
> (sortie de guerre Iran-US, MoU signé le 19/06/2026, réouverture du détroit
> d'Ormuz sous 30 jours → probable détente du pétrole et rebond de la CSE).

---

## Contexte des résultats actuels

Backtest de référence (fenêtre 2023-06-19 → 2026-06-19, 18 noms, rebalance W-FRI, T+2, net de frais) :

| Stratégie | CAGR | Sharpe | MaxDD | Win% | vs Benchmark |
|---|--:|--:|--:|--:|--:|
| factor_model | 9.8% | 0.75 | −16.1% | 50% | −14.5% |
| momentum | 7.6% | 0.56 | −18.6% | 44% | −16.7% |
| mean_reversion | −12.6% | −0.99 | −35.8% | 34% | −36.8% |
| Benchmark (buy & hold) | 24.2% | 1.41 | −18.6% | — | — |

Les stratégies de timing sous-performent le buy-and-hold parce que la fenêtre est
dominée par un bull market persistant. C'est un résultat honnête, pas un bug. Les
changements ci-dessous visent (1) à réparer ce qui est cassé, (2) à durcir ce qui
est approximatif, (3) à préparer le re-test sur le nouveau régime.

---

## Changement 1 — `mean_reversion` : sortie trop précoce (PRIORITÉ HAUTE)

**Fichier :** `csequant/strategies/mean_reversion.py`

**Problème.** La condition de sortie ferme la position dès que le prix revient à
sa moyenne mobile (`zscore_exit = 0.0`). On achète à −1.5σ et on vend à 0σ : on ne
capture que la moitié du mouvement de réversion, tout en payant les frais
(commission + TVA + slippage) à chaque aller-retour. Le edge théorique est mangé
par les coûts.

**Preuve (backtest rapide sur le cache, 18 noms, coût 1.6% round-trip) :**

| Variante | Rendement moyen | Win rate |
|---|--:|--:|
| Original (`exit z>=0.0`) | −19.5% | 17% |
| Sortie retardée (`exit z>=1.0`) | −12.6% | 28% |
| Sortie retardée + filtre de régime | −9.6% | 28% |

**Action.**

1. Changer le défaut `zscore_exit` de `0.0` à `1.0` dans `defaults` (et répliquer
   dans `config/settings.yaml` → `strategies.mean_reversion.zscore_exit: 1.0`).
   Cela laisse la réversion dépasser la moyenne avant de sortir.

2. La logique d'exit reste `(z >= zscore_exit) | (rsi >= rsi_overbought)`, donc
   aucun changement de code dans `compute()` — seul le paramètre change. Vérifier
   que `self.params["zscore_exit"]` est bien lu depuis la config et non codé en
   dur ailleurs.

**Important.** Même corrigée, la stratégie reste perdante sur cette fenêtre
(−9.6%). Ne pas la présenter comme génératrice d'alpha. Le but est de limiter la
casse, pas de la rendre gagnante sur un marché en tendance.

---

## Changement 2 — `mean_reversion` : ajouter un filtre de régime (PRIORITÉ HAUTE)

**Fichier :** `csequant/strategies/mean_reversion.py`

**Problème.** La stratégie achète des titres en chute libre même quand ils sont
très au-dessus de leur tendance long terme (euphorie de bull market). Fader une
tendance forte est le mauvais pari.

**Action.** Ajouter un filtre optionnel qui interdit les entrées quand le prix est
trop au-dessus de sa moyenne mobile longue.

1. Nouveau paramètre dans `defaults` et dans `config/settings.yaml` :
   ```yaml
   strategies:
     mean_reversion:
       regime_ma: 200          # fenêtre de la moyenne mobile de régime
       regime_max_premium: 0.10   # n'entre pas si prix > MA200 * (1 + 0.10)
       regime_filter: true        # activable/désactivable
   ```

2. Dans `compute()`, après le calcul de `entry`, appliquer le filtre si activé :
   ```python
   if bool(self.params.get("regime_filter", False)):
       ma_reg = close.rolling(int(self.params["regime_ma"]),
                              min_periods=int(self.params["regime_ma"])).mean()
       premium = float(self.params["regime_max_premium"])
       not_euphoric = close < ma_reg * (1.0 + premium)
       entry = entry & not_euphoric.fillna(False)
   ```
   `fillna(False)` garantit qu'on n'entre pas tant que la MA longue n'est pas
   disponible (pas de look-ahead, comportement causal conservé).

3. Exposer les triggers correspondants dans `_static_triggers()` pour que la
   raison lisible mentionne le filtre.

---

## Changement 3 — `mean_reversion` : exposer la raison du filtre (PRIORITÉ MOYENNE)

**Fichiers :** `csequant/strategies/mean_reversion.py`,
`csequant/explainability/reasoning.py`

**Action.** Quand le filtre de régime bloque une entrée qui aurait sinon été
déclenchée, la raison lisible doit le dire (cohérent avec la philosophie
« explainable signals » du projet). Exemple de texte attendu :

> "NO ENTRY (mean_reversion): RSI(14)=27.0 oversold AND price 1.8σ below 20-day
> mean, BUT price is +14% above its 200-day trend (max +10%) → regime filter
> blocks the entry."

Garder le format des autres raisons (valeurs exactes des triggers en clair).

---

## Changement 4 — Optimiseur : intégrer la contrainte de volatilité dans le MV (PRIORITÉ MOYENNE)

**Fichier :** `csequant/risk/portfolio_optimizer.py`

**Problème.** Le mean-variance optimise `μ'w − ½λ·w'Σw` sous contrainte
`sum(w) == budget`, PUIS un vol-targeting rescale le vecteur a posteriori
(`_apply_vol_target`, `scale = min(1, target_vol / pv)`). Ce rescaling après coup
casse l'optimalité Markowitz : le portefeuille final n'est plus le portefeuille
mean-variance optimal au niveau de vol cible.

**Action (au choix, par ordre de préférence).**

- **Option A (propre).** Reformuler en ajoutant une contrainte d'inégalité de
  variance directement dans le programme SLSQP de `_mean_variance` :
  ```python
  cons.append({"type": "ineq",
               "fun": lambda w: target_vol**2 - w @ S @ w})
  ```
  et passer `target_vol` en argument de `_mean_variance`. On supprime alors le
  rescaling post-hoc pour le profil mean-variance (le garder pour risk-parity et
  rule-based si besoin).

- **Option B (minimal).** Garder le rescaling mais documenter explicitement dans
  le docstring et le STRATEGY.md que le portefeuille mean-variance est
  « optimal-then-scaled », pas « optimal-at-target-vol ». Honnêteté > élégance si
  le temps manque.

Choisir l'option A si les tests d'optimiseur passent toujours ; sinon B.

---

## Changement 5 — Optimiseur : réduire le biais « tout-cash » (PRIORITÉ MOYENNE)

**Fichier :** `csequant/risk/portfolio_optimizer.py` + `config/settings.yaml`

**Problème.** Sur le cache actuel, l'optimiseur sort 77–88% de cash dans tous les
profils. Cause : le shrinkage des rendements à 50% vers la moyenne
(`mu = grand + 0.5*(mu - grand)`) écrase les rendements attendus vers ~3–4%,
combiné à un vol-targeting agressif → aucune raison de concentrer. C'est
mathématiquement honnête mais probablement trop conservateur, surtout à l'aube
d'un changement de régime où les rendements futurs ne ressembleront pas aux
rendements passés (baissiers).

**Action.**

1. Rendre le coefficient de shrinkage configurable au lieu de le coder en dur :
   ```yaml
   optimizer:
     returns_shrink: 0.5   # 0 = pas de shrink (μ brut), 1 = tout vers la moyenne
   ```
   et remplacer la ligne en dur :
   ```python
   shrink = float(self.cfg.get("optimizer.returns_shrink", 0.5))
   mu = grand + (1.0 - shrink) * (mu - grand)
   ```
   ⚠️ Attention au sens : avec la formule actuelle `grand + 0.5*(mu-grand)`,
   le `0.5` est le **poids gardé sur μ**, pas le poids du shrink. Clarifier la
   sémantique dans le commentaire pour éviter toute confusion (shrink=0.5 doit
   donner exactement le comportement actuel).

2. Ne RIEN changer aux défauts (rétrocompatibilité). Juste rendre le levier
   accessible pour permettre des sensibilités lors du re-test post-régime.

---

## Changement 6 — Ajouter une commande de sensibilité / re-test de régime (PRIORITÉ BASSE)

**Fichiers :** `csequant/cli.py`, `csequant/pipeline.py`

**Contexte.** Tous les backtests existants couvrent un bull market 2023–2026. Le
contexte macro vient de basculer (fin de guerre Iran-US, réouverture d'Ormuz,
détente probable du pétrole). On veut pouvoir re-tester facilement sur des
sous-fenêtres et comparer les régimes.

**Action.** Ajouter une commande CLI `backtest-window` qui prend `--start` et
`--end` et lance le backtest des trois stratégies sur cette sous-fenêtre, en
réutilisant le moteur existant (pas de nouveau code de backtest, juste un
filtrage de dates avant l'appel au moteur). Sortie : le même tableau de métriques
que `backtest`, plus une ligne benchmark.

Exemple d'usage visé :
```bash
python -m csequant backtest-window --start 2026-03-01 --end 2026-06-19
```
(post-frappes, marché stressé — pour voir si momentum/factor tiennent mieux que
le buy-and-hold dans un régime non-haussier).

---

## Changement 7 — Tests à ajouter / mettre à jour (PRIORITÉ HAUTE, accompagne 1-2)

**Fichier :** `tests/test_indicators.py` ou nouveau `tests/test_mean_reversion.py`

**Action.**

1. Test que `zscore_exit` par défaut vaut bien `1.0` après le changement 1.
2. Test du filtre de régime : construire une série synthétique en forte hausse
   (prix >> MA200) avec un creux de RSI ; vérifier qu'avec `regime_filter: true`
   AUCUNE entrée n'est générée, et qu'avec `regime_filter: false` l'entrée
   apparaît. Garantit que le filtre est causal et fonctionnel.
3. Test de non-régression : les autres stratégies (`momentum`, `factor_model`) ne
   doivent pas être affectées par ces changements.
4. Si Changement 4 option A retenu : test que la vol réalisée du portefeuille MV
   optimisé est ≤ `target_vol` (à une tolérance près).

Tous les tests doivent rester synthétiques et sans réseau (cohérent avec la suite
existante).

---

## Ordre d'implémentation suggéré

1. Changement 1 (param `zscore_exit` → 1.0) — trivial, gros impact.
2. Changement 2 (filtre de régime) — cœur du correctif mean_reversion.
3. Changement 7 (tests pour 1 + 2) — verrouiller le comportement.
4. Changement 3 (raison lisible du filtre) — cohérence explainability.
5. Changement 5 (shrink configurable) — petit, utile pour le re-test.
6. Changement 4 (vol intégrée au MV) — plus délicat, option B acceptable.
7. Changement 6 (CLI backtest-window) — confort de re-test.

---

## Garde-fous (ne pas casser)

- Tout reste **long-only**, **whole-share**, **T+2**, **causal (pas de
  look-ahead)** — ce sont les invariants du projet.
- Tous les nouveaux paramètres vont dans `config/settings.yaml`, jamais codés en
  dur (principe du projet : « everything a strategy needs lives in config »).
- Conserver les défauts existants pour la rétrocompatibilité ; les nouveaux
  comportements (filtre de régime, shrink ajustable) doivent reproduire
  exactement l'ancien comportement quand on garde les valeurs par défaut
  d'origine.
- `mean_reversion` reste documentée honnêtement comme perdante sur la fenêtre
  haussière, même après correctifs. Ne pas survendre les résultats.
- `pytest -q` doit passer entièrement après chaque changement.
