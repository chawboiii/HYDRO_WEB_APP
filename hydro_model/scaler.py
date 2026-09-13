import yaml
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Union


class HydroDataScaler:
    """
    Gestionnaire de mise à l'échelle des variables d'entrée et de sortie du modèle LSTM,
    chargé directement à partir du fichier exact train_data_scaler.yml.
    """
    STATIC_ATTRS = [
        "area_km2",
        "elev_mean",
        "slope_mean",
        "forest_frac",
        "aridity",
        "p_mean",
        "frac_snow",
        "p_seasonality",
    ]

    DYNAMIC_VARS = ["prcp_mm", "tmin_c", "tmax_c", "pet_mm"]

    def __init__(self, scaler_path: Union[str, Path] = None):
        if scaler_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            primary_path = base_dir / "models" / "temporal_model" / "train_data_scaler.yml"
            fallback_path = base_dir / "data_update_9stations" / "temporal_model_weights" / "train_data_scaler.yml"
            scaler_path = primary_path if primary_path.exists() else fallback_path

        scaler_path = Path(scaler_path)
        if not scaler_path.exists():
            raise FileNotFoundError(f"Fichier scaler introuvable: {scaler_path}")

        with open(scaler_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        self.attribute_means: Dict[str, float] = cfg.get("attribute_means", {})
        self.attribute_stds: Dict[str, float] = cfg.get("attribute_stds", {})

        feat_center = cfg.get("xarray_feature_center", {}).get("data_vars", {})
        feat_scale = cfg.get("xarray_feature_scale", {}).get("data_vars", {})

        self.feature_centers: Dict[str, float] = {k: float(v["data"]) if isinstance(v, dict) else float(v) for k, v in feat_center.items()}
        self.feature_scales: Dict[str, float] = {k: float(v["data"]) if isinstance(v, dict) else float(v) for k, v in feat_scale.items()}

    def normalize_static_attributes(self, attrs: Dict[str, float]) -> np.ndarray:
        """
        Normalise les 8 attributs statiques : (attr - mean) / std.
        Retourne un vecteur numpy 1D de 8 éléments.
        """
        normed = []
        for name in self.STATIC_ATTRS:
            val = float(attrs.get(name, 0.0))
            mean = self.attribute_means.get(name, 0.0)
            std = self.attribute_stds.get(name, 1.0)
            if std == 0:
                std = 1.0
            norm_val = (val - mean) / std
            # Robustesse anti-saturation des portes LSTM (garde-fou out-of-distribution)
            normed.append(float(np.clip(norm_val, -3.0, 3.0)))
        return np.array(normed, dtype=np.float32)

    def normalize_dynamic_inputs(self, df_forcing: pd.DataFrame) -> np.ndarray:
        """
        Normalise les 4 forçages météorologiques journaliers (T, 4) : (x - center) / scale.
        df_forcing doit contenir les colonnes: prcp_mm, tmin_c, tmax_c, pet_mm.
        """
        data = []
        for col in self.DYNAMIC_VARS:
            val = df_forcing[col].astype(float).values
            center = self.feature_centers.get(col, 0.0)
            scale = self.feature_scales.get(col, 1.0)
            if scale == 0:
                scale = 1.0
            data.append((val - center) / scale)
        return np.column_stack(data).astype(np.float32)

    def build_input_sequence(self, df_forcing: pd.DataFrame, attrs: Dict[str, float]) -> np.ndarray:
        """
        Construit la matrice d'entrée (seq_len, 12) prête pour le LSTM :
        Concaténation des 4 variables dynamiques normalisées et des 8 attributs statiques répétés.
        """
        dyn_norm = self.normalize_dynamic_inputs(df_forcing)
        stat_norm = self.normalize_static_attributes(attrs)

        seq_len = len(df_forcing)
        # Répéter les 8 attributs statiques sur toute la séquence temporelle
        stat_matrix = np.tile(stat_norm, (seq_len, 1))

        # Matrice finale (seq_len, 12)
        X = np.hstack([dyn_norm, stat_matrix])
        return X.astype(np.float32)

    def denormalize_output(self, y_pred_norm: np.ndarray) -> np.ndarray:
        """
        Dénormalise la prédiction du modèle en lame d'eau simulée journalière qobs_mm:
        sim_mm = y_norm * scale + center.
        On applique une borne inférieure à 0 mm/j (lame d'eau physique non négative).
        """
        center = self.feature_centers.get("qobs_mm", 0.7070284)
        scale = self.feature_scales.get("qobs_mm", 1.8443305)
        sim_mm = y_pred_norm * scale + center
        return np.clip(sim_mm, 0.0, None)

    @staticmethod
    def mm_to_m3s(q_mm: np.ndarray, area_km2: float) -> np.ndarray:
        """
        Convertit la lame d'eau journalière (mm/j) en débit moyen journalier (m³/s) :
        Q = q_mm * (area_km2 * 1e6 * 1e-3) / 86400 = q_mm * area_km2 / 86.4
        """
        return (q_mm * area_km2) / 86.4

    @staticmethod
    def mm_to_monthly_hm3(df_daily: pd.DataFrame, area_km2: float) -> pd.DataFrame:
        """
        Agrège les lames d'eau ou débits journaliers en cumul mensuel (hm³/mois) :
        Vol_hm3 = q_mm * area_km2 / 1000.
        """
        df = df_daily.copy()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")

        df["vol_daily_hm3"] = (df["q_sim_mm"] * area_km2) / 1000.0
        monthly = df.resample("MS").agg({
            "vol_daily_hm3": "sum",
            "q_sim_m3s": "mean",
            "q_sim_mm": "sum"
        }).reset_index()

        monthly = monthly.rename(columns={
            "vol_daily_hm3": "sim_hm3",
            "q_sim_m3s": "q_mean_m3s",
            "q_sim_mm": "sim_monthly_mm"
        })
        return monthly
