import numpy as np
import pandas as pd
import torch
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from .lstm_net import HydroLSTM, load_trained_model
from .scaler import HydroDataScaler


def calc_kge(obs: np.ndarray, sim: np.ndarray) -> float:
    """Calcul du critère de Kling-Gupta Efficiency (KGE)"""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    o, s = obs[mask], sim[mask]
    if len(o) < 10 or np.std(o) == 0 or np.std(s) == 0:
        return float("nan")
    r = np.corrcoef(o, s)[0, 1]
    alpha = np.std(s) / np.std(o)
    beta = np.mean(s) / np.mean(o)
    return float(1.0 - np.sqrt((r - 1.0)**2 + (alpha - 1.0)**2 + (beta - 1.0)**2))


def calc_nse(obs: np.ndarray, sim: np.ndarray) -> float:
    """Calcul du critère de Nash-Sutcliffe Efficiency (NSE)"""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    o, s = obs[mask], sim[mask]
    if len(o) < 10 or np.sum((o - np.mean(o))**2) == 0:
        return float("nan")
    return float(1.0 - np.sum((o - s)**2) / np.sum((o - np.mean(o))**2))


def calc_pbias(obs: np.ndarray, sim: np.ndarray) -> float:
    """Calcul du biais en pourcentage (PBIAS)"""
    mask = ~(np.isnan(obs) | np.isnan(sim))
    o, s = obs[mask], sim[mask]
    if len(o) < 10 or np.sum(o) == 0:
        return float("nan")
    return float(100.0 * np.sum(s - o) / np.sum(o))


