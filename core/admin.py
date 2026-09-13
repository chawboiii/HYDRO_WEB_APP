from django.contrib import admin
from .models import SimulationRun


@admin.register(SimulationRun)
class SimulationRunAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'basin_name',
        'country',
        'area_km2',
        'aridity',
        'envelope_status',
        'kge_monthly',
        'created_at',
    )
    list_filter = ('country', 'envelope_status', 'created_at')
    search_fields = ('basin_name', 'verdict_text')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
