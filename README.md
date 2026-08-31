# Job Agent

Moteur de matching offre↔profil pour des postes Data Scientist / ML–AI
Engineer, marché français et remote EU.

La métrique optimisée est le nombre de **conversations qualifiées par
semaine**. Le nombre de candidatures envoyées est traité comme une
anti-métrique : le système est conçu pour éliminer, pas pour classer
large.

> 🚧 En cours de construction. Le code n'est pas exécutable en l'état.

---

## Périmètre

Le système ingère des offres depuis des sources structurées, en extrait
les exigences sous forme atomique, les apparie à un profil lui-même
décomposé en preuves vérifiées, et produit un digest quotidien de 5 à 10
offres. Chaque entrée porte un score, la liste des exigences couvertes et
non couvertes, et une recommandation d'action.

**Implémenté ou planifié**

- Connecteurs ATS publics : Greenhouse, Lever, Ashby, SmartRecruiters,
  Recruitee, Workable, Personio
- Connecteur France Travail (API officielle, OAuth2, segmentation par
  code ROME)
- Normalisation vers un schéma canonique, déduplication en deux passes
  (hash exact, puis similarité d'embedding), scoring d'offres fantômes
- Scoring décomposable : couverture par exigence (`7/9 must-have`), les
  manquants nommés
- Digest quotidien, feedback 1-clic alimentant le jeu d'évaluation
- Étapes ultérieures : brief entreprise, génération de documents ancrée
  sur les preuves, CRM, préparation d'entretien

**Hors périmètre, par décision**

- Pas d'auto-postulation. Toute sortie externe passe par une validation
  humaine.
- Pas de scraping LinkedIn. Uniquement des endpoints publics et des API
  officielles.
- Pas d'orchestration multi-agents autonome. Pipeline déterministe, appels
  LLM localisés aux nœuds d'extraction, de jugement et de rédaction.

---

## Architecture

```
   SOURCES                 ATS publics · France Travail
      │                    cron, 1 passe/entreprise/24 h
      ▼
   INGESTION               connecteurs → normalisation → dédup
      │
      ▼
   ENRICHISSEMENT          extraction des requirements (LLM, en cache)
      │                    → embeddings bge-m3
      ▼
┌──────────────┐       ┌──────────────────────────────────────┐
│   PROFIL     │──────▶│  MATCHING ENGINE                     │
│ proof_points │       │  S0  filtres SQL        ~500 → ~120  │
│ filtres durs │       │  S1  late interaction   ~120 →  ~25  │
└──────────────┘       │  S2  LLM-judge           ~25 →   ~8  │
                       └──────────────────┬───────────────────┘
                                          ▼
                              DIGEST quotidien → UI + CRM
                                     ◀── validation humaine
```

_Les volumes indiqués sont des cibles de design, à confirmer par la mesure
au S3._

### Décisions structurantes

| Décision                          | Justification                                                                                                                                                | Contrepartie acceptée                                       |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| Pas de framework d'agents         | Le graphe a moins de 5 nœuds ; LangGraph/CrewAI ajoutent une couche d'indirection sans réduire la complexité réelle. Appels LLM directs + schémas Pydantic.  | À réintroduire si le graphe se ramifie (mock interview, L7) |
| Postgres + pgvector               | Corpus < 100k vecteurs, sous le seuil où un index dédié apporte quelque chose. Une seule base : transactions, jointures offre↔exigence↔match, backup unique. | Perte de performance au-delà de ~1M vecteurs                |
| Pipeline déterministe             | Le contrôle de flux est en Python, pas dans un LLM. Rejouabilité, coût prévisible, bugs localisables.                                                        | Pas d'adaptation dynamique du plan d'exécution              |
| Embeddings self-hosted (`bge-m3`) | Corpus bilingue FR/EN, donc un modèle multilingue est une contrainte, pas une préférence. Ré-indexation sans coût marginal.                                  | Gestion de l'inférence à charge du projet                   |

---

## Matching

Le matching est formulé comme un problème de ranking : la requête est
l'ensemble des exigences d'une offre, le corpus est l'ensemble des
`proof_points` du profil. Le score de l'offre est une agrégation des
scores d'appariement exigence↔preuve.

### Pourquoi pas un bi-encodeur document-niveau

Encoder le CV et l'offre en un vecteur chacun puis calculer un cosinus
pose trois problèmes :

1. **Dilution par pooling** — le mean-pooling d'un document de 2–3k tokens
   écrase les exigences discriminantes. Une exigence contribue ~1/N à la
   représentation ; sa présence ou son absence déplace le cosinus de moins
   que le bruit inter-offres.
2. **Score dominé par la similarité de registre** — deux documents du même
   domaine (lexique data/ML, format offre d'emploi) obtiennent un cosinus
   élevé indépendamment du fit réel. La variance utile entre offres est
   faible devant la composante topique commune, ce qui rend le seuillage
   instable.
3. **Score non décomposable** — un scalaire unique ne permet ni d'attribuer
   le score à une exigence, ni de diagnostiquer une erreur de ranking, ni
   d'alimenter l'affichage de couverture.

### Approche retenue : interaction tardive

On décompose des deux côtés en unités atomiques, on calcule la matrice de
similarité complète exigences × preuves, et on n'agrège qu'au dernier
moment : max sur les preuves, puis moyenne pondérée sur les exigences.
C'est un MaxSim de type ColBERT appliqué au niveau de la proposition
plutôt que du token.

```
Pour chaque exigence r :
    sim(r) = max_p cos(emb(r), emb(p))

retrieval_score = Σ_r w(r)·sim(r) / Σ_r w(r)

w(must_have) = 3.0 · w(responsibility) = 1.5 · w(nice_to_have) = 1.0
```

Trois propriétés en découlent :

1. **Score décomposable.** La matrice exigences × preuves est conservée.
   Pour chaque exigence on dispose de l'argmax sur les preuves et de la
   similarité associée, ce qui donne à la fois l'affichage de couverture
   et le matériel d'analyse d'erreurs.
2. **Pas de dilution.** Le max sur les preuves est calculé par exigence,
   donc une exigence rare bien couverte conserve son score quel que soit le
   nombre d'exigences génériques dans l'offre. La pondération par `kind`
   contrôle ensuite explicitement la contribution de chacune, au lieu de la
   laisser dépendre de la longueur du document.
3. **Coût d'inférence nul.** L'étage se réduit à un produit matriciel sur
   des embeddings déjà indexés. Le re-scoring complet du corpus après
   modification du profil est de l'ordre de la seconde, ce qui rend
   l'itération sur les `proof_points` et sur les poids praticable —
   condition nécessaire pour tuner l'étage contre le jeu labellisé.

### Étage LLM

Le LLM-judge n'est appliqué qu'au top-25, avec la matrice de couverture
passée en entrée. Le jugement est donc conditionné sur un signal
quantitatif explicite plutôt que sur la seule lecture des deux documents.
Sa sortie exploitable n'est pas le `fit_score` mais le champ
`recommendation` (`apply`, `apply_with_prep`, `network_first`, `skip`),
qui encode une décision plutôt qu'une mesure.

Coût estimé : ≈ 0,35 $/jour, contre ≈ 8 $/jour pour un scoring LLM
appliqué à l'ensemble du corpus (~500 offres/jour, ~4k tokens/offre).
Chiffres à remplacer par la mesure issue de la table `llm_call`.

---

## Ancrage factuel

La génération de documents est contrainte à deux niveaux.

**En entrée** : l'agent ne reçoit que la liste des `proof_point_id`
retenus pour l'offre et doit retourner, pour chaque phrase produite,
l'identifiant source. Reformulation, condensation et réordonnancement sont
autorisés ; l'ajout d'une compétence ou d'une métrique absente des preuves
ne l'est pas.

**En sortie** : une passe de validation segmente le texte en claims et
vérifie que chacun se rattache à un `proof_point`. Les claims non ancrés
sont écrits dans `document.unanchored_claims` et affichés dans l'UI ; le
document n'est pas livré comme valide tant qu'ils n'ont pas été traités.

La contrainte d'entrée réduit le taux d'invention, la passe de sortie le
mesure. Aucune des deux ne le garantit à zéro — un claim reformulé de
manière trop générique peut passer la validation.

---

## Stack

Python 3.12 · FastAPI + Pydantic v2 · Postgres 16 + pgvector (HNSW,
cosine) · sentence-transformers / bge-m3, 1024 dim, self-hosted CPU ·
API Anthropic, routage à deux tiers (extraction / jugement) ·
APScheduler · Streamlit · pytest + cassettes VCR

---

## Évaluation

Jeu de 250–300 offres labellisées manuellement sur une échelle 0–3, split
70/30 avec test gelé. Cinq systèmes comparés sur le même jeu : filtres
mots-clés, BM25 description↔CV, cosinus global CV↔offre, interaction
tardive exigences↔preuves, interaction tardive + rerank LLM.

Métriques : Recall@25 et NDCG@10 sur l'étage de retrieval, Precision@10
sur le digest final, MAE du `fit_score` normalisé et Cohen's κ sur
`recommendation` pour l'étage LLM.

Recall@25 est la métrique contraignante : une offre écartée à l'étage 1 ne
peut plus être récupérée en aval.

Protocole et résultats : `docs/evaluation.md` — _à venir_.

---

## Démarrage

_À venir._ L'installation n'est pas encore stabilisée.

---

## Notes

Les endpoints ATS interrogés sont des API publiques non authentifiées.
Politique de crawl : une passe par entreprise et par 24 h, backoff
exponentiel sur 429/5xx, User-Agent identifiable.

Le dépôt public contient le code et un jeu de démonstration synthétique.
Les `proof_points` réels, les labels et le contenu des offres ne sont pas
versionnés.
