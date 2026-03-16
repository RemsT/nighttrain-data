# nighttrain-data

Source de données ouverte pour les trains de nuit européens — utilisée par l'app iOS **NightTrain**.

`routes.json` est le fichier central. Il est mis à jour automatiquement chaque mois via GitHub Actions et peut être consommé directement par n'importe quelle app ou projet.

---

## Contenu de routes.json

Chaque route contient :

| Champ | Description |
|-------|-------------|
| `id` | Identifiant unique (ex: `nightjet-vienna-paris`) |
| `name` | Nom lisible (ex: `Vienne → Paris`) |
| `operator` | Compagnie opératrice (ex: `ÖBB Nightjet`) |
| `status` | `active` · `suspended` · `upcoming` |
| `stops` | Liste des arrêts avec heures de départ/arrivée |
| `coordinates` | Tracé GPS de la ligne `[{ lat, lon }]` |
| `duration` | Durée totale du trajet |
| `operating_days` | Fréquence (ex: `Lun-Sam`) |
| `accommodations` | Types disponibles + prix de départ |
| `is_direct` | Sans changement de train |
| `bike_allowed` · `pet_allowed` | Services à bord |
| `meal_included` · `shower_available` | Confort à bord |
| `booking_url` | Lien de réservation |

**URL publique :**
```
https://raw.githubusercontent.com/RemsT/nighttrain-data/main/routes.json
```

---

## Comment les données sont collectées

Les données proviennent de plusieurs sources selon la compagnie, toutes interrogées automatiquement par les scripts Python dans `scripts/`.

### 1. API Hafas — DB & ÖBB
> Nightjet, European Sleeper, EuroNight, Snälltåget, PKP

