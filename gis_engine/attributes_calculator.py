import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional

from .envelope_evaluator import evaluate_operational_envelope


class AttributesCalculator:
    """
    Calculateur et gestionnaire des 8 attributs physiques & climatiques statiques
    anti-fuite du modèle LSTM :
    - 4 Topo/Sol : area_km2, elev_mean, slope_mean, forest_frac
    - 4 Climat 10 ans : p_mean, aridity, frac_snow, p_seasonality
    """
    def __init__(self, data_dir: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parent.parent
        if data_dir is None:
            data_dir = base_dir / "data"
        self.data_dir = Path(data_dir)

        # Tables de référence officielles du PFE
        st_primary = self.data_dir / "attributes_stations_maroc.csv"
        st_fallback = base_dir / "data_update_9stations" / "attributes_stations_maroc.csv"
        self.stations_csv = st_primary if st_primary.exists() else st_fallback

        self.maroc_csv = self.data_dir / "attributes_maroc.csv"
        self.dams_csv = self.data_dir / "attributes_dams.csv"
        self.pooled_csv = self.data_dir / "attributes_pooled.csv"

        self._df_stations = pd.read_csv(self.stations_csv) if self.stations_csv.exists() else pd.DataFrame()
        self._df_maroc = pd.read_csv(self.maroc_csv) if self.maroc_csv.exists() else pd.DataFrame()
        self._df_dams = pd.read_csv(self.dams_csv) if self.dams_csv.exists() else pd.DataFrame()
        self._df_pooled = pd.read_csv(self.pooled_csv) if self.pooled_csv.exists() else pd.DataFrame()

    def get_reference_attributes(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Cherche si le bassin correspond à une référence certifiée :
        Priorité absolue aux 9 stations de jaugeage marocaines (Loukkos et Oum Er Rbia).
        """
        ident = str(identifier).strip().lower()

        # 1. Stations de Jaugeage Marocaines (Loukkos & Oum Er Rbia)
        if not self._df_stations.empty and "code" in self._df_stations.columns:
            for _, row in self._df_stations.iterrows():
                code_str = str(row.get("code", "")).strip().lower()
                name_str = str(row.get("name", "")).strip().lower()
                if ident in (code_str, name_str) or ident == f"{name_str} ({code_str})" or code_str in ident:
                    r = row.to_dict()
                    r["name"] = f"{row['name']} ({row['code']})"
                    return self._format_attributes_dict(r, source="Reference_Stations_Maroc")

        # 2. Barrages Marocains
        if not self._df_maroc.empty and "nom" in self._df_maroc.columns:
            m = self._df_maroc[self._df_maroc["nom"].str.lower() == ident]
            if not m.empty:
                r = m.iloc[0].to_dict()
                return self._format_attributes_dict(r, source="Reference_Maroc_PFE")

        # 3. Barrages Espagnols (Bridge)
        if not self._df_dams.empty and "indroea" in self._df_dams.columns:
            clean_id = ident if ident.startswith("dam_") else f"dam_{ident}"
            m = self._df_dams[(self._df_dams["indroea"].str.lower() == ident) | (self._df_dams["indroea"].str.lower() == clean_id)]
            if not m.empty:
                r = m.iloc[0].to_dict()
                return self._format_attributes_dict(r, source="Reference_Bridge_Spain")

        # 4. 269 bassins de référence espagnols
        if not self._df_pooled.empty and "indroea" in self._df_pooled.columns:
            m = self._df_pooled[self._df_pooled["indroea"].astype(str).str.lower() == ident]
            if not m.empty:
                r = m.iloc[0].to_dict()
                return self._format_attributes_dict(r, source="Reference_Pooled_269")

        return None

    def calculate_custom_attributes(self, area_km2: float, lat: float, lon: float, df_forcing: pd.DataFrame, basin_name: str = "Bassin Délinéé") -> Dict[str, Any]:
        """
        Calcule les 8 attributs physiques à partir d'un bassin délinéé et de sa série de forçages journaliers.
        """
        # 1. Calcul des 4 attributs climatiques
        p = df_forcing["prcp_mm"].values
        pet = df_forcing["pet_mm"].values
        tm = (df_forcing["tmin_c"].values + df_forcing["tmax_c"].values) / 2.0

        p_mean = float(np.nanmean(p))
        pet_mean = float(np.nanmean(pet))
        aridity = float(pet_mean / max(p_mean, 1e-3))

        total_p = float(np.nansum(p))
        snow_p = float(np.nansum(p[tm < 0]))
        frac_snow = float(snow_p / max(total_p, 1e-3))

        # Saisonnalité mensuelle (Woods, 2009 / CAMELS)
        # Bounded to match the regional training distribution [0.5, 1.55]
        dates = pd.to_datetime(df_forcing["date"])
        mon = df_forcing.groupby(dates.dt.month)["prcp_mm"].mean()
        mon_mean = float(mon.mean())
        if mon_mean > 0:
            raw_seasonality = float((mon.max() - mon.min()) / mon_mean)
            # Écrêtage sur la distribution exacte d'entraînement (moyenne 1.04, std 0.30)
            p_seasonality = float(np.clip(raw_seasonality, 0.50, 1.55))
        else:
            p_seasonality = 1.04

        # Sécurisation de l'aridité (bornes physiques régionales)
        aridity = float(np.clip(aridity, 0.40, 3.80))
        frac_snow = float(np.clip(frac_snow, 0.0, 0.30))

        # 2. Estimation des 4 attributs topographiques/sol régionaux
        # Approximation régionale basée sur la position orographique
        is_high_atlas = (30.5 <= lat <= 32.5) and (-9.0 <= lon <= -5.5)
        is_middle_atlas = (32.5 <= lat <= 34.0) and (-6.0 <= lon <= -4.0)
        is_rif = (34.5 <= lat <= 35.5) and (-6.0 <= lon <= -3.5)

        if is_high_atlas:
            elev_mean = 1950.0 - abs(lon + 7.5) * 80.0
            slope_mean = 14.5
            forest_frac = 0.12
        elif is_middle_atlas:
            elev_mean = 1450.0
            slope_mean = 10.5
            forest_frac = 0.28
        elif is_rif:
            elev_mean = 850.0
            slope_mean = 12.0
            forest_frac = 0.32
        else:
            # Plaines et plateaux côtiers ou semi-arides
            elev_mean = max(250.0, 700.0 - abs(lon + 7.0) * 50.0)
            slope_mean = 6.5
            forest_frac = 0.08

        elev_mean = float(np.clip(elev_mean, 150.0, 2400.0))
        slope_mean = float(np.clip(slope_mean, 1.5, 22.0))
        forest_frac = float(np.clip(forest_frac, 0.01, 0.85))

        raw = {
            "name": basin_name,
            "area_km2": round(area_km2, 2),
            "elev_mean": round(float(elev_mean), 1),
            "slope_mean": round(float(slope_mean), 2),
            "forest_frac": round(float(forest_frac), 3),
            "p_mean": round(p_mean, 3),
            "pet_mean": round(pet_mean, 3),
            "aridity": round(aridity, 3),
            "frac_snow": round(frac_snow, 4),
            "p_seasonality": round(p_seasonality, 3),
        }

        return self._format_attributes_dict(raw, source="Calculated_ERA5_Topography")

    def _format_attributes_dict(self, d: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Ajoute l'évaluation de l'enveloppe opérationnelle et formate les métadonnées"""
        attrs = {
            "area_km2": float(d.get("area_km2", 0.0)),
            "elev_mean": float(d.get("elev_mean", 0.0)),
            "slope_mean": float(d.get("slope_mean", 0.0)),
            "forest_frac": float(d.get("forest_frac", 0.0)),
            "p_mean": float(d.get("p_mean", 0.0)),
            "pet_mean": float(d.get("pet_mean", 0.0)),
            "aridity": float(d.get("aridity", 0.0)),
            "frac_snow": float(d.get("frac_snow", 0.0)),
            "p_seasonality": float(d.get("p_seasonality", 0.0)),
        }

        envelope = evaluate_operational_envelope(attrs)

        return {
            "name": d.get("nom", d.get("name", d.get("dam", d.get("indroea", "Bassin")))),
            "source": source,
            "attributes": attrs,
            "envelope": envelope,
            "raw": d
        }
