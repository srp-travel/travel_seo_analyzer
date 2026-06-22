# travel_seo_analyzer

Outil d'analyse SEO pour les pages du sitemap `voyage.showroomprive.com`.

## Installation

```bash
cd travel_seo_analyzer
pip install -r requirements.txt
python app.py
```

Ouvrir **http://localhost:5000** dans votre navigateur.

## Fonctionnalités

### 1. Scraping avec cache
- Parse le sitemap `voyage.showroomprive.com/sitemap_serp.xml`
- Scrape toutes les pages avec user-agent Chrome réaliste
- Sauvegarde le HTML dans `cache/` pour réutilisation
- Barre de progression en temps réel (Server-Sent Events)
- Option "Rafraîchir" pour forcer le re-téléchargement

### 2. Onglet SEO basique (automatique)
Vérifie pour chaque page : H1, Meta Title, Meta Description.
Export CSV disponible.

### 3. Onglet Offres (automatique)
Détecte la présence de `div.result-offers` et le nombre d'offres.
Export CSV disponible.

### 4. Onglet Contenu éditorial (à la demande)
Extrait et permet d'exporter en CSV :
- H1, Meta Title, Meta Description
- Contenu de `class="header-intro"`
- Contenu de `class="bloc-edito-content"`
- Contenu de `class="cpt-faq"`

### 5. Onglet Conformité specs ⚡ (à la demande)
Vérifie : format Title, format H1, unicité H1, canonical, Open Graph,
BreadcrumbList Schema.org, FAQPage Schema.org, longueur meta description.

### 6. Onglet Guide Google AIO ⚡ (à la demande)
Vérifie les critères du guide Google pour l'optimisation IA générative :
données structurées, hiérarchie H2, meta description, volume de contenu,
canonical self-ref, alt text images, FAQPage schema, balise `<main>`.

## Structure du projet

```
travel_seo_analyzer/
├── app.py           → Serveur Flask + routes API
├── scraper.py       → Parsing sitemap + scraping + cache
├── analyzer.py      → Moteur d'analyse SEO (5 modules)
├── requirements.txt
├── README.md
├── templates/
│   └── index.html   → Interface utilisateur
├── static/
│   ├── app.js       → Logique frontend
│   └── style.css    → Styles
└── cache/           → HTML des pages scrappées (auto-créé)
```