[Hafas](https://github.com/public-transport/hafas-client) est le système de planification de trajets utilisé par les chemins de fer européens. Des instances publiques non officielles permettent d'y accéder librement :

- `https://v6.db.transport.rest` — réseau DB (Allemagne + Europe)
- `https://v5.db.transport.rest` — réseau ÖBB (Autriche + Italie)

Pour chaque route, on cherche un trajet sur les 14 prochains jours en filtrant par numéro de train (ex: `NJ 421`) et on extrait automatiquement les arrêts, horaires et coordonnées GPS.

**Pour trouver un numéro de train :** chercher le trajet sur [bahn.de](https://www.bahn.de) ou directement via `https://v6.db.transport.rest/journeys?from=...&to=...` et repérer le `trainNumber` dans la réponse JSON.

### 2. API SNCF Open Data
> Intercités de Nuit, Trenhotel France

L'[API SNCF](https://data.sncf.com) fournit les horaires des trains français. Elle nécessite une clé API gratuite, disponible sur [data.sncf.com](https://data.sncf.com) → *Mes tokens*. À configurer dans les secrets GitHub (`SNCF_API_KEY`). Sans clé, les arrêts SNCF sont conservés depuis la dernière version valide.

### 3. Entur — Norvège
> Vy Nattog, Go-Ahead Norge

L'[API Entur](https://api.entur.io) couvre les trains scandinaves norvégiens. Elle est publique et ne nécessite pas de clé.

### 4. Manual
Certaines lignes (Trenhotel Espagne, Caledonian Sleeper, lignes saisonnières rares) n'ont pas d'API fiable ou accessible. Leurs données sont maintenues à la main dans `routes.json` et déclarées `api: manual` dans `enrichment.yaml` — le script ne les touche jamais.

---

## Structure des fichiers

```
nighttrain-data/
├── routes.json              ← Source de vérité (lue par l'app iOS)
├── enrichment.yaml          ← Config API par route (numéro de train, gares, saison)
├── requirements.txt         ← Dépendances Python (requests, pyyaml)
├── scripts/
│   ├── build_routes.py      ← Script principal (orchestre la mise à jour)
│   ├── fetch_hafas.py       ← Fetcher API Hafas DB/ÖBB
│   ├── fetch_sncf.py        ← Fetcher API SNCF
│   ├── fetch_entur.py       ← Fetcher API Entur (Norvège)
│   └── validate.py          ← Validation avant commit (bloque les régressions)
└── .github/workflows/
    └── update.yml           ← GitHub Actions (1er de chaque mois, 5h UTC)
```

---

## Mise à jour automatique

Le workflow tourne le **1er de chaque mois à 5h UTC**. Il :

1. Appelle les APIs pour chaque route configurée dans `enrichment.yaml`
2. Applique la règle de sécurité : si une API renvoie moins de 70% des arrêts connus → conserve les données existantes
3. Calcule le statut saisonnier (`active_from` / `active_until`)
4. Valide qu'aucune route n'a régressé par rapport à la version précédente
5. Commit et push si des changements sont détectés

**Déclencher manuellement :**

GitHub → Actions → *Update Night Train Routes* → **Run workflow**

Cocher **Dry-run** pour voir les changements sans modifier `routes.json`.

---

## Ajouter ou modifier une route

### Modifier une route existante

Édite directement `routes.json` et push. Le champ `version` sera incrémenté automatiquement au prochain run automatique.

### Ajouter une nouvelle route

**1. Ajouter l'entrée dans `routes.json`** avec tous les champs requis et un `id` unique en kebab-case.

**2. Ajouter la config dans `enrichment.yaml`** :

```yaml
nightjet-vienna-paris:
  api: hafas_db
  from_station: "Wien Hbf"      # nom exact Hafas
  to_station: "Paris Est"
  train_number: "NJ 468"
  # Optionnel — pour les lignes saisonnières :
  seasonal:
    active_from: "06-15"        # MM-DD
    active_until: "09-15"
```

Si la ligne n'a pas d'API connue, utiliser `api: manual` — les arrêts ne seront jamais écrasés.

**3. Tester localement :**

```bash
pip install -r requirements.txt
python scripts/build_routes.py --dry-run
```

---

## Sources de référence pour trouver les lignes

| Source | Ce qu'on y trouve |
|--------|-------------------|
| [seat61.com](https://www.seat61.com/night-trains-in-europe.htm) | Répertoire complet des trains de nuit européens, horaires et infos pratiques |
| [back-on-track.eu](https://back-on-track.eu/night-train-map/) | Carte interactive et état du réseau européen |
| [nightjet.com](https://www.nightjet.com) | Réseau officiel ÖBB (Autriche, Allemagne, Italie, Pays-Bas…) |
| [european-sleeper.eu](https://www.european-sleeper.eu) | Brussels → Prague, Amsterdam → Barcelona |
| [snalltaget.se](https://www.snalltaget.se) | Stockholm → Berlin, Malmö → Innsbruck |
| [sleeper.scot](https://www.sleeper.scot) | Caledonian Sleeper (Londres → Écosse) |
| [intercites-de-nuit.sncf.com](https://www.intercites-de-nuit.sncf.com) | Intercités de Nuit SNCF |
| [renfe.com](https://www.renfe.com) | Trenhotel espagnols |
| [bahn.de](https://www.bahn.de) | Recherche de trajets pour trouver les numéros de train Hafas |

---

## Utiliser ces données dans un projet

```swift
// iOS / Swift
let url = URL(string: "https://raw.githubusercontent.com/RemsT/nighttrain-data/main/routes.json")!
let (data, _) = try await URLSession.shared.data(from: url)
let payload = try JSONDecoder().decode(RoutesPayload.self, from: data)
```

```js
// JavaScript / Node
const res = await fetch("https://raw.githubusercontent.com/RemsT/nighttrain-data/main/routes.json")
const data = await res.json()
```

---

## Contribuer

Les données sont incomplètes — il manque des lignes, des arrêts, des prix à jour. Toute contribution est bienvenue :

- **Corriger un horaire ou un arrêt** → édite `routes.json` + PR
- **Ajouter une ligne** → `routes.json` + `enrichment.yaml` + PR
- **Améliorer un fetcher** → `scripts/` + PR

Ouvre une issue si tu trouves une ligne incorrecte ou manquante.
