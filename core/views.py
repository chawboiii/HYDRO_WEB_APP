from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from .models import SimulationRun
from gis_engine.attributes_calculator import AttributesCalculator

attr_calc = AttributesCalculator()

MOROCCO_STATIONS = [
    {"code": "LOUK_01", "name": "Pont d'Oughane", "basin": "Loukkos", "river": "Oughane", "area_km2": 300.8, "lat": 34.9643, "lon": -5.5373, "kge": 0.638, "status": "valid"},
    {"code": "LOUK_02", "name": "Pont M'Ghar", "basin": "Loukkos", "river": "M'ghar", "area_km2": 82.3, "lat": 34.9885, "lon": -5.5115, "kge": -3.35, "status": "danger"},
    {"code": "LOUK_04", "name": "M'Douar", "basin": "Loukkos", "river": "Loukkos", "area_km2": 659.4, "lat": 34.9993, "lon": -5.5156, "kge": 0.833, "status": "valid"},
    {"code": "LOUK_05", "name": "Boufarah", "basin": "Loukkos", "river": "Loukkos", "area_km2": 261.8, "lat": 35.0418, "lon": -5.4631, "kge": 0.752, "status": "valid"},
    {"code": "OER_01", "name": "Addammaghene", "basin": "Oum Er Rbia", "river": "Lakhdar", "area_km2": 1039.8, "lat": 31.7100, "lon": -6.7390, "kge": -0.403, "status": "danger"},
    {"code": "OER_02", "name": "Sgatt", "basin": "Oum Er Rbia", "river": "Bernat", "area_km2": 435.6, "lat": 31.8100, "lon": -6.6865, "kge": -0.238, "status": "danger"},
    {"code": "OER_03", "name": "Zaouit Ahancal", "basin": "Oum Er Rbia", "river": "Ahancal", "area_km2": 182.2, "lat": 31.8317, "lon": -6.1040, "kge": -0.664, "status": "danger"},
    {"code": "OER_04", "name": "Tillouguite", "basin": "Oum Er Rbia", "river": "Asif Melloul", "area_km2": 2501.4, "lat": 32.0184, "lon": -6.2182, "kge": -0.135, "status": "warning"},
    {"code": "OER_05", "name": "Tizi n'Isly", "basin": "Oum Er Rbia", "river": "Ouirine", "area_km2": 271.0, "lat": 32.4109, "lon": -5.7273, "kge": -0.368, "status": "warning"},
]

def dashboard_view(request):
    """Vue principale du tableau de bord WebGIS Maroc"""
    recent_sims = SimulationRun.objects.all()[:5]

    context = {
        "morocco_stations": MOROCCO_STATIONS,
        "recent_sims": recent_sims,
        "default_lat": 33.5,
        "default_lon": -6.0,
        "default_zoom": 7
    }
    return render(request, "dashboard.html", context)


def htmx_envelope_partial(request):
    """Partiel HTMX pour le badge et le verdict de l'enveloppe de validité"""
    area_km2 = float(request.GET.get("area_km2", 0.0))
    aridity = float(request.GET.get("aridity", 0.0))
    status = request.GET.get("status", "valid")
    verdict = request.GET.get("verdict", "")

    context = {
        "area_km2": area_km2,
        "aridity": aridity,
        "overall_status": status,
        "verdict_text": verdict,
    }
    return render(request, "components/envelope_card.html", context)
