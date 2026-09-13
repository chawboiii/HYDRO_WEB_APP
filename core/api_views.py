import json
import csv
import io
import re
import unicodedata
import collections
from urllib.parse import quote
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import cache_page
import pandas as pd
from pathlib import Path

from gis_engine.gpkg_reader import GeoPackageManager
from gis_engine.delineator import MoroccoDelineator
from gis_engine.attributes_calculator import AttributesCalculator
from gis_engine.envelope_evaluator import evaluate_operational_envelope
from hydro_model.inference import HydroInferenceEngine
from hydro_model.forcing_service import ForcingService
from gis_engine.anthropogenic_audit import AnthropogenicAuditor
from .models import SimulationRun

# Singletons en mémoire pour performances maximales
gpkg_mgr = GeoPackageManager()
delineator = MoroccoDelineator.get_instance()
attr_calc = AttributesCalculator()
infer_engine = HydroInferenceEngine.get_instance()
forcing_srv = ForcingService()
auditor = AnthropogenicAuditor.get_instance()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@cache_page(60 * 60)  # 1 hour — layers don't change at runtime
@require_GET
def layer_geojson_view(request, country, layer_name):
    """Fournit les couches vectorielles en GeoJSON optimisé pour Leaflet"""
    try:
        fc = gpkg_mgr.get_layer_geojson(country=country, layer_name=layer_name, simplify_tol=0.006)
        return JsonResponse(fc, safe=False)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


