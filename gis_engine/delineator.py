import time
import threading
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import numpy as np
from PIL import Image
from affine import Affine
import pyflwdir
from rasterio.features import shapes
import shapely
from shapely.geometry import Polygon, MultiPolygon, mapping, shape
from shapely.ops import unary_union


class MoroccoDelineator:
    """
    Moteur de délinéation de bassins versants amont pour le Maroc,
    utilisant pyflwdir et le MNT D8 HydroSHEDS (data/hysheds_dir_maroc.tif).
    """
    _instance: Optional["MoroccoDelineator"] = None
    _lock = threading.Lock()

    def __init__(self, tif_path: Optional[Path] = None):
        if tif_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            tif_path = base_dir / "data" / "hysheds_dir_maroc.tif"
        self.tif_path = Path(tif_path)
        if not self.tif_path.exists():
            raise FileNotFoundError(f"Fichier MNT D8 introuvable: {self.tif_path}")

        Image.MAX_IMAGE_PIXELS = None
        self._im = Image.open(str(self.tif_path))
        tags = self._im.tag_v2
        scale = tags.get(33550, (0.00083336708907768, 0.00083336708907768, 0.0))
        tiepoint = tags.get(33922, (0.0, 0.0, 0.0, -13.500546843058416, 36.36313956481549, 0.0))

        dx, dy = float(scale[0]), -float(scale[1])
        x0, y0 = float(tiepoint[3]), float(tiepoint[4])
        self.transform = Affine.translation(x0, y0) * Affine.scale(dx, dy)
        self.inv_transform = ~self.transform

        self.width, self.height = self._im.size  # (15001, 10636)
        self.valid_d8 = {0, 1, 2, 4, 8, 16, 32, 64, 128}

    @classmethod
    def get_instance(cls, tif_path: Optional[Path] = None) -> "MoroccoDelineator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(tif_path=tif_path)
        return cls._instance

    def delineate(self, lon: float, lat: float, max_snap_cells: int = 35, half_window: int = 700) -> Dict[str, Any]:
        """
        Délinéation automatique du bassin amont à partir d'un point (lon, lat) :
        1. Projection pixel
        2. Découpage adaptatif de la grille D8
        3. Snapping sur le thalweg le plus pertinent
        4. Délinéation pyflwdir
        5. Vectorisation géométrique Shapely et GeoJSON
        """
        t0 = time.time()
        c_global, r_global = [int(round(v)) for v in (self.inv_transform * (lon, lat))]

        if not (0 <= c_global < self.width and 0 <= r_global < self.height):
            raise ValueError(f"Coordonnées ({lat:.4f}°N, {lon:.4f}°W) en dehors de la couverture du Maroc (MNT HydroSHEDS : 27.5°N à 36.3°N, 13.5°W à 1.0°W).")

        # Délimitation de la sous-fenêtre pour performance maximale
        x_min = max(0, c_global - half_window)
        y_min = max(0, r_global - half_window)
        x_max = min(self.width, c_global + half_window)
        y_max = min(self.height, r_global + half_window)

        sub_arr = np.array(self._im.crop((x_min, y_min, x_max, y_max)))
        sub_transform = self.transform * Affine.translation(x_min, y_min)

        # Nettoyage D8
        a = sub_arr.astype(np.int32)
        a[a == 255] = 0
        a = np.where(np.isin(a, list(self.valid_d8)), a, 247).astype(np.uint8)

        # Initialisation pyflwdir
        flw = pyflwdir.from_array(a, ftype="d8", transform=sub_transform, latlon=True)
        upa = flw.upstream_area(unit="km2")

        # Position locale dans la sous-fenêtre
        r_local = r_global - y_min
        c_local = c_global - x_min

        # Snapping adaptatif : chercher le maximum d'aire amont dans le voisinage
        best_upa = -1.0
        best_r, best_c = r_local, c_local

        # Vectorized snap: find max upstream area in neighborhood windows
        nrow_sub, ncol_sub = a.shape
        for w in [10, 20, max_snap_cells]:
            r_lo = max(0, r_local - w)
            r_hi = min(nrow_sub, r_local + w + 1)
            c_lo = max(0, c_local - w)
            c_hi = min(ncol_sub, c_local + w + 1)
            window = upa[r_lo:r_hi, c_lo:c_hi]
            local_idx = np.unravel_index(np.argmax(window), window.shape)
            candidate_upa = window[local_idx]
            if candidate_upa > best_upa:
                best_upa = candidate_upa
                best_r = r_lo + local_idx[0]
                best_c = c_lo + local_idx[1]
            if best_upa > 5.0 and w >= 20:
                break

        # Coordonnées réelles du point snappé (exutoire)
        snap_lon, snap_lat = sub_transform * (best_c + 0.5, best_r + 0.5)

        # Délinéation du bassin
        idx = np.array([best_r * ncol_sub + best_c], dtype=np.int64)
        bas = flw.basins(idxs=idx)
        mask = (bas > 0)
        n_cells = int(np.sum(mask))

        if n_cells == 0:
            raise RuntimeError(f"Aucun thalweg ou réseau amont identifié pour l'exutoire ({lat:.4f}°N, {lon:.4f}°W). Le point est probablement situé dans l'océan ou une dépression fermée.")

        # Vectorisation par extraction de contours (contouring)
        geom = self._mask_to_polygon(mask, sub_transform)
        if geom is None or geom.is_empty:
            # Fallback robuste : enveloppe convexe des cellules
            ys, xs = np.where(mask)
            if len(ys) > 0:
                step = max(1, len(ys) // 150)
                pts = [sub_transform * (x + 0.5, y + 0.5) for y, x in zip(ys[::step], xs[::step])]
                from shapely.geometry import MultiPoint
                geom = MultiPoint(pts).convex_hull
                if geom.geom_type not in ("Polygon", "MultiPolygon"):
                    geom = geom.buffer(0.003)
            else:
                from shapely.geometry import Point
                geom = Point(snap_lon, snap_lat).buffer(0.005)

        if not geom.is_valid:
            from shapely.validation import make_valid
            geom = make_valid(geom)

        # Surface en km² : priorité à l'aire cumulée hydrologique de pyflwdir
        area_km2 = float(best_upa) if best_upa > 0 else float(n_cells * 0.0075)
        if area_km2 < 0.01:
            area_km2 = 0.01

        elapsed = round(time.time() - t0, 3)

        return {
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "name": f"Bassin délinéé ({snap_lat:.3f} N, {snap_lon:.3f} W)",
                "area_km2": round(area_km2, 2),
                "outlet_lat": round(snap_lat, 5),
                "outlet_lon": round(snap_lon, 5),
                "clicked_lat": round(lat, 5),
                "clicked_lon": round(lon, 5),
                "snap_distance_km": round(float(np.hypot((snap_lat - lat) * 111.0, (snap_lon - lon) * 111.0 * np.cos(np.radians(lat)))), 2),
                "cells_count": n_cells,
                "delineation_time_s": elapsed
            }
        }

    def _mask_to_polygon(self, mask: np.ndarray, transform: Affine) -> Optional[shapely.Geometry]:
        """Convertit un masque 2D booléen en géométrie Shapely fermée et lissée (via rasterio.features.shapes)"""
        try:
            polygons = [
                shape(geom)
                for geom, val in shapes(mask.astype(np.uint8), mask=mask, transform=transform)
                if val == 1
            ]
            if not polygons:
                return None

            u = unary_union(polygons)
            # Simplification légère pour réduire la taille du GeoJSON sur la carte
            return u.simplify(0.0015, preserve_topology=True)
        except Exception:
            return None
