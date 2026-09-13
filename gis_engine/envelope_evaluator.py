from typing import Dict, Any


def evaluate_operational_envelope(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Évalue l'Enveloppe de Validité Opérationnelle du modèle LSTM régionalisé
    selon les bornes d'applicabilité établies (Chapitre 5 du PFE) :
    - Surface du bassin versant : 20 à 3 500 km²
    - Indice d'aridité (PET / P) : <= 2.2 (Strate Humide <= 1.6, Intermédiaire 1.6-2.2, Aride > 2.2)
    """
    area = float(attrs.get("area_km2", 0.0))
    aridity = float(attrs.get("aridity", 0.0))

    area_valid = (20.0 <= area <= 3500.0)
    
    if aridity <= 1.6:
        aridity_strate = "humide"
        aridity_desc = "Strate humide (KGE médian régionalisé ~0.47)"
        aridity_badge = "success"  # vert
        aridity_valid = True
    elif aridity <= 2.2:
        aridity_strate = "intermédiaire"
        aridity_desc = "Strate intermédiaire (KGE médian régionalisé ~0.27)"
        aridity_badge = "warning"  # jaune/ambre
        aridity_valid = True
    else:
        aridity_strate = "aride"
        aridity_desc = "Strate aride (KGE médian négatif — pertes/évaporation extrêmes)"
        aridity_badge = "danger"   # rouge
        aridity_valid = False

    reasons = []
    if not area_valid:
        if area < 20.0:
            reasons.append(f"Surface ({area:.1f} km²) inférieure au seuil minimal de 20 km²")
        else:
            reasons.append(f"Surface ({area:.0f} km²) supérieure au seuil maximal de 3 500 km²")
    
    if not aridity_valid:
        reasons.append(f"Indice d'aridité ({aridity:.2f}) supérieur au seuil critique de 2.20")

    if area_valid and aridity_valid:
        if aridity_strate == "humide":
            verdict_text = "Bassin pleinement dans l'enveloppe opérationnelle (Strate humide, haute confiance KGE ~0.47)"
            overall_status = "valid"
            badge_color = "emerald"
        else:
            verdict_text = "Bassin dans l'enveloppe opérationnelle (Strate intermédiaire, performance modérée KGE ~0.27)"
            overall_status = "warning"
            badge_color = "amber"
    else:
        verdict_text = "Bassin hors de l'enveloppe opérationnelle recommandée : " + " ; ".join(reasons)
        overall_status = "danger"
        badge_color = "rose"

    return {
        "area_km2": round(area, 2),
        "area_valid": area_valid,
        "aridity": round(aridity, 3),
        "aridity_strate": aridity_strate,
        "aridity_desc": aridity_desc,
        "aridity_badge": aridity_badge,
        "aridity_valid": aridity_valid,
        "overall_status": overall_status,
        "badge_color": badge_color,
        "verdict_text": verdict_text,
        "reasons": reasons
    }
