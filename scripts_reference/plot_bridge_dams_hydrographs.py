import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pathlib import Path

# Workspace directory (defaults to repository 'data' folder or environment variable)
WORKSPACE = os.environ.get("HYDRO_WORKSPACE", str(Path(__file__).resolve().parent.parent / "data"))
if os.path.exists(WORKSPACE):
    os.chdir(WORKSPACE)

plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
plt.rcParams['axes.edgecolor'] = '#cccccc'
plt.rcParams['axes.linewidth'] = 0.8

# Dam metadata
DAMS = {
    5050: ("COLOMERA", "Succès parfait : substrat argilo-marneux imperméable, 100% ruissellement superficiel"),
    5139: ("ARENOSO", "Très bonne dynamique temporelle (r = 0,87), léger sous-dimensionnement orographique"),
    5062: ("GUADALMELLATO", "Comportement satisfaisant sur grand bassin granito-schisteux de la Sierra Morena"),
    5018: ("GUADALMENA", "Bassin intermédiaire, dynamique saisonnière bien captée"),
    5012: ("BEMBEZAR", "Sous-estimation volumique liée aux prélèvements amont non répertoriés"),
    5001: ("TRANCO DE BEAS", "Bassin de haute montagne calcaire (Sierra de Cazorla)"),
    5039: ("QUIEBRAJANO", "Échec karstique (pertes) : substrat dolomitique fracturé, fuites vers vallée voisine"),
    5060: ("SAN CLEMENTE", "Échec karstique (gains) : résurgences vauclusiennes massives drainant hors MNT")
}

# 1. Load dam areas
catd = pd.read_csv('attributes_dams.csv')
area_map = dict(zip(catd['indroea'], catd['area_km2']))

# 2. Load LSTM simulations on dams
parqs = sorted(glob.glob('bridge/sims/deploy_s*.parquet'))
sims = pd.concat([pd.read_parquet(p) for p in parqs], ignore_index=True)
sims = sims.groupby(['basin', 'date'], as_index=False)[['sim']].mean()
sims['area_km2'] = sims['basin'].map(area_map)
sims['sim_hm3'] = sims['sim'] * sims['area_km2'] / 1000.0
sims['ref_ceh'] = sims['basin'].str.replace('dam_', '').astype(int)

# 3. Monthly aggregation
sm = (sims.set_index('date').groupby('ref_ceh')['sim_hm3']
      .resample('MS').agg(['sum', 'count']).reset_index()
      .rename(columns={'sum': 'sim_hm3', 'count': 'n_sim'}))

obs = pd.read_csv('bridge_inflows_monthly.csv')
obs['date'] = pd.to_datetime(obs['date'])
m = obs.merge(sm, on=['ref_ceh', 'date'], how='inner')
m = m[(m['n_valid'] >= 25) & (m['n_sim'] >= 25) & m['I_corr'].notna()]

# Load official results
res_df = pd.read_csv('bridge_results.csv').set_index('ref_ceh')

# Create 8-panel figure (4 rows, 2 columns)
fig, axes = plt.subplots(4, 2, figsize=(16, 18), sharex=False)
fig.subplots_adjust(hspace=0.36, wspace=0.18, top=0.94, bottom=0.04, left=0.06, right=0.96)

ordered_dams = [5050, 5139, 5062, 5018, 5012, 5001, 5039, 5060]

for idx, ref in enumerate(ordered_dams):
    ax = axes[idx // 2, idx % 2]
    g = m[m['ref_ceh'] == ref].sort_values('date').copy()
    
    # Zoom on a representative 10-year window for clarity (e.g. 2005-2018 or last 12 years of available data)
    max_d = g['date'].max()
    min_d = max(g['date'].min(), max_d - pd.DateOffset(years=14))
    sub = g[(g['date'] >= min_d) & (g['date'] <= max_d)].copy()
    
    dam_name, diag = DAMS[ref]
    kge_val = res_df.loc[ref, 'KGE_monthly']
    nse_val = res_df.loc[ref, 'NSE_monthly']
    pbias_val = res_df.loc[ref, 'pbias_pct']
    area_val = area_map.get(f'dam_{ref}', 0)
    
    # Plot curves
    ax.plot(sub['date'], sub['I_corr'], color='#1a2530', linewidth=1.6, label="I_corr (Observé reconstruit)", zorder=3)
    ax.plot(sub['date'], sub['sim_hm3'], color='#0077b6', linewidth=1.5, linestyle='-', label="LSTM Régional (PUB Aveugle)", zorder=4)
    
    # Color badge based on KGE
    if kge_val >= 0.5:
        badge_col = '#e8f5e9'; border_col = '#4caf50' # Vert
    elif kge_val >= 0.0:
        badge_col = '#fff9c4'; border_col = '#fbc02d' # Jaune
    else:
        badge_col = '#ffebee'; border_col = '#e57373' # Rouge
        
    badge_text = (
        f"KGE = {kge_val:.3f} | NSE = {nse_val:.3f} | Biais = {pbias_val:+.1f}%\n"
        f"Aire = {area_val:.0f} km² | {diag}"
    )
    ax.text(0.02, 0.94, badge_text, transform=ax.transAxes, fontsize=8.2,
            verticalalignment='top', bbox=dict(boxstyle='round,pad=0.4', facecolor=badge_col, edgecolor=border_col, alpha=0.95))
    
    ax.set_title(f"BARRAGE {dam_name} (Réf. CEH {ref})", fontsize=11, fontweight='bold', color='#0a4d4e', loc='left')
    ax.set_ylabel("Apport mensuel (hm³/mois)", fontsize=9.5, fontweight='bold')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.tick_params(axis='x', labelsize=9)
    ax.tick_params(axis='y', labelsize=9)
    
    if idx == 0:
        ax.legend(loc='upper right', fontsize=9, framealpha=0.95)

fig.suptitle("ÉVALUATION EN AVEUGLE DU MODÈLE RÉGIONAL SUR LES 8 BARRAGES DU BASSIN DU GUADALQUIVIR (APPLICATION BRIDGE)\nReconstitution des Apports Mensuels Entrants (hm³/mois) sans aucun Débit Passé (Analogie Cas d'Usage Marocain)",
             fontsize=13, fontweight='bold', color='#0a4d4e', y=0.98)

out_fig = 'figures_v7/F8_bridge_dams_detailed_hydrographs.png'
plt.savefig(out_fig, dpi=300, bbox_inches='tight')
print(f'Successfully saved dam hydrographs to {out_fig}')
plt.close()
