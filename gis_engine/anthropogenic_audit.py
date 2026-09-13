import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np
import shapely
from shapely.geometry import shape, Point


class AnthropogenicAuditor:
    """
    Moteur d'audit hydrologique et de détection d'influence anthropique :
    1. Détecte la présence de grands barrages en amont (Point-in-Polygon).
    2. Identifie si l'exutoire est sur un Grand Oued / Axe fluvial majeur ou en tête de bassin.
    3. Évalue le régime d'écoulement (Naturel vs Régulé/Artificiel) et son impact sur la prédiction LSTM.
    """
    _instance: Optional["AnthropogenicAuditor"] = None

    def __init__(self, data_path: Optional[Path] = None):
        if data_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            data_path = base_dir / "data" / "dams_morocco_inventory.json"
            if not data_path.exists():
                data_path = base_dir / "data_update_9stations" / "dams_morocco_inventory.json"

        self.data_path = Path(data_path)
        self.dams: List[Dict[str, Any]] = []

        if self.data_path.exists():
            with open(self.data_path, "r", encoding="utf-8") as f:
                self.dams = json.load(f)

    @classmethod
    def get_instance(cls, data_path: Optional[Path] = None) -> "AnthropogenicAuditor":
        if cls._instance is None:
            cls._instance = cls(data_path=data_path)
        return cls._instance

    def audit(self, catchment_geom: Any, outlet_lat: float, outlet_lon: float, area_km2: float) -> Dict[str, Any]:
        """
        Exécute l'audit spatial complet pour un bassin délinéé :
        - catchment_geom : Dict GeoJSON geometry ou objet Shapely
        - outlet_lat, outlet_lon : Coordonnées de l'exutoire
        - area_km2 : Superficie du bassin versant
        """
        if isinstance(catchment_geom, dict):
            poly = shape(catchment_geom)
        else:
            poly = catchment_geom

        outlet_pt = Point(outlet_lon, outlet_lat)

        upstream_dams = []
        total_capacity = 0.0

        for dam in self.dams:
            dam_pt = Point(dam["lon"], dam["lat"])

            # Vérifier si le barrage est situé à l'intérieur du bassin versant
            if poly.contains(dam_pt):
                # Calculer la distance géographique approximative entre le barrage et l'exutoire
                dist_km = float(np.hypot((dam["lat"] - outlet_lat) * 111.0, (dam["lon"] - outlet_lon) * 111.0 * np.cos(np.radians(outlet_lat))))

                # Si le barrage est à moins de 1.2 km de l'exutoire, c'est l'exutoire lui-même qui correspond au barrage
                # (l'utilisateur cherche alors à évaluer les apports ENTRANTS dans ce barrage)
                if dist_km < 1.2:
                    continue

                cap = float(dam.get("capacity_hm3", 0.0))
                total_capacity += cap
                upstream_dams.append({
                    "name": dam["name"],
                    "river": dam["river"],
                    "basin": dam["basin"],
                    "capacity_hm3": cap,
                    "year": dam.get("year"),
                    "purpose": dam.get("purpose", "Irrigation / Eau Potable"),
                    "lat": dam["lat"],
                    "lon": dam["lon"],
                    "distance_upstream_km": round(dist_km, 1)
                })

        # Trier les barrages amont par capacité décroissante
        upstream_dams.sort(key=lambda d: d["capacity_hm3"], reverse=True)
        count = len(upstream_dams)

        # Classification de l'échelle du cours d'eau (Grand Oued vs Affluent)
        if area_km2 >= 5000:
            scale_type = "Fleuve / Grand Oued Régional Majeur"
            scale_status = "warning"
            scale_desc = f"Bassin de très grande taille ({area_km2:.0f} km²), transit fluvial long avec potentiel d'amortissement hydraulique."
        elif area_km2 >= 3500:
            scale_type = "Grand Cours d'Eau (Limite d'enveloppe)"
            scale_status = "warning"
            scale_desc = f"Superficie ({area_km2:.0f} km²) proche du plafond opérationnel (3 500 km²)."
        elif area_km2 >= 200:
            scale_type = "Bassin Versant Moyen Standard"
            scale_status = "valid"
            scale_desc = f"Échelle optimale ({area_km2:.0f} km²) correspondant à la plage de performance maximale du modèle LSTM."
        else:
            scale_type = "Sous-bassin Amont / Tête de Bassin"
            scale_status = "valid"
            scale_desc = f"Bassin de tête ({area_km2:.1f} km²), réponse pluie-débit rapide et dynamique torrentielle."

        # Diagnostic de Régime d'Écoulement
        if count == 0:
            regime = "Naturel"
            regime_status = "natural"  # Vert
            badge_color = "emerald"
            badge_icon = "fa-circle-check"
            title = "Régime Naturel (Bassin Vierge / Non Régulé)"
            message = "Aucun grand barrage détecté en amont dans ce bassin versant. Les écoulements sont libres et naturels."
            recommendation = "Excellentes conditions pour le modèle Deep Learning LSTM : la simulation correspond au comportement hydrologique réel non influencé."
        elif total_capacity < 20.0:
            regime = "Faiblement Influencé"
            regime_status = "warning"  # Orange
            badge_color = "amber"
            badge_icon = "fa-triangle-exclamation"
            title = f"Régime Faiblement Influencé ({total_capacity:.1f} hm³ de stockage amont)"
            dam_names = ", ".join([d["name"] for d in upstream_dams])
            message = f"Présence de {count} aménagement(s) hydraulique(s) en amont ({dam_names}) totalisant {total_capacity:.1f} hm³ de capacité."
            recommendation = "Impact modéré sur les étiages et les petites crues. Les pointes majeures restent perceptibles."
        else:
            regime = "Fortement Régulé"
            regime_status = "regulated"  # Rouge
            badge_color = "rose"
            badge_icon = "fa-triangle-exclamation"
            title = f"Régime Régulé par Barrage Amont ({total_capacity:,.0f} hm³ stockés)"
            dam_names = ", ".join([d["name"] for d in upstream_dams[:3]])
            if count > 3:
                dam_names += f" et {count - 3} autres"
            message = f"Attention : Le bassin versant est situé en aval de {count} grand(s) barrage(s) ({dam_names}) cumulant {total_capacity:,.0f} hm³ de stockage."
            recommendation = "Important : Le modèle LSTM calcule les apports naturels bruts (pluie-débit vierge). Le débit réel observé à cet exutoire dépendra des consignes d'exploitation du barrage (lâchers d'eau, turbinage hydroélectrique, soutirages AEP/irrigation)."

        return {
            "regime": regime,
            "regime_status": regime_status,
            "badge_color": badge_color,
            "badge_icon": badge_icon,
            "title": title,
            "message": message,
            "recommendation": recommendation,
            "upstream_dams_count": count,
            "total_storage_capacity_hm3": round(total_capacity, 1),
            "total_upstream_capacity_Mm3": round(total_capacity, 1),
            "upstream_dams": upstream_dams,
            "scale": {
                "type": scale_type,
                "status": scale_status,
                "description": scale_desc
            }
        }
