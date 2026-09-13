import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import shapely
import shapely.wkb
from shapely.geometry import mapping, shape


def gpkg_blob_to_shapely(blob: bytes) -> Optional[shapely.Geometry]:
    """
    Parse un BLOB de géométrie GeoPackage (OGC Standard) vers un objet Shapely.
    Extrait l'en-tête GeoPackage (magic bytes 'GP', flags, SRS ID, bounding box)
    puis décode le WKB sous-jacent.
    """
    if blob is None or len(blob) < 8:
        return None
    if blob[:2] != b"GP":
        return None

    flags = blob[3]
    envelope_indicator = (flags >> 1) & 0x07
    env_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    env_size = env_sizes.get(envelope_indicator, 0)
    wkb_offset = 8 + env_size

    try:
        return shapely.wkb.loads(blob[wkb_offset:])
    except Exception:
        return None


class GeoPackageManager:
    """
    Gestionnaire centralisé pour la lecture, la mise en cache et la sérialisation GeoJSON
    des GeoPackages nationaux du Maroc et d'Espagne.
    """
    _cache: Dict[str, Dict[str, Any]] = {}

    def __init__(self, data_dir: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parent.parent
        if data_dir is None:
            data_dir = base_dir / "data"
        self.data_dir = Path(data_dir)
        self.morocco_gpkg = self.data_dir / "catchments_morocco_full.gpkg"
        self.spain_gpkg = self.data_dir / "catchments_spain_full.gpkg"
        self.dams_spain_gpkg = self.data_dir / "catchments_dams.gpkg"
        self.dams_morocco_gpkg = self.data_dir / "catchments_maroc.gpkg"

        # GeoPackage des 9 stations marocaines certifiées
        primary_st = self.data_dir / "catchments_new_stations.gpkg"
        fallback_st = base_dir / "data_update_9stations" / "catchments_new_stations.gpkg"
        self.stations_morocco_gpkg = primary_st if primary_st.exists() else fallback_st

        # Couches réseau hydrographique du Maroc
        primary_riv = self.data_dir / "morocco_rivers_network.gpkg"
        fallback_riv = base_dir / "data_update_9stations" / "morocco_rivers_network.gpkg"
        self.rivers_morocco_gpkg = primary_riv if primary_riv.exists() else fallback_riv

        primary_light = self.data_dir / "morocco_rivers_light.geojson"
        fallback_light = base_dir / "data_update_9stations" / "morocco_rivers_light.geojson"
        self.rivers_light_geojson = primary_light if primary_light.exists() else fallback_light

        # Persistent read-only connection cache for faster repeated lookups
        self._connections: Dict[str, sqlite3.Connection] = {}

    def _get_connection(self, gpkg_path: Path) -> sqlite3.Connection:
        """Returns a cached read-only SQLite connection for a GeoPackage file."""
        key = str(gpkg_path)
        if key not in self._connections:
            self._connections[key] = sqlite3.connect(str(gpkg_path), check_same_thread=False)
        return self._connections[key]

    def get_layer_geojson(self, country: str, layer_name: str, simplify_tol: float = 0.002) -> Dict[str, Any]:
        """
        Retourne une FeatureCollection GeoJSON optimisée pour Leaflet, avec mise en cache mémoire.
        Supporte la couche des 9 stations de jaugeage et le réseau hydrographique (HydroRIVERS).
        """
        cache_key = f"{country}_{layer_name}_{simplify_tol}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        actual_table = layer_name
        if layer_name in ("rivers", "morocco_rivers", "rivers_network"):
            if self.rivers_light_geojson.exists():
                try:
                    with open(self.rivers_light_geojson, "r", encoding="utf-8") as f:
                        fc = json.load(f)
                    self._cache[cache_key] = fc
                    return fc
                except Exception:
                    pass
            if self.rivers_morocco_gpkg.exists():
                gpkg_path = self.rivers_morocco_gpkg
                actual_table = "rivers"
            else:
                raise FileNotFoundError("Fichier réseau hydrographique introuvable.")
        elif layer_name in ("catchments_new_stations", "stations_reference_9", "stations_morocco", "dams_reference_9") and self.stations_morocco_gpkg.exists():
            gpkg_path = self.stations_morocco_gpkg
            actual_table = "catchments"
        elif country.lower() in ("morocco", "maroc"):
            gpkg_path = self.morocco_gpkg
        elif country.lower() in ("spain", "espagne"):
            gpkg_path = self.spain_gpkg
        else:
            raise ValueError(f"Pays non supporté : {country}")

        if not gpkg_path.exists():
            raise FileNotFoundError(f"Fichier GeoPackage introuvable : {gpkg_path}")

        con = sqlite3.connect(str(gpkg_path))
        cur = con.cursor()

        # Vérifier si la table existe
        cur.execute("SELECT table_name FROM gpkg_contents WHERE table_name = ?", (actual_table,))
        if not cur.fetchone():
            con.close()
            raise ValueError(f"Couche '{actual_table}' introuvable dans {gpkg_path.name}")

        # Récupérer les colonnes
        cur.execute(f'PRAGMA table_info("{actual_table}")')
        cols = [r[1] for r in cur.fetchall()]
        geom_col = "geom" if "geom" in cols else "geometry"
        prop_cols = [c for c in cols if c != geom_col]

        quoted_cols = ", ".join(f'"{c}"' for c in [geom_col] + prop_cols)
        cur.execute(f'SELECT {quoted_cols} FROM "{actual_table}"')
        rows = cur.fetchall()
        con.close()

        features = []
        for row in rows:
            geom_blob = row[0]
            geom = gpkg_blob_to_shapely(geom_blob)
            if geom is None or geom.is_empty:
                continue

            if simplify_tol > 0:
                geom = geom.simplify(simplify_tol, preserve_topology=True)

            properties = {}
            for col_name, val in zip(prop_cols, row[1:]):
                properties[col_name] = val

            features.append({
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": properties
            })

        fc = {
            "type": "FeatureCollection",
            "features": features,
            "layer_name": layer_name,
            "country": country,
            "count": len(features)
        }

        self._cache[cache_key] = fc
        return fc

    def find_catchment_by_name_or_id(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Recherche un polygone de bassin par son nom ou code (ex: 'LOUK_01', 'Boufarah', 'OER_04').
        Recherche en priorité absolue dans les 9 stations de jaugeage marocaines.
        """
        ident_str = str(identifier).strip().lower()

        # 1. Chercher en priorité dans les 9 stations marocaines de jaugeage
        if self.stations_morocco_gpkg.exists():
            con = self._get_connection(self.stations_morocco_gpkg)
            cur = con.cursor()
            cur.execute("SELECT code, name, basin, river, delineated_area_km2, geom FROM catchments")
            for code, name, basin, river, area, blob in cur.fetchall():
                c_str = str(code).strip().lower() if code else ""
                n_str = str(name).strip().lower() if name else ""
                if ident_str in (c_str, n_str) or ident_str == f"{n_str} ({c_str})" or c_str in ident_str:
                    geom = gpkg_blob_to_shapely(blob)
                    return {
                        "name": f"{name} ({code})",
                        "station_name": name,
                        "code": code,
                        "basin": basin,
                        "river": river,
                        "type": "morocco_station",
                        "area_km2": float(area) if area else None,
                        "geometry": mapping(geom) if geom else None
                    }
            # No connection close needed — using pooled connection

        # 2. Chercher dans les barrages espagnols
        if self.spain_gpkg.exists():
            con = self._get_connection(self.spain_gpkg)
            cur = con.cursor()
            cur.execute("SELECT indroea, dam, area_km2, geom FROM dams_reference_8")
            for indroea, dam, area, blob in cur.fetchall():
                if (indroea and indroea.lower() == ident_str) or (dam and dam.lower() == ident_str) or (ident_str in (str(indroea).lower(), f"dam_{indroea}".lower())):
                    geom = gpkg_blob_to_shapely(blob)
                    return {
                        "name": f"Barrage {dam} ({indroea})",
                        "ref_ceh": str(indroea).replace("dam_", ""),
                        "dam": dam,
                        "type": "spain_dam",
                        "area_km2": float(area) if area else None,
                        "geometry": mapping(geom) if geom else None
                    }
            # No connection close needed — using pooled connection

        # 3. Chercher dans les 269 bassins d'entraînement espagnols
        if self.spain_gpkg.exists():
            con = self._get_connection(self.spain_gpkg)
            cur = con.cursor()
            cur.execute("SELECT indroea, demarc, area_km2, geom FROM catchments_reference_269 WHERE indroea = ?", (ident_str,))
            row = cur.fetchone()
            if row:
                geom = gpkg_blob_to_shapely(row[3])
                return {
                    "name": f"Bassin Jaugé {row[0]} ({row[1]})",
                    "indroea": row[0],
                    "demarc": row[1],
                    "type": "spain_pooled",
                    "area_km2": float(row[2]) if row[2] else None,
                    "geometry": mapping(geom) if geom else None
                }

        return None
