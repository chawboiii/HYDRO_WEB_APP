import os
import torch
import torch.nn as nn
from pathlib import Path


class HydroLSTM(nn.Module):
    """
    Architecture PyTorch du LSTM Régionalisé (128 unités cachées, Dropout 0.5, Head Régression Linéaire).
    Entrées (12) : 4 forçages dynamiques (prcp_mm, tmin_c, tmax_c, pet_mm)
                 + 8 attributs statiques répétés sur la séquence temporelle.
    Sortie (1) : Lame d'eau journalière normalisée (qobs_mm).
    """
    def __init__(self, input_size: int = 12, hidden_size: int = 128, dropout: float = 0.5):
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.lstm = nn.LSTM(input_size=input_size, hidden_size=hidden_size, batch_first=True)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: Tensor de forme (batch_size, seq_len, input_size)
        Retourne: Tensor de forme (batch_size, seq_len, 1) ou (batch_size, 1)
        """
        out, (h_n, c_n) = self.lstm(x)
        out = self.dropout(out)
        out = self.head(out)
        return out


from typing import Optional


def load_trained_model(weights_path: Optional[str] = None, device: str = "cpu") -> HydroLSTM:
    """
    Charge les poids neuronaux du modèle temporel de référence (ex: model_epoch025.pt, ou tout motif model_epoch2*.pt)
    dans le réseau HydroLSTM.
    """
    base_dir = Path(__file__).resolve().parent.parent
    temporal_dir = base_dir / "models" / "temporal_model"
    fallback_dir = base_dir / "data_update_9stations" / "temporal_model_weights"

    resolved_path = None

    if weights_path:
        w_path = Path(weights_path)
        if w_path.exists():
            resolved_path = w_path
        else:
            # Recherche par nom ou motif glob dans temporal_dir puis fallback_dir
            pattern = str(weights_path)
            for search_dir in [temporal_dir, fallback_dir]:
                if search_dir.exists():
                    matches = sorted(list(search_dir.glob(pattern)), reverse=True)
                    if matches:
                        resolved_path = matches[0]
                        break

    if resolved_path is None:
        # Recherche prioritaire du modèle temporel (model_epoch025.pt, KGE médian 0.619)
        candidates = [
            temporal_dir / "model_epoch025.pt",
            fallback_dir / "model_epoch025.pt",
            temporal_dir / "model_epoch020.pt",
            fallback_dir / "model_epoch020.pt"
        ]
        # Recherche aussi tout fichier correspondant à model_epoch2*.pt ou model_epoch02*.pt
        for search_dir in [temporal_dir, fallback_dir]:
            if search_dir.exists():
                for glob_pat in ["model_epoch2*.pt", "model_epoch02*.pt", "model_epoch*2*.pt"]:
                    for m in sorted(search_dir.glob(glob_pat), reverse=True):
                        if m not in candidates:
                            candidates.insert(0, m)

        for c in candidates:
            if c.exists():
                resolved_path = c
                break

    if resolved_path is None or not resolved_path.exists():
        raise FileNotFoundError(f"Fichier de poids du modèle temporel introuvable dans {temporal_dir} ou {fallback_dir}")

    print(f"[HydroLSTM] Modèle temporel chargé avec succès : {resolved_path.name}")
    model = HydroLSTM(input_size=12, hidden_size=128, dropout=0.5)
    ckpt = torch.load(str(resolved_path), map_location=torch.device(device), weights_only=True)

    # Adapter les clés si le checkpoint provient de neuralhydrology (ex: head.net.0.* -> head.0.*)
    adapted_dict = {}
    for k, v in ckpt.items():
        if k.startswith("head.net."):
            adapted_key = k.replace("head.net.", "head.")
            adapted_dict[adapted_key] = v
        else:
            adapted_dict[k] = v

    model.load_state_dict(adapted_dict, strict=True)
    model.to(device)
    model.eval()
    return model

