from django.urls import path
from . import views, api_views

app_name = 'core'

urlpatterns = [
    # Dashboard View
    path('', views.dashboard_view, name='dashboard'),
    
    # HTMX Partials
    path('htmx/envelope/', views.htmx_envelope_partial, name='htmx_envelope'),

    # REST / GeoJSON APIs
    path('api/layers/<str:country>/<str:layer_name>/', api_views.layer_geojson_view, name='api_layer_geojson'),
    path('api/delineate/', api_views.delineate_api_view, name='api_delineate'),
    path('api/clear-delineation/', api_views.clear_delineation_api_view, name='api_clear_delineation'),
    path('api/select-catchment/', api_views.select_catchment_api_view, name='api_select_catchment'),
    path('api/rivers/', api_views.rivers_geojson_view, name='api_rivers'),
    path('api/dams/', api_views.dams_geojson_view, name='api_dams'),
    path('api/export-csv/', api_views.export_simulation_csv, name='api_export_csv'),
]
