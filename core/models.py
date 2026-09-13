from django.db import models


class SimulationRun(models.Model):
    """Enregistre l'historique des délinéations et simulations d'hydrogrammes."""
    basin_name = models.CharField(max_length=255, verbose_name="Nom du Bassin")
    country = models.CharField(max_length=50, default="Morocco", verbose_name="Pays")
    outlet_lat = models.FloatField(verbose_name="Latitude Exutoire")
    outlet_lon = models.FloatField(verbose_name="Longitude Exutoire")
    area_km2 = models.FloatField(verbose_name="Superficie (km²)")
    aridity = models.FloatField(verbose_name="Indice d'Aridité")
    envelope_status = models.CharField(max_length=50, default="valid", verbose_name="Statut Enveloppe")
    verdict_text = models.TextField(blank=True, verbose_name="Verdict")
    
    kge_monthly = models.FloatField(null=True, blank=True, verbose_name="KGE Mensuel")
    nse_monthly = models.FloatField(null=True, blank=True, verbose_name="NSE Mensuel")
    
    attributes_json = models.JSONField(default=dict, verbose_name="Attributs Physiques")
    results_json = models.JSONField(default=dict, verbose_name="Résultats Synthétiques")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de simulation")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Simulation Hydrologique"
        verbose_name_plural = "Simulations Hydrologiques"

    def __str__(self):
        return f"{self.basin_name} ({self.area_km2:.1f} km²) - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
