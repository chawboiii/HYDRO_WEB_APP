# 🌊 HYDRO_WEB_APP : Inférence Hydrologique Régionale par Deep Learning (LSTM) & WebGIS

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new)
![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![Django](https://img.shields.io/badge/Django-5.0-success.svg)
![PyTorch](https://img.shields.io/badge/PyTorch-2.2-orange.svg)
![Leaflet](https://img.shields.io/badge/Leaflet-1.9-green.svg)
![IAV Hassan II](https://img.shields.io/badge/IAV%20Hassan%20II-PFE%20G%C3%A9nie%20Rural-darkred.svg)

> **Projet de Fin d'Études — Institut Agronomique et Vétérinaire Hassan II (IAV), Rabat**  
> **Filière :** Ingénierie en Génie Rural  
> **Auteur :** Ayach Mohamed Chawki  
> **Sujet :** *Modélisation hydrologique pluie-débit en milieu semi-aride non jaugé par Deep Learning régionalisé (LSTM) : transfert transfrontalier et évaluation in situ au Maroc (Loukkos & Oum Er-Rbia).*

---

## 📌 Présentation du Projet

**HYDRO_WEB_APP** est une plateforme WebGIS décisionnelle intégrée conçue pour l'évaluation et la prédiction continue des ressources en eau de surface dans les bassins versants non jaugés ou faiblement équipés du Maroc.

La plateforme combine :
1. **Un modèle Deep Learning hydrologique (HydroLSTM)** pré-entraîné sur 247 bassins versants ibéro-méditerranéens (KGE médian = 0,619) et transféré sans re-calibration sur le territoire marocain.
2. **Un moteur de délinéation spatiale instantané (D8 pyflwdir + HydroSHEDS)** permettant de délimiter le bassin versant d'un cours d'eau en moins de 2 secondes à partir d'un simple clic sur la carte.
3. **Une matrice de 8 descripteurs physiographiques et climatiques** calculés automatiquement avec diagnostic d'enveloppe de validité opérationnelle (aridité, superficie, relief, couverture forestière).
4. **Un module d'audit d'influence anthropique & détection des barrages amont** (45 grands barrages du Maroc) vérifiant si l'écoulement à l'exutoire est naturel ou régulé par une retenue hydraulique.
5. **Une vérité terrain in situ sur 9 stations de jaugeage officielles** des agences de bassin ABHL (Loukkos) et ABHOER (Oum Er-Rbia) comparant les débits simulés par le LSTM aux observations hydrométriques réelles (2000–2024).
6. **Le réseau hydrographique détaillé des oueds majeurs du Maroc** dérivé d'HydroRIVERS (segments $\ge 30\text{ km}^2$).

---

## 🏛️ Architecture & Fonctionnalités Clés

### 1. Délinéation & Caractérisation Spatiale Instantanée
* **MNT D8 HydroSHEDS 3 arc-secondes** (`data/hysheds_dir_maroc.tif`) intégré en mémoire.
* Snapping automatique du curseur sur le thalweg le plus proche.
* Découpage du polygone vectoriel amont et calcul de la superficie ($A$ en $\text{km}^2$), altitude moyenne ($H_{\text{mean}}$ en m) et pente moyenne ($S_{\text{mean}}$ en %).

### 2. Le Moteur Deep Learning (HydroLSTM)
* **Architecture :** LSTM à 128 unités cachées, couche de Dropout (0,5), et tête de régression linéaire.
* **Entrées (12 variables) :** 4 forçages météorologiques journaliers (Précipitation $P$, Température min $T_{\min}$, Température max $T_{\max}$, Évapotranspiration potentielle $\text{PET}$) couplés aux 8 attributs physiographiques statiques normalisés.
* **Sortie :** Lame d'eau écoulée journalière ($Q$ en $\text{mm/jour}$) convertie en débit instantané ($m^3/s$) et volume mensuel ($\text{hm}^3/\text{mois}$).
* **Modèle Temporel Actif :** `models/temporal_model/model_epoch025.pt` (Époque 25, 247 bassins d'entraînement).

### 3. Audit Anthropique & Détection des Barrages en Amont
* Base spatiale des **45 grands barrages du Maroc** (`data/dams_morocco_inventory.json`).
* Intersection géométrique en temps réel avec le polygone délinéé :
  - 🟢 **Régime Naturel :** 0 barrage en amont $\to$ Prédictions LSTM 100% valides.
  - 🟡 **Faiblement Influencé :** Capacité amont $V_{\text{amont}} < 10\text{ hm}^3$.
  - 🔴 **Fortement Régulé :** Présence d'une grande retenue (ex: Al Wahda, Bin el Ouidane, Al Massira) $\to$ Alerte méthodologique précisant que l'écoulement réel dépend du déstockage de l'ouvrage.

### 4. Carte Interactive Leaflet.js Haute Performance
* Sélecteur de fonds de carte à haute vélocité sans blocage : **Topographie Relief Esri**, **CartoDB Voyager**, et **Satellite HD**.
* Affichage vectoriel fluide du réseau des oueds marocains (HydroRIVERS).
* Couche SIG des 45 grands barrages avec fiches techniques interactives (capacité en $\text{Mm}^3$, hauteur, oued, bassin, année).
* Affichage des hydrogrammes mensuels et journaliers avec Chart.js réactif.

---

## 📊 Jeu de Données d'Entraînement (247 Bassins)

Le jeu de données complet des **247 bassins versants ibériques** ayant servi à l'entraînement du modèle LSTM est documenté et hébergé sur un dépôt public séparé :
👉 **[Accéder au Dépôt du Dataset des 247 Bassins Versants d'Entraînement](https://github.com/votre-compte/dataset-hydrologique-247-bassins-espagne)** *(Lien vers le dépôt du dataset)*

Ce dépôt dédié comprend :
* La matrice complète des 19 attributs physiographiques et hydroclimatiques.
* Les contours géographiques vectoriels des 247 bassins (GeoJSON & GPKG).
* Les paramètres calibrés du modèle conceptuel benchmark **GR4J** ($X_1, X_2, X_3, X_4$).
* Les critères d'exclusion et de filtrage qualité (passage de 269 à 247 bassins).

---

## 🚀 Guide de Démarrage & Lancement

### Option A : Lancement en 1 Clic via GitHub Codespaces (Recommandé)

Aucune installation locale requise. Codespaces configure automatiquement l'environnement Linux avec GDAL, PyTorch et Django :
1. Cliquez sur le bouton **Open in GitHub Codespaces** en haut de cette page.
2. Une fois le terminal chargé, lancez simplement :
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```
3. L'application s'ouvre automatiquement dans votre navigateur.

---

### Option B : Installation Locale (Windows / Linux / macOS)

#### 1. Prérequis Système
* Python 3.10, 3.11 ou 3.12.
* Bibliothèques C++ géospatiales (GDAL, GEOS, PROJ) installées sur votre système (ou via Conda/OSGeo4W).

#### 2. Clonage et Environnement Virtuel
```bash
git clone https://github.com/votre-compte/HYDRO_WEB_APP.git
cd HYDRO_WEB_APP

# Création de l'environnement virtuel
python -m venv venv

# Activation (Windows PowerShell)
.\venv\Scripts\Activate.ps1
# Activation (Linux / macOS)
source venv/bin/activate
```

#### 3. Installation des Dépendances
```bash
pip install --upgrade pip

# Installation de PyTorch CPU (recommandé pour inférence rapide sans GPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Installation des dépendances du projet
pip install -r requirements.txt
```

#### 4. Initialisation et Lancement
```bash
# Vérification de l'intégrité Django
python manage.py check

# Application des migrations
python manage.py migrate

# Lancement du serveur local
python manage.py runserver
```
Accédez ensuite à l'adresse : **`http://127.0.0.1:8000/`**.

---

## 📂 Structure des Fichiers

```text
HYDRO_WEB_APP/
├── .devcontainer/                  # Configuration pour GitHub Codespaces (1 clic)
│   └── devcontainer.json
├── core/                           # Application Django principale
│   ├── api_views.py                # Endpoints REST (délinéation, simulation, barrages, rivières)
│   ├── views.py                    # Vue dashboard et stations de référence
│   └── models.py                   # Modèle de persistance des simulations (SQLite)
├── gis_engine/                     # Moteur géomatique & spatial
│   ├── delineator.py               # Algorithme D8 pyflwdir sur MNT HydroSHEDS
│   ├── anthropogenic_audit.py      # Détection et calcul de retenue des barrages amont
│   ├── attributes_calculator.py    # Calcul des 8 descripteurs physiographiques
│   └── gpkg_reader.py              # Lecteur optimisé multi-couches GeoPackage
├── hydro_model/                    # Moteur d'apprentissage profond
│   ├── lstm_net.py                 # Classe HydroLSTM PyTorch
│   ├── inference.py                # Pipeline d'inférence journalière/mensuelle
│   ├── scaler.py                   # Normalisation Z-score anti-fuite
│   └── forcing_service.py          # Gestionnaire des forçages météo ERA5-Land
├── models/
│   └── temporal_model/             # Poids du modèle Époque 25 (247 bassins)
│       ├── model_epoch025.pt
│       ├── train_data_scaler.yml
│       └── config.yml
├── data/                           # Données spatiales & hydrométriques prêtes
│   ├── hysheds_dir_maroc.tif       # MNT D8 direction HydroSHEDS (33.8 Mo)
│   ├── catchments_new_stations.gpkg# 9 stations de jaugeage certifiées
│   ├── attributes_stations_maroc.csv
│   ├── observed_monthly_9_stations.csv
│   ├── forcings_9_stations_era5.parquet
│   ├── dams_morocco_inventory.geojson # 45 grands barrages du Maroc
│   └── morocco_rivers_light.geojson   # Réseau des oueds HydroRIVERS
├── static/                         # Feuilles de style, JS et assets
│   └── js/app.js                   # Contrôleur Alpine.js + Leaflet.js
├── templates/                      # Gabarits HTML Tailwind + Alpine.js
│   ├── dashboard.html
│   └── components/                 # audit_card.html, hydrograph_chart.html, etc.
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🎓 Citation & Référence Académique

Si vous utilisez cette plateforme ou ses composants dans le cadre de travaux de recherche :

```bibtex
@mastersthesis{ayach2026pfe,
  author       = {Ayach, Mohamed Chawki},
  title        = {Modélisation pluie-débit en milieu semi-aride non jaugé par Deep Learning régionalisé : transfert transfrontalier et évaluation in situ au Maroc},
  school       = {Institut Agronomique et Vétérinaire Hassan II (IAV), Rabat, Maroc},
  year         = {2026},
  type         = {Mémoire de Projet de Fin d'Études en Génie Rural}
}
```