class HydroInferenceEngine:
    """
    Moteur central d'inférence hydrologique par Deep Learning (LSTM).
    Gère la mise en séquence, le forward pass PyTorch et les conversions d'unités.
    """
    _instance: Optional["HydroInferenceEngine"] = None
    _lock = threading.Lock()

    def __init__(self, weights_path: Optional[str] = None, scaler_path: Optional[str] = None, device: str = "cpu"):
        self.device = device
        self.model: HydroLSTM = load_trained_model(weights_path=weights_path, device=device)
        self.scaler: HydroDataScaler = HydroDataScaler(scaler_path=scaler_path)

    @classmethod
    def get_instance(cls, weights_path: Optional[str] = None, scaler_path: Optional[str] = None, device: str = "cpu") -> "HydroInferenceEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(weights_path=weights_path, scaler_path=scaler_path, device=device)
        return cls._instance

    def predict(self, df_forcing: pd.DataFrame, attrs: Dict[str, Any], obs_monthly: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Exécute la simulation complète :
        - df_forcing : DataFrame avec dates et [prcp_mm, tmin_c, tmax_c, pet_mm]
        - attrs : Dict des 8 attributs physiques
        - obs_monthly : Optionnel, DataFrame avec ['date', 'I_corr'] pour le benchmark des barrages
        """
        area_km2 = float(attrs.get("area_km2", 100.0))

        # 1. Construction de la séquence normalisée (seq_len, 12)
        X = self.scaler.build_input_sequence(df_forcing, attrs)
        X_tensor = torch.tensor(X, dtype=torch.float32).unsqueeze(0).to(self.device)

        # 2. Inférence PyTorch
        with torch.no_grad():
            y_norm = self.model(X_tensor)
            y_norm = y_norm.squeeze(0).squeeze(-1).cpu().numpy()

        # 3. Dénormalisation en lame d'eau (mm/j)
        q_sim_mm = self.scaler.denormalize_output(y_norm)

        # Garde-fou hydrologique strict de conservation de masse (bilan hydrologique)
        # En régime méditerranéen/semi-aride, le coefficient d'écoulement annuel C = Q / P est physiquement borné
        total_p = float(np.nansum(df_forcing["prcp_mm"].values))
        total_q = float(np.nansum(q_sim_mm))
        if total_p > 10.0 and total_q > 0.0:
            raw_c = total_q / total_p
            aridity = float(attrs.get("aridity", 1.5))
            # Plafond réaliste d'écoulement selon l'aridité (Chapitre 4 & 5 du PFE)
            max_c = 0.55 if aridity <= 1.6 else (0.35 if aridity <= 2.2 else 0.18)
            if raw_c > max_c:
                correction = max_c / raw_c
                q_sim_mm = q_sim_mm * correction

        # 4. Conversion en débit (m³/s)
        q_sim_m3s = self.scaler.mm_to_m3s(q_sim_mm, area_km2)

        dates = pd.to_datetime(df_forcing["date"]).dt.strftime("%Y-%m-%d").tolist()
        df_daily = pd.DataFrame({
            "date": dates,
            "prcp_mm": np.round(df_forcing["prcp_mm"].values, 2),
            "pet_mm": np.round(df_forcing["pet_mm"].values, 2),
            "tmin_c": np.round(df_forcing["tmin_c"].values, 1),
            "tmax_c": np.round(df_forcing["tmax_c"].values, 1),
            "q_sim_mm": np.round(q_sim_mm, 3),
            "q_sim_m3s": np.round(q_sim_m3s, 3)
        })

        # 5. Agrégation mensuelle (hm³/mois)
        df_monthly = self.scaler.mm_to_monthly_hm3(df_daily, area_km2)
        df_monthly["month_str"] = df_monthly["date"].dt.strftime("%Y-%m")
        df_monthly["date"] = df_monthly["date"].dt.strftime("%Y-%m-%d")

        # 6. Comparaison avec observations in situ si disponibles (exclusivement pour les 9 stations)
        metrics = {"has_obs": False}
        if obs_monthly is not None and not obs_monthly.empty:
            obs_clean = obs_monthly.copy()
            if "month_str" not in obs_clean.columns and "date" in obs_clean.columns:
                obs_clean["month_str"] = pd.to_datetime(obs_clean["date"]).dt.strftime("%Y-%m")

            merged = pd.merge(df_monthly, obs_clean, on="month_str", how="inner", suffixes=("_sim", "_obs"))

            # Vérifier la présence de volume ou débit observé
            obs_col = None
            if "vol_obs_hm3" in merged.columns:
                obs_col = "vol_obs_hm3"
                sim_col = "sim_hm3"
            elif "I_corr" in merged.columns:
                obs_col = "I_corr"
                sim_col = "sim_hm3"
            elif "q_obs_m3s" in merged.columns:
                obs_col = "q_obs_m3s"
                sim_col = "q_mean_m3s"

            if obs_col is not None and not merged.empty:
                obs_vals = merged[obs_col].astype(float).values
                sim_vals = merged[sim_col].astype(float).values

                valid_mask = ~(np.isnan(obs_vals) | np.isnan(sim_vals))
                o_v = obs_vals[valid_mask]
                s_v = sim_vals[valid_mask]

                if len(o_v) >= 5:
                    kge_val = calc_kge(o_v, s_v)
                    nse_val = calc_nse(o_v, s_v)
                    pbias_val = calc_pbias(o_v, s_v)
                    metrics = {
                        "KGE_monthly": round(float(kge_val), 3) if not np.isnan(kge_val) else None,
                        "NSE_monthly": round(float(nse_val), 3) if not np.isnan(nse_val) else None,
                        "PBIAS_pct": round(float(pbias_val), 1) if not np.isnan(pbias_val) else None,
                        "mean_annual_sim_hm3": round(float(np.nanmean(sim_vals) * 12.0), 1),
                        "mean_annual_obs_hm3": round(float(np.nanmean(obs_vals) * 12.0), 1),
                        "has_obs": True
                    }
                    # Injecter les observations dans le DataFrame mensuel pour Chart.js
                    vol_key = "vol_obs_hm3" if "vol_obs_hm3" in merged.columns else ("I_corr" if "I_corr" in merged.columns else obs_col)
                    df_monthly["obs_hm3"] = df_monthly["month_str"].map(dict(zip(merged["month_str"], merged[vol_key])))
                    if "q_obs_m3s" in merged.columns:
                        df_monthly["obs_q_m3s"] = df_monthly["month_str"].map(dict(zip(merged["month_str"], merged["q_obs_m3s"])))

        # Résumé statistique
        stats = {
            "total_precip_mm": round(float(np.sum(df_daily["prcp_mm"])), 1),
            "total_sim_volume_hm3": round(float(np.sum(df_monthly["sim_hm3"])), 2),
            "mean_sim_discharge_m3s": round(float(np.mean(q_sim_m3s)), 2),
            "peak_sim_discharge_m3s": round(float(np.max(q_sim_m3s)), 2),
            "mean_sim_runoff_mm": round(float(np.sum(q_sim_mm)), 1),
            "runoff_coefficient": round(float(np.sum(q_sim_mm) / max(np.sum(df_daily["prcp_mm"]), 1e-3)), 3)
        }

        return {
            "daily": df_daily.to_dict(orient="records"),
            "monthly": df_monthly.fillna("").to_dict(orient="records"),
            "stats": stats,
            "metrics": metrics
        }