def _cleanup_previous_custom_delineations():
    """Supprime les délinéations personnalisées précédentes de la base et du cache pour libérer du stockage."""
    try:
        # 1. Supprimer de la table SQLite les simulations personnalisées antérieures
        SimulationRun.objects.filter(basin_name__startswith="Bassin délinéé").delete()
        SimulationRun.objects.filter(basin_name="custom_delineated").delete()

        # 2. Nettoyer les fichiers CSV de forçage temporaires dans cache/forcings
        forcings_dir = Path(__file__).resolve().parent.parent / "cache" / "forcings"
        if forcings_dir.exists():
            for f in forcings_dir.glob("custom_delineated_*.csv"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in forcings_dir.glob("Bassin_délinéé_*.csv"):
                try:
                    f.unlink()
                except Exception:
                    pass
            for f in forcings_dir.glob("custom_*.csv"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass


@csrf_exempt
@require_POST
def clear_delineation_api_view(request):
    """
    Endpoint permettant d'effacer les délinéations temporaires précédentes de la base et du disque.
    """
    _cleanup_previous_custom_delineations()
    return JsonResponse({"status": "success", "message": "Délinéations précédentes nettoyées avec succès."})


@csrf_exempt
@require_POST
def delineate_api_view(request):
    """
    Endpoint de délinéation spatiale instantanée (pyflwdir) :
    Prend (lat, lon) et renvoie le polygone délinéé, les 8 attributs,
    le verdict d'enveloppe et la simulation d'hydrogramme complète.
    Supprime automatiquement toute délinéation précédente pour libérer la mémoire et le stockage.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    try:
        lat = float(data.get("lat"))
        lon = float(data.get("lon"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Paramètres 'lat' et 'lon' requis et numériques."}, status=400)

    try:
        # 0. Nettoyage préalable pour libérer le stockage (disque & SQLite)
        _cleanup_previous_custom_delineations()

        # 1. Délinéation spatiale via pyflwdir
        feature = delineator.delineate(lon=lon, lat=lat)
        props = feature["properties"]
        area_km2 = props["area_km2"]
        snap_lat = props["outlet_lat"]
        snap_lon = props["outlet_lon"]

        # Récupération de l'année de départ du forçage de 10 ans (défaut: 2014 -> 2014 à 2023)
        try:
            forcing_start_year = int(data.get("forcing_start_year", 2014))
        except (ValueError, TypeError):
            forcing_start_year = 2014

        start_date = f"{forcing_start_year}-01-01"
        end_date = f"{forcing_start_year + 9}-12-31"

        # 2. Récupération des forçages météo ERA5-Land (10 ans / 3 652 jours)
        df_forcing = forcing_srv.get_forcings(
            lat=snap_lat,
            lon=snap_lon,
            start_date=start_date,
            end_date=end_date,
            basin_name=f"custom_{forcing_start_year}"
        )

        # 3. Calcul des 8 attributs et diagnostic d'enveloppe
        attr_data = attr_calc.calculate_custom_attributes(
            area_km2=area_km2,
            lat=snap_lat,
            lon=snap_lon,
            df_forcing=df_forcing,
            basin_name=props["name"]
        )

        # 4. Inférence LSTM PyTorch
        sim_res = infer_engine.predict(
            df_forcing=df_forcing,
            attrs=attr_data["attributes"]
        )

        # 5. Audit d'influence anthropique & détection des barrages en amont
        audit_res = auditor.audit(
            catchment_geom=feature["geometry"],
            outlet_lat=snap_lat,
            outlet_lon=snap_lon,
            area_km2=area_km2
        )

        # Sauvegarde en base SQLite
        run = SimulationRun.objects.create(
            basin_name=props["name"],
            country="Maroc",
            outlet_lat=snap_lat,
            outlet_lon=snap_lon,
            area_km2=area_km2,
            aridity=attr_data["attributes"]["aridity"],
            envelope_status=attr_data["envelope"]["overall_status"],
            verdict_text=attr_data["envelope"]["verdict_text"],
            attributes_json=attr_data["attributes"],
            results_json={
                **sim_res["stats"],
                "_daily_cache": sim_res["daily"],
                "_monthly_cache": sim_res.get("monthly", []),
                "_metrics": sim_res.get("metrics", {})
            }
        )

        return JsonResponse({
            "status": "success",
            "run_id": run.id,
            "feature": feature,
            "attributes": attr_data["attributes"],
            "envelope": attr_data["envelope"],
            "audit": audit_res,
            "hydrograph": sim_res,
            "forcing_period": {
                "start_date": start_date,
                "end_date": end_date,
                "start_year": forcing_start_year,
                "end_year": forcing_start_year + 9,
                "duration_years": 10
            },
            "message": f"Bassin délinéé avec succès ({area_km2:.1f} km²)."
        })


    except ValueError as e:
        return JsonResponse({
            "status": "error",
            "error": str(e),
            "hint": "La délinéation spatiale instantanée par MNT D8 HydroSHEDS est active sur le Maroc (27.5°N–36.3°N, 13.5°W–1.0°W)."
        }, status=400)
    except RuntimeError as e:
        return JsonResponse({
            "status": "error",
            "error": str(e),
            "hint": "Aucun cours d'eau amont n'a pu être extrait à cette position. Déplacez légèrement le curseur vers une vallée ou un thalweg."
        }, status=400)
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "error": f"Erreur lors de la délinéation spatiale : {str(e)}"
        }, status=400)


@csrf_exempt
@require_POST
def select_catchment_api_view(request):
    """
    Sélectionne un bassin ou barrage de référence existant (Maroc ou Espagne),
    charge ses données officielles (géométrie, attributs, vérité terrain I_corr),
    et exécute la prédiction par Deep Learning.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    identifier = data.get("identifier")
    if not identifier:
        return JsonResponse({"error": "Paramètre 'identifier' manquant."}, status=400)

    try:
        # 1. Recherche du polygone vectoriel
        catchment_info = gpkg_mgr.find_catchment_by_name_or_id(str(identifier))
        
        # 2. Récupération des attributs certifiés du PFE
        attr_data = attr_calc.get_reference_attributes(str(identifier))
        if not attr_data:
            # Si non trouvé dans les tables spécifiques, calcul par défaut
            area = catchment_info.get("area_km2", 150.0) if catchment_info else 150.0
            attr_data = attr_calc.calculate_custom_attributes(area_km2=area, lat=34.0, lon=-5.0, df_forcing=pd.DataFrame())

        attrs = attr_data["attributes"]
        area_km2 = attrs["area_km2"]

        # 3. Forçages météo et vérité terrain
        obs_monthly = None
        basin_type = catchment_info.get("type", "") if catchment_info else ""
        
        # Coordonnées représentatives pour la météo
        if catchment_info and catchment_info.get("geometry"):
            from shapely.geometry import shape
            geom = shape(catchment_info["geometry"])
            centroid = geom.centroid
            lat_f, lon_f = centroid.y, centroid.x
        else:
            lat_f, lon_f = 34.0, -5.0

        # Identifier s'il s'agit d'une des 9 stations de jaugeage marocaines
        st_code = None
        if catchment_info and catchment_info.get("code"):
            st_code = str(catchment_info["code"]).strip().upper()
        elif attr_data and attr_data.get("code"):
            st_code = str(attr_data["code"]).strip().upper()
        else:
            ident_clean = str(identifier).strip().upper()
            if ident_clean in ["LOUK_01", "LOUK_02", "LOUK_04", "LOUK_05", "OER_01", "OER_02", "OER_03", "OER_04", "OER_05"]:
                st_code = ident_clean

        # Choix de la période de 10 ans pour le forçage (défaut: 2014 -> 2014-2023)
        try:
            forcing_start_year = int(data.get("forcing_start_year", 2014))
        except (ValueError, TypeError):
            forcing_start_year = 2014

        f_start_date = f"{forcing_start_year}-01-01"
        f_end_date = f"{forcing_start_year + 9}-12-31"

        df_forcing = None
        morocco_9_codes = ["LOUK_01", "LOUK_02", "LOUK_04", "LOUK_05", "OER_01", "OER_02", "OER_03", "OER_04", "OER_05"]
        if st_code in morocco_9_codes:
            # 1. Forçages officiels ERA5-Land (2000-2022)
            parquet_file = DATA_DIR / "forcings_9_stations_era5.parquet"
            if parquet_file.exists():
                try:
                    df_all_f = pd.read_parquet(parquet_file)
                    df_st_f = df_all_f[df_all_f["code"].str.upper() == st_code].copy()
                    if not df_st_f.empty:
                        df_st_f["date"] = pd.to_datetime(df_st_f["date"]).dt.strftime("%Y-%m-%d")
                        # Filtrer sur les 10 ans demandés si disponibles dans le parquet
                        df_st_sub = df_st_f[(df_st_f["date"] >= f_start_date) & (df_st_f["date"] <= f_end_date)].copy()
                        if len(df_st_sub) >= 300:
                            df_forcing = df_st_sub[["date", "prcp_mm", "tmin_c", "tmax_c", "pet_mm"]].copy()
                        else:
                            df_forcing = df_st_f[["date", "prcp_mm", "tmin_c", "tmax_c", "pet_mm"]].copy()
                except Exception:
                    df_forcing = None

            # 2. Observations mensuelles in situ officielles
            obs_file = DATA_DIR / "observed_monthly_9_stations.csv"
            if obs_file.exists():
                try:
                    df_obs_all = pd.read_csv(obs_file)
                    df_obs_st = df_obs_all[df_obs_all["station_code"].str.upper() == st_code].copy()
                    if not df_obs_st.empty:
                        obs_monthly = df_obs_st[["date", "vol_obs_hm3", "q_obs_m3s"]].copy()
                        obs_monthly["I_corr"] = obs_monthly["vol_obs_hm3"]
                except Exception:
                    obs_monthly = None

        # Vérifier si c'est un des 8 barrages espagnols de l'étude Bridge
        ref_ceh = catchment_info.get("ref_ceh") if catchment_info else None
        if not ref_ceh:
            clean_ident = str(identifier).replace("dam_", "")
            if clean_ident in ["5001", "5012", "5018", "5039", "5050", "5060", "5062", "5139"]:
                ref_ceh = clean_ident

        if ref_ceh:
            inflow_file = DATA_DIR / "bridge_inflows_monthly.csv"
            if inflow_file.exists():
                df_obs = pd.read_csv(inflow_file)
                df_obs["date"] = pd.to_datetime(df_obs["date"])
                obs_monthly = df_obs[df_obs["ref_ceh"] == int(ref_ceh)].copy()

        # Forçages journaliers sur 10 ans par défaut si non chargés depuis le parquet
        if df_forcing is None or df_forcing.empty:
            df_forcing = forcing_srv.get_forcings(
                lat=lat_f,
                lon=lon_f,
                start_date=f_start_date,
                end_date=f_end_date,
                basin_name=f"{identifier}_{forcing_start_year}"
            )

        # 4. Inférence Deep Learning LSTM
        sim_res = infer_engine.predict(
            df_forcing=df_forcing,
            attrs=attrs,
            obs_monthly=obs_monthly
        )

        # Si barrage espagnol officiel, injecter les métriques certifiées du PFE
        if ref_ceh:
            bridge_res_file = DATA_DIR / "bridge_results.csv"
            if bridge_res_file.exists():
                bdf = pd.read_csv(bridge_res_file)
                match = bdf[bdf["ref_ceh"] == int(ref_ceh)]
                if not match.empty:
                    row = match.iloc[0]
                    sim_res["metrics"].update({
                        "KGE_monthly": float(row["KGE_monthly"]),
                        "NSE_monthly": float(row["NSE_monthly"]),
                        "PBIAS_pct": float(row["pbias_pct"]),
                        "mean_annual_obs_hm3": float(row["mean_annual_obs_hm3"]),
                        "mean_annual_sim_hm3": float(row["mean_annual_sim_hm3"]),
                        "has_obs": True
                    })

        # Enregistrer en base
        country = "Maroc" if (st_code in morocco_9_codes or "maroc" in basin_type.lower()) else "Espagne"
        run = SimulationRun.objects.create(
            basin_name=attr_data["name"],
            country=country,
            outlet_lat=lat_f,
            outlet_lon=lon_f,
            area_km2=area_km2,
            aridity=attrs["aridity"],
            envelope_status=attr_data["envelope"]["overall_status"],
            verdict_text=attr_data["envelope"]["verdict_text"],
            kge_monthly=sim_res["metrics"].get("KGE_monthly"),
            nse_monthly=sim_res["metrics"].get("NSE_monthly"),
            attributes_json=attrs,
            results_json={
                **sim_res["stats"],
                "_daily_cache": sim_res["daily"],
                "_monthly_cache": sim_res.get("monthly", []),
                "_metrics": sim_res.get("metrics", {})
            }
        )

        feature = None
        if catchment_info and catchment_info.get("geometry"):
            feature = {
                "type": "Feature",
                "geometry": catchment_info["geometry"],
                "properties": {
                    "name": attr_data["name"],
                    "area_km2": area_km2
                }
            }

        actual_start_date = df_forcing["date"].iloc[0] if "date" in df_forcing.columns else f_start_date
        actual_end_date = df_forcing["date"].iloc[-1] if "date" in df_forcing.columns else f_end_date

        # Audit d'influence anthropique & détection des barrages en amont
        audit_res = None
        if catchment_info and catchment_info.get("geometry"):
            audit_res = auditor.audit(
                catchment_geom=catchment_info["geometry"],
                outlet_lat=lat_f,
                outlet_lon=lon_f,
                area_km2=area_km2
            )

        return JsonResponse({
            "status": "success",
            "run_id": run.id,
            "feature": feature,
            "basin_name": attr_data["name"],
            "station_code": st_code,
            "attributes": attrs,
            "envelope": attr_data["envelope"],
            "audit": audit_res,
            "hydrograph": sim_res,
            "forcing_period": {
                "start_date": actual_start_date,
                "end_date": actual_end_date,
                "start_year": int(actual_start_date[:4]),
                "end_year": int(actual_end_date[:4]),
                "duration_years": round((pd.to_datetime(actual_end_date) - pd.to_datetime(actual_start_date)).days / 365.25, 1)
            },
            "message": f"Bassin/Station '{attr_data['name']}' sélectionné et simulé."
        })


    except Exception as e:
        return JsonResponse({"status": "error", "error": str(e)}, status=500)


@require_GET
def export_simulation_csv(request):
    """
    Exporte les séries temporelles (journalières ou mensuelles) d'une simulation
    au format CSV standard (RFC 4180) avec en-têtes explicites, encodage UTF-8 BOM
    directement exploitable sous Microsoft Excel, Python/Pandas, QGIS et R.
    Génère un nom de fichier descriptif normalisé ASCII et RFC 5987.
    """
    run_id = request.GET.get("run_id")
    if not run_id:
        raise Http404("Paramètre 'run_id' manquant.")

    try:
        run = SimulationRun.objects.get(id=run_id)
    except SimulationRun.DoesNotExist:
        raise Http404("Simulation introuvable.")

    timestep = request.GET.get("timestep", "journalier").lower()
    is_monthly = timestep in ["monthly", "mensuel", "mois", "m"]

    # Récupération des caches
    results_json = run.results_json if isinstance(run.results_json, dict) else {}
    daily_cache = results_json.get("_daily_cache")
    monthly_cache = results_json.get("_monthly_cache")

    # Si données absentes du cache, recalcul d'inférence de secours
    if (is_monthly and not monthly_cache) or (not is_monthly and not daily_cache):
        df_forcing = forcing_srv.get_forcings(lat=run.outlet_lat, lon=run.outlet_lon, basin_name=run.basin_name)
        sim_res = infer_engine.predict(df_forcing=df_forcing, attrs=run.attributes_json)
        daily_cache = sim_res["daily"]
        monthly_cache = sim_res.get("monthly", [])

    # Si monthly demandé mais non précalculé, agréger rapidement depuis daily_cache
    if is_monthly and (not monthly_cache or len(monthly_cache) == 0) and daily_cache:
        monthly_agg = collections.OrderedDict()
        for r in daily_cache:
            m_key = r["date"][:7]
            if m_key not in monthly_agg:
                monthly_agg[m_key] = {"month_str": m_key, "prcp_mm": 0.0, "q_sum": 0.0, "count": 0}
            monthly_agg[m_key]["prcp_mm"] += float(r.get("prcp_mm", 0.0) or 0.0)
            monthly_agg[m_key]["q_sum"] += float(r.get("q_sim_m3s", 0.0) or 0.0)
            monthly_agg[m_key]["count"] += 1
        
        monthly_cache = []
        for m_key, agg in monthly_agg.items():
            cnt = max(agg["count"], 1)
            mean_q = agg["q_sum"] / cnt
            vol = mean_q * 86400.0 * cnt / 1e6
            monthly_cache.append({
                "month_str": m_key,
                "prcp_mm": round(agg["prcp_mm"], 1),
                "sim_q_m3s": round(mean_q, 3),
                "sim_hm3": round(vol, 3)
            })

    # Si c'est une des 9 stations, vérifier si des observations in situ peuvent être injectées
    st_code_match = re.search(r'(LOUK_\d+|OER_\d+)', run.basin_name, re.IGNORECASE)
    if is_monthly and monthly_cache and st_code_match:
        st_code = st_code_match.group(1).upper()
        obs_file = DATA_DIR / "observed_monthly_9_stations.csv"
        if obs_file.exists():
            try:
                df_obs = pd.read_csv(obs_file)
                df_obs_st = df_obs[df_obs["station_code"].str.upper() == st_code].copy()
                if not df_obs_st.empty:
                    df_obs_st["month_str"] = df_obs_st["date"].astype(str).str.slice(0, 7)
                    obs_dict = dict(zip(df_obs_st["month_str"], df_obs_st["vol_obs_hm3"]))
                    q_obs_dict = dict(zip(df_obs_st["month_str"], df_obs_st["q_obs_m3s"])) if "q_obs_m3s" in df_obs_st.columns else {}
                    for m_item in monthly_cache:
                        m_str = m_item.get("month_str")
                        if m_str in obs_dict and obs_dict[m_str] not in [None, ""]:
                            m_item["obs_hm3"] = obs_dict[m_str]
                            if m_str in q_obs_dict:
                                m_item["obs_q_m3s"] = q_obs_dict[m_str]
            except Exception:
                pass

    # Détection des années de début et de fin pour le nommage descriptif
    start_year, end_year = None, None
    if is_monthly and monthly_cache and len(monthly_cache) > 0:
        start_year = str(monthly_cache[0].get("month_str", ""))[:4]
        end_year = str(monthly_cache[-1].get("month_str", ""))[:4]
    elif daily_cache and len(daily_cache) > 0:
        start_year = str(daily_cache[0].get("date", ""))[:4]
        end_year = str(daily_cache[-1].get("date", ""))[:4]

    # Construction du nom de fichier descriptif (purement ASCII, robuste tout OS)
    nfkd = unicodedata.normalize('NFKD', str(run.basin_name))
    ascii_name = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean_name = re.sub(r'[^a-zA-Z0-9]+', '_', ascii_name).strip('_')
    clean_name = re.sub(r'_+', '_', clean_name)
    if not clean_name:
        clean_name = "bassin"

    step_tag = "mensuel" if is_monthly else "journalier"
    area_tag = f"{int(round(run.area_km2))}km2" if run.area_km2 else ""
    period_tag = f"{start_year}_{end_year}" if start_year and end_year and start_year.isdigit() else ""

    parts = ["hydrogramme", step_tag, clean_name]
    if area_tag:
        parts.append(area_tag)
    if period_tag:
        parts.append(period_tag)
    
    filename = "_".join(parts) + ".csv"

    # Génération du contenu CSV avec BOM UTF-8 (\ufeff) pour ouverture directe et propre sous Excel
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=",", lineterminator="\r\n")

    area_val = round(run.area_km2, 2) if run.area_km2 else 0.0

    if is_monthly and monthly_cache:
        has_obs = any(r.get("obs_hm3") not in [None, ""] for r in monthly_cache)
        if has_obs:
            writer.writerow([
                "mois", "nom_bassin", "superficie_km2", "precipitation_mm",
                "debit_simule_m3s", "volume_simule_hm3",
                "debit_observe_m3s", "volume_observe_hm3",
                "ecart_volume_hm3", "ratio_sim_obs"
            ])
            for r in monthly_cache:
                v_sim = float(r.get("sim_hm3", 0.0) or 0.0)
                v_obs_raw = r.get("obs_hm3")
                v_obs = float(v_obs_raw) if v_obs_raw not in [None, ""] else None
                diff = round(v_sim - v_obs, 3) if v_obs is not None else ""
                ratio = round(v_sim / max(v_obs, 1e-4), 3) if (v_obs is not None and v_obs > 0) else ""
                writer.writerow([
                    r.get("month_str", ""),
                    run.basin_name,
                    area_val,
                    r.get("prcp_mm", ""),
                    r.get("sim_q_m3s", ""),
                    r.get("sim_hm3", ""),
                    r.get("obs_q_m3s", "") if v_obs is not None else "",
                    r.get("obs_hm3", "") if v_obs is not None else "",
                    diff,
                    ratio
                ])
        else:
            writer.writerow([
                "mois", "nom_bassin", "superficie_km2", "precipitation_mm",
                "debit_simule_m3s", "volume_simule_hm3"
            ])
            for r in monthly_cache:
                writer.writerow([
                    r.get("month_str", ""),
                    run.basin_name,
                    area_val,
                    r.get("prcp_mm", ""),
                    r.get("sim_q_m3s", ""),
                    r.get("sim_hm3", "")
                ])
    else:
        writer.writerow([
            "date", "nom_bassin", "superficie_km2",
            "precipitation_era5_mm", "evapotranspiration_pet_mm",
            "temperature_min_c", "temperature_max_c",
            "lame_ecoulee_simulee_mm", "debit_simule_m3s", "volume_simule_hm3"
        ])
        for r in (daily_cache or []):
            q_m3s = float(r.get("q_sim_m3s", 0.0) or 0.0)
            vol_hm3 = round(q_m3s * 0.0864, 4)
            writer.writerow([
                r.get("date", ""),
                run.basin_name,
                area_val,
                r.get("prcp_mm", ""),
                r.get("pet_mm", ""),
                r.get("tmin_c", ""),
                r.get("tmax_c", ""),
                r.get("q_sim_mm", ""),
                round(q_m3s, 4),
                vol_hm3
            ])

    csv_bytes = output.getvalue().encode("utf-8")
    response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'
    response["Content-Length"] = len(csv_bytes)
    return response


@cache_page(60 * 60)
@require_GET
def rivers_geojson_view(request):
    """Fournit le réseau des oueds majeurs du Maroc (HydroRIVERS filtré >= 30 km2)"""
    rivers_path = DATA_DIR / "morocco_rivers_light.geojson"
    if not rivers_path.exists():
        rivers_path = DATA_DIR / "morocco_rivers_main.geojson"
    if not rivers_path.exists():
        raise Http404("Fichier de réseau hydrographique introuvable.")
    with open(rivers_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JsonResponse(data, safe=False)


@cache_page(60 * 60)
@require_GET
def dams_geojson_view(request):
    """Fournit les 45 grands barrages du Maroc avec coordonnées, capacités et caractéristiques"""
    dams_path = DATA_DIR / "dams_morocco_inventory.geojson"
    if not dams_path.exists():
        dams_path = Path(__file__).resolve().parent.parent / "data_update_9stations" / "dams_morocco_inventory.geojson"
    if not dams_path.exists():
        raise Http404("Fichier d'inventaire des barrages introuvable.")
    with open(dams_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JsonResponse(data, safe=False)

