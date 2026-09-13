/**
 * HYDRO_WEB_APP — Application Frontend Réactive (Thème Modern Organic Maroc)
 * Alpine.js 3.x + Leaflet 1.9.x + Chart.js 4.x
 */

function hydroApp() {
    return {
        // État de l'IHM & Disposition Spatiale
        activeMode: 'delineate', // 'delineate' ou 'reference'
        sidebarOpen: true,       // Permet de replier le volet pour 100% d'espace carte
        chartDrawerState: 'minimized', // Commence minimisé pour maximiser l'espace carte au chargement initial
        chartMode: 'monthly',    // 'monthly' par défaut pour un affichage immédiat et fluide
        dateFilterStart: '',     // Filtrage interactif de l'hydrogramme (Date Début YYYY-MM-DD)
        dateFilterEnd: '',       // Filtrage interactif de l'hydrogramme (Date Fin YYYY-MM-DD)

        // Forçage temporel (10 ans)
        forcingStartYear: 2014,  // Année de départ du forçage de 10 ans (ex: 2014 -> 2014-2023)
        availableForcingYears: [
            2015, 2014, 2013, 2012, 2011, 2010, 2009, 2008, 2007, 2006, 2005, 2004, 2003, 2002, 2001, 2000, 1995, 1990, 1985, 1980
        ],
        forcingIntervalStart: '', // Borne début stricte des 10 ans simulés (YYYY-MM-DD)
        forcingIntervalEnd: '',   // Borne fin stricte des 10 ans simulés (YYYY-MM-DD)
        originalFullStats: null,  // Mémorisation des métriques sur les 10 ans complets

        // Coordonnées & Curseur
        inputLat: 34.583,
        inputLon: -5.291,
        cursorLat: null,
        cursorLon: null,
        cursorInMorocco: true,
        autoDelineateOnClick: false,
        isLoading: false,
        _lastMouseMove: 0,

        // Notifications Toast Modern Organic
        toast: {
            visible: false,
            title: '',
            message: '',
            type: 'info', // 'info', 'warning', 'error', 'success'
            hint: '',
            timeout: null
        },

        // Points de repère hydrologiques
        presets: [],

        // Données du bassin actif
        currentBasinName: '',
        currentRunId: null,
        currentEnvelope: null,
        currentAttributes: null,
        currentStats: null,
        currentMetrics: null,
        hasSimulationData: false,
        simulationCache: null,

        // Couches SIG Nationales (Maroc uniquement)
        layers: {
            morocco_major: false,
            morocco_dams: true,
            morocco_lev06: false,
            morocco_rivers: false,
            morocco_dams_all: false
        },

        // Audit d'influence anthropique & Barrages amont
        currentAudit: null,
        upstreamDamMarkers: [],
        allDamsLayer: null,

        // Instances Leaflet & Chart.js
        map: null,
        leafletLayers: {},
        activeCatchmentLayer: null,
        outletMarker: null,
        pickerMarker: null,
        coverageRectangle: null,
        chartInstance: null,

        init() {
            window.hydroAppInstance = this;
            this.$nextTick(() => {
                this.initMap();
                // Charger automatiquement la couche des 9 stations clés du Maroc
                this.toggleLayer('morocco', 'catchments_new_stations', true);
                if (window.lucide) window.lucide.createIcons();
            });

            // Écouter les redimensionnements de fenêtre pour rafraîchir la carte et le graphique
            window.addEventListener('resize', () => {
                if (this.map) this.map.invalidateSize();
                if (this.chartInstance) this.chartInstance.resize();
            });
        },

        toggleSidebar() {
            this.sidebarOpen = !this.sidebarOpen;
            setTimeout(() => {
                if (this.map) this.map.invalidateSize();
                if (this.chartInstance) this.chartInstance.resize();
            }, 320);
        },

        setChartDrawerState(state) {
            this.chartDrawerState = state;
            setTimeout(() => {
                if (this.map) this.map.invalidateSize();
                if (this.chartInstance) this.chartInstance.resize();
            }, 320);
        },

        isWithinMorocco(lat, lon) {
            return (lat >= 27.5 && lat <= 36.35 && lon >= -13.5 && lon <= -1.0);
        },

        setMode(mode) {
            this.activeMode = mode;
            const mapEl = document.getElementById('leafletMap');
            if (mapEl) {
                if (mode === 'delineate') {
                    mapEl.classList.add('cursor-crosshair');
                } else {
                    mapEl.classList.remove('cursor-crosshair');
                }
            }
            if (mode === 'delineate') {
                this.flyToRegion('maroc');
            }
        },

        initMap() {
            // Centre initial sur le Maroc
            this.map = L.map('leafletMap', {
                center: [31.8, -6.8],
                zoom: 6.5,
                zoomControl: false // Déplacé en bas à droite pour libérer l'espace
            });

            L.control.zoom({ position: 'bottomright' }).addTo(this.map);

            // Curseur crosshair par défaut en mode délinéation
            const mapEl = document.getElementById('leafletMap');
            if (mapEl) mapEl.classList.add('cursor-crosshair');

            // Fonds de carte Modern Organic clairs, fiables & fluides (sans clé API ni filigrane)
            const esriTopo = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
                maxZoom: 19,
                updateWhenIdle: true,
                keepBuffer: 2,
                attribution: '&copy; Esri &mdash; Topographie'
            });

            // OpenStreetMap haute fidélité (serveur OSM France rapide, sans filigrane 'API KEY REQUIRED' ni blocage 403)
            const osmDetailed = L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
                maxZoom: 19,
                subdomains: 'abc',
                updateWhenIdle: true,
                keepBuffer: 2,
                attribution: '&copy; OpenStreetMap France &copy; Contributeurs OSM'
            });

            const esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                maxZoom: 19,
                updateWhenIdle: true,
                keepBuffer: 2,
                attribution: '&copy; Esri &mdash; Satellite HD'
            });

            // Fond par défaut : Topographie Relief Esri
            esriTopo.addTo(this.map);

            const baseMaps = {
                "🏔️ Topographie Relief (Esri)": esriTopo,
                "🗺️ Carte Détaillée (OSM Rues)": osmDetailed,
                "🛰️ Satellite HD (Esri)": esriSat
            };

            // Positionné en HAUT À GAUCHE pour une visibilité totale et sans conflit avec le curseur ni la barre SIG
            L.control.layers(baseMaps, null, { position: 'topleft' }).addTo(this.map);

            // Périmètre de couverture MNT HydroSHEDS Maroc (tracé épuré)
            this.coverageRectangle = L.rectangle([[27.5, -13.5], [36.35, -1.0]], {
                color: '#0f766e',
                weight: 1.5,
                dashArray: '6, 8',
                fillColor: '#0f766e',
                fillOpacity: 0.015,
                interactive: false
            }).addTo(this.map);

            // Création du curseur interactif d'exutoire (Pin déplaçable)
            this.setPickerLocation(this.inputLat, this.inputLon);

            // Suivi des coordonnées du curseur
            this.map.on('mousemove', (e) => {
                const now = Date.now();
                if (now - this._lastMouseMove < 66) return; // ~15fps throttle
                this._lastMouseMove = now;
                this.cursorLat = e.latlng.lat.toFixed(4);
                this.cursorLon = e.latlng.lng.toFixed(4);
                this.cursorInMorocco = this.isWithinMorocco(e.latlng.lat, e.latlng.lng);
            });

            // Clic sur la carte : positionnement du curseur exutoire
            this.map.on('click', (e) => {
                const lat = parseFloat(e.latlng.lat.toFixed(5));
                const lon = parseFloat(e.latlng.lng.toFixed(5));

                this.setPickerLocation(lat, lon);

                if (this.activeMode === 'delineate') {
                    if (!this.isWithinMorocco(lat, lon)) {
                        this.showToast(
                            'Position hors couverture Maroc',
                            `Le point (${lat.toFixed(3)}°N, ${lon.toFixed(3)}°W) est en dehors du périmètre MNT HydroSHEDS Maroc.`,
                            'warning'
                        );
                        return;
                    }

                    if (this.autoDelineateOnClick) {
                        this.triggerDelineation();
                    } else {
                        this.showToast(
                            'Exutoire positionné 🎯',
                            `Coordonnées : ${lat.toFixed(4)}°N, ${lon.toFixed(4)}°W. Cliquez sur "Délinéer" pour lancer le calcul.`,
                            'info',
                            '',
                            3000
                        );
                    }
                }
            });
        },

        createPickerIcon() {
            return L.divIcon({
                className: 'outlet-picker-pin',
                html: '<div class="outlet-picker-pin-inner"><i class="fa-solid fa-crosshairs"></i></div>',
                iconSize: [32, 32],
                iconAnchor: [16, 32],
                popupAnchor: [0, -32]
            });
        },

        setPickerLocation(lat, lon, panTo = false) {
            this.inputLat = parseFloat(Number(lat).toFixed(5));
            this.inputLon = parseFloat(Number(lon).toFixed(5));
            this.cursorInMorocco = this.isWithinMorocco(this.inputLat, this.inputLon);

            const popupContent = `
                <div style="font-size:12px; font-family:Inter,sans-serif; min-width:210px; padding:4px;">
                    <div style="font-weight:700; color:#0f766e; margin-bottom:4px; display:flex; align-items:center; justify-content:space-between;">
                        <span>🎯 Exutoire Cible</span>
                        <span style="font-size:10px; color:#64748b; font-weight:normal;">Glissable</span>
                    </div>
                    <div style="font-family:monospace; margin-bottom:6px; color:#1e293b; font-size:11px; background:#f8fafc; padding:3px 6px; border-radius:6px; border:1px solid #e2e8f0;">
                        Lat: ${this.inputLat.toFixed(4)}°N | Lon: ${this.inputLon.toFixed(4)}°W
                    </div>
                    <div style="margin-bottom:8px; font-size:11px;">
                        ${this.cursorInMorocco 
                            ? '<span style="color:#15803d; font-weight:600;"><i class="fa-solid fa-circle-check"></i> Zone MNT Maroc (Prêt)</span>' 
                            : '<span style="color:#be123c; font-weight:600;"><i class="fa-solid fa-triangle-exclamation"></i> Hors zone Maroc</span>'}
                    </div>
                    <button onclick="window.hydroAppInstance.triggerDelineation()" style="width:100%; background:linear-gradient(to right, #0f766e, #0369a1); color:white; border:none; padding:6px 10px; border-radius:8px; font-size:11px; font-weight:600; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:6px; box-shadow:0 2px 4px rgba(15,118,110,0.2);">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Délinéer depuis ce point
                    </button>
                </div>
            `;

            if (this.pickerMarker) {
                this.pickerMarker.setLatLng([this.inputLat, this.inputLon]);
                this.pickerMarker.setPopupContent(popupContent);
            } else if (this.map) {
                this.pickerMarker = L.marker([this.inputLat, this.inputLon], {
                    draggable: true,
                    icon: this.createPickerIcon()
                }).addTo(this.map);

                this.pickerMarker.bindPopup(popupContent);

                this.pickerMarker.on('drag', (e) => {
                    const pos = e.latlng;
                    this.inputLat = parseFloat(pos.lat.toFixed(5));
                    this.inputLon = parseFloat(pos.lng.toFixed(5));
                    this.cursorInMorocco = this.isWithinMorocco(this.inputLat, this.inputLon);
                });

                this.pickerMarker.on('dragend', (e) => {
                    const pos = e.latlng;
                    this.setPickerLocation(pos.lat, pos.lng);
                    if (this.autoDelineateOnClick && this.isWithinMorocco(this.inputLat, this.inputLon)) {
                        this.triggerDelineation();
                    }
                });
            }

            if (panTo && this.map) {
                this.map.panTo([this.inputLat, this.inputLon]);
            }
        },

        onCoordinateInput() {
            if (this.inputLat && this.inputLon) {
                this.setPickerLocation(this.inputLat, this.inputLon, true);
            }
        },

        applyPreset(preset) {
            this.setPickerLocation(preset.lat, preset.lon, true);
            this.showToast(
                `Point sélectionné : ${preset.name}`,
                `${preset.river} (${preset.desc}) positionné. Calcul en cours...`,
                'info',
                '',
                3000
            );
            this.triggerDelineation();
        },

        flyToRegion(region) {
            if (region === 'maroc' && this.map) {
                this.map.flyTo([31.8, -6.8], 6.5);
            }
        },

        centerOnPicker() {
            if (this.pickerMarker && this.map) {
                this.map.flyTo([this.inputLat, this.inputLon], 9);
                this.pickerMarker.openPopup();
            }
        },

        toggleLayer(country, layerName, isVisible) {
            const key = `${country}_${layerName}`;

            if (!isVisible) {
                if (this.leafletLayers[key] && this.map) {
                    this.map.removeLayer(this.leafletLayers[key]);
                }
                return;
            }

            if (this.leafletLayers[key] && this.map) {
                this.leafletLayers[key].addTo(this.map);
                return;
            }

            fetch(`/api/layers/${country}/${layerName}/`)
                .then(res => {
                    if (!res.ok) throw new Error(`Erreur HTTP ${res.status}`);
                    return res.json();
                })
                .then(geojson => {
                    const isDamLayer = layerName.includes('dam');
                    const layer = L.geoJSON(geojson, {
                        style: () => {
                            if (isDamLayer) {
                                return {
                                    color: '#0f766e',
                                    weight: 2,
                                    fillColor: '#14b8a6',
                                    fillOpacity: 0.28
                                };
                            }
                            return {
                                color: '#0284c7',
                                weight: 1.2,
                                fillColor: '#38bdf8',
                                fillOpacity: 0.12
                            };
                        },
                        onEachFeature: (feat, layerItem) => {
                            const p = feat.properties || {};
                            const title = p.nom || p.dam || p.basin_name || 'Bassin';
                            const area = p.area_km2 || p.total_area_km2 || '';
                            
                            layerItem.bindTooltip(`<b>${title}</b>${area ? ` (${Math.round(area)} km²)` : ''}`, {
                                sticky: true,
                                className: 'text-xs'
                            });

                            layerItem.on('click', (e) => {
                                L.DomEvent.stopPropagation(e);
                                if (p.nom) this.selectCatchment(p.nom);
                                else if (p.dam) this.selectCatchment(p.dam);
                            });
                        }
                    });

                    this.leafletLayers[key] = layer;
                    if (this.map) layer.addTo(this.map);
                })
                .catch(err => {
                    console.error(`Erreur couche ${key}:`, err);
                    this.showToast('Couche vectorielle', `Impossible de charger la couche ${layerName}.`, 'warning');
                });
        },

        triggerDelineation() {
            if (!this.inputLat || !this.inputLon) {
                this.showToast('Coordonnées requises', 'Veuillez renseigner la latitude et la longitude de l\'exutoire.', 'warning');
                return;
            }

            if (!this.isWithinMorocco(this.inputLat, this.inputLon)) {
                this.showToast(
                    'Position hors couverture Maroc',
                    `Les coordonnées (${this.inputLat}°N, ${this.inputLon}°W) sont hors de la grille MNT HydroSHEDS Maroc.`,
                    'warning'
                );
                return;
            }

            this.isLoading = true;

            // Nettoie systématiquement toute délinéation précédente pour libérer l'écran et le stockage
            this.clearDelineation(false);

            fetch('/api/delineate/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: this.inputLat,
                    lon: this.inputLon,
                    forcing_start_year: this.forcingStartYear
                })
            })
            .then(async res => {
                this.isLoading = false;
                let data;
                try {
                    data = await res.json();
                } catch (jsonErr) {
                    throw new Error("Réponse serveur invalide.");
                }

                if (res.ok && data.status === 'success') {
                    try {
                        this.applySimulationResults(data);
                        this.showToast(
                            'Bassin délinéé avec succès 🌊',
                            `Surface : ${data.envelope.area_km2} km² — Modèle LSTM exécuté.`,
                            'success',
                            '',
                            4000
                        );
                    } catch (renderErr) {
                        console.error('Erreur affichage résultats:', renderErr);
                        this.showToast('Erreur d\'affichage', 'Les calculs sont terminés mais le graphique a rencontré un problème.', 'warning');
                    }
                } else {
                    const msg = data.error || 'Veuillez vérifier les coordonnées.';
                    const hint = data.hint || 'Déplacez le curseur plus près d\'une vallée ou d\'un cours d\'eau.';
                    this.showToast('Délinéation impossible', msg, 'error', hint, 7000);
                }
            })
            .catch(err => {
                this.isLoading = false;
                console.error('Erreur réseau ou client:', err);
                this.showToast(
                    'Erreur de communication',
                    `Impossible de joindre le serveur : ${err.message || 'Erreur réseau.'}`,
                    'error',
                    'Vérifiez que le serveur Django est en cours d\'exécution.',
                    6000
                );
            });
        },

        selectCatchment(identifier) {
            this.isLoading = true;

            // Nettoie systématiquement toute délinéation précédente pour libérer l'écran et le stockage
            this.clearDelineation(false);

            fetch('/api/select-catchment/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    identifier: identifier,
                    forcing_start_year: this.forcingStartYear
                })
            })
            .then(async res => {
                this.isLoading = false;
                let data;
                try {
                    data = await res.json();
                } catch (jsonErr) {
                    throw new Error("Réponse serveur invalide.");
                }

                if (res.ok && data.status === 'success') {
                    this.applySimulationResults(data);
                    this.showToast(
                        'Barrage chargé avec succès',
                        `${data.envelope.area_km2} km² — Modèle LSTM exécuté.`,
                        'success',
                        '',
                        3500
                    );
                } else {
                    this.showToast('Bassin introuvable', data.error || 'Erreur de chargement du bassin.', 'error');
                }
            })
            .catch(err => {
                this.isLoading = false;
                console.error('Erreur:', err);
                this.showToast('Erreur serveur', 'Impossible de charger le bassin de barrage.', 'error');
            });
        },

        applySimulationResults(data) {
            this.currentRunId = data.run_id;
            this.currentAttributes = data.attributes;
            this.currentEnvelope = data.envelope;
            this.currentStats = { ...data.hydrograph.stats };
            this.originalFullStats = { ...data.hydrograph.stats };
            this.currentMetrics = data.hydrograph.metrics;

            if (data.basin_name) {
                this.currentBasinName = (data.station_code && !data.basin_name.includes(data.station_code))
                    ? `${data.basin_name} (${data.station_code})`
                    : data.basin_name;
            } else if (data.envelope && data.envelope.area_km2) {
                this.currentBasinName = `${data.envelope.area_km2} km²`;
            } else {
                this.currentBasinName = '';
            }

            this.hasSimulationData = true;
            this.simulationCache = data.hydrograph;

            // Définir l'intervalle strict des 10 ans simulé
            if (data.forcing_period && data.forcing_period.start_date && data.forcing_period.end_date) {
                this.forcingIntervalStart = data.forcing_period.start_date;
                this.forcingIntervalEnd = data.forcing_period.end_date;
            } else if (data.hydrograph && data.hydrograph.daily && data.hydrograph.daily.length > 0) {
                const daily = data.hydrograph.daily;
                this.forcingIntervalStart = daily[0].date;
                this.forcingIntervalEnd = daily[daily.length - 1].date;
            } else {
                this.forcingIntervalStart = '';
                this.forcingIntervalEnd = '';
            }

            // Initialiser les filtres temporels sur l'intervalle des 10 ans
            this.dateFilterStart = this.forcingIntervalStart;
            this.dateFilterEnd = this.forcingIntervalEnd;

            // S'assurer que le tiroir de graphique est en mode standard si minimisé
            if (this.chartDrawerState === 'minimized') {
                this.chartDrawerState = 'standard';
            }

            // Affichage du polygone délinéé sur la carte Leaflet
            if (data.feature && this.map) {
                this.activeCatchmentLayer = L.geoJSON(data.feature, {
                    style: {
                        color: '#0284c7',
                        weight: 2.2,
                        fillColor: '#0ea5e9',
                        fillOpacity: 0.25
                    }
                }).addTo(this.map);

                const bounds = this.activeCatchmentLayer.getBounds();
                if (bounds.isValid()) {
                    this.map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
                }

                // Marqueur de l'exutoire snappé par le modèle
                const props = data.feature.properties || {};
                const hasValidBounds = bounds && typeof bounds.isValid === 'function' && bounds.isValid();
                const outletLat = props.outlet_lat ?? (hasValidBounds ? bounds.getSouth() : null);
                const outletLon = props.outlet_lon ?? (hasValidBounds ? bounds.getCenter().lng : null);

                if (outletLat && outletLon) {
                    const customIcon = L.divIcon({
                        className: 'outlet-pulse',
                        html: '<div style="width:16px; height:16px; background:#0284c7; border:2.5px solid white; border-radius:50%; box-shadow: 0 0 12px rgba(2,132,199,0.6);"></div>',
                        iconSize: [16, 16],
                        iconAnchor: [8, 8]
                    });
                    this.outletMarker = L.marker([outletLat, outletLon], { icon: customIcon })
                        .bindTooltip(`<b>Exutoire Snappé</b><br>${outletLat.toFixed(4)}°N, ${outletLon.toFixed(4)}°W`, { sticky: true })
                        .addTo(this.map);
                    
                    this.setPickerLocation(outletLat, outletLon);
                }
            }

            // Enregistrer les résultats de l'audit anthropique
            this.currentAudit = data.audit || null;

            // Supprimer d'anciens marqueurs de barrages amont
            if (this.upstreamDamMarkers && this.upstreamDamMarkers.length > 0) {
                this.upstreamDamMarkers.forEach(m => this.map.removeLayer(m));
                this.upstreamDamMarkers = [];
            }

            // Si des barrages amont sont détectés dans le bassin, les afficher en rouge
            if (data.audit && Array.isArray(data.audit.upstream_dams) && data.audit.upstream_dams.length > 0 && this.map) {
                data.audit.upstream_dams.forEach(dam => {
                    const damIcon = L.divIcon({
                        className: 'upstream-dam-marker',
                        html: `<div style="width:28px; height:28px; background:#e11d48; border:2.5px solid white; border-radius:50%; display:flex; align-items:center; justify-content:center; color:white; font-size:11px; box-shadow: 0 0 12px rgba(225,29,72,0.65); cursor:pointer;">
                                   <i class="fa-solid fa-water-ladder"></i>
                               </div>`,
                        iconSize: [28, 28],
                        iconAnchor: [14, 14],
                        popupAnchor: [0, -14]
                    });
                    const cap = dam.capacity_hm3 || dam.capacity_Mm3 || '--';
                    const m = L.marker([dam.lat, dam.lon], { icon: damIcon })
                        .bindPopup(`
                            <div class="p-2.5 text-xs font-sans min-w-[210px]">
                                <div class="font-bold text-rose-800 flex items-center gap-1.5 border-b border-rose-100 pb-1 mb-1.5">
                                    <i class="fa-solid fa-water-ladder text-rose-600"></i>
                                    <span>${dam.name} (Barrage Amont)</span>
                                </div>
                                <div class="text-[11px] text-slate-600 space-y-0.5">
                                    <div><strong>Oued :</strong> ${dam.river || '--'}</div>
                                    <div><strong>Bassin :</strong> ${dam.basin || '--'}</div>
                                    <div><strong>Capacité :</strong> <span class="text-rose-700 font-bold">${cap} Mm³</span></div>
                                    <div><strong>Distance exutoire :</strong> ${dam.distance_to_outlet_km ? dam.distance_to_outlet_km + ' km' : '--'}</div>
                                </div>
                            </div>
                        `)
                        .bindTooltip(`<b>${dam.name}</b> (Barrage amont)<br>Capacité : ${cap} Mm³`, { sticky: true })
                        .addTo(this.map);
                    this.upstreamDamMarkers.push(m);
                });
            }

            // Mettre à jour le graphique Chart.js avec un léger délai pour laisser le temps au DOM de calculer les dimensions du canvas
            setTimeout(() => {
                this.updateChart();
            }, 120);
        },

        clearDelineation(notify = true) {
            // 1. Nettoyage écran : supprimer les polygones et marqueurs Leaflet
            if (this.activeCatchmentLayer && this.map) {
                this.map.removeLayer(this.activeCatchmentLayer);
                this.activeCatchmentLayer = null;
            }
            if (this.outletMarker && this.map) {
                this.map.removeLayer(this.outletMarker);
                this.outletMarker = null;
            }
            if (this.upstreamDamMarkers && this.upstreamDamMarkers.length > 0) {
                this.upstreamDamMarkers.forEach(m => this.map.removeLayer(m));
                this.upstreamDamMarkers = [];
            }
            this.currentAudit = null;

            // 2. Nettoyage écran : réinitialiser les données et métriques
            this.currentBasinName = '';
            this.currentRunId = null;
            this.currentEnvelope = null;
            this.currentAttributes = null;
            this.currentStats = null;
            this.originalFullStats = null;
            this.currentMetrics = null;
            this.hasSimulationData = false;
            this.simulationCache = null;
            this.dateFilterStart = '';
            this.dateFilterEnd = '';
            this.forcingIntervalStart = '';
            this.forcingIntervalEnd = '';

            // 3. Destruction propre du canvas et du graphique Chart.js
            if (this.chartInstance) {
                this.chartInstance.destroy();
                this.chartInstance = null;
            }
            const canvas = document.getElementById('hydrographCanvas');
            if (canvas) {
                const ctx = canvas.getContext('2d');
                if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
            }

            // 4. Nettoyage stockage serveur : supprimer les données temporaires en SQLite & cache
            fetch('/api/clear-delineation/', { method: 'POST' }).catch(() => {});

            if (notify) {
                this.showToast('Tracé effacé', 'Le bassin et les données de simulation ont été effacés et le stockage libéré.', 'info', '', 3000);
            }
        },

        onDateFilterChange() {
            if (!this.simulationCache) return;

            // Clamper strictement les sélections dans l'intervalle des 10 ans
            if (this.forcingIntervalStart && this.dateFilterStart) {
                if (this.dateFilterStart < this.forcingIntervalStart) {
                    this.dateFilterStart = this.forcingIntervalStart;
                }
            }
            if (this.forcingIntervalEnd && this.dateFilterEnd) {
                if (this.dateFilterEnd > this.forcingIntervalEnd) {
                    this.dateFilterEnd = this.forcingIntervalEnd;
                }
            }
            if (this.dateFilterStart && this.dateFilterEnd && this.dateFilterStart > this.dateFilterEnd) {
                this.dateFilterEnd = this.dateFilterStart;
            }

            this.updateChart();
        },

        resetDateFilter() {
            if (this.forcingIntervalStart && this.forcingIntervalEnd) {
                this.dateFilterStart = this.forcingIntervalStart;
                this.dateFilterEnd = this.forcingIntervalEnd;
            } else if (this.simulationCache && this.simulationCache.daily && this.simulationCache.daily.length > 0) {
                const daily = this.simulationCache.daily;
                this.dateFilterStart = daily[0].date;
                this.dateFilterEnd = daily[daily.length - 1].date;
            } else {
                this.dateFilterStart = '';
                this.dateFilterEnd = '';
            }
            this.updateChart();
        },

        recalculateFilteredStats(dailyList, monthlyList) {
            if (!this.originalFullStats) return;
            if (!dailyList || dailyList.length === 0) {
                this.currentStats = { ...this.originalFullStats };
                return;
            }

            let totalP = 0;
            let totalQmm = 0;
            let sumQ = 0;
            let peakQ = 0;
            for (let i = 0; i < dailyList.length; i++) {
                const d = dailyList[i];
                const prcp = Number(d.prcp_mm) || 0;
                const qMm = Number(d.q_sim_mm) || 0;
                const qM3s = Number(d.q_sim_m3s) || 0;
                totalP += prcp;
                totalQmm += qMm;
                sumQ += qM3s;
                if (qM3s > peakQ) peakQ = qM3s;
            }

            let totalVol = 0;
            if (monthlyList && monthlyList.length > 0) {
                for (let i = 0; i < monthlyList.length; i++) {
                    totalVol += (Number(monthlyList[i].sim_hm3) || 0);
                }
            } else if (this.currentAttributes && this.currentAttributes.area_km2) {
                totalVol = (totalQmm * Number(this.currentAttributes.area_km2)) / 1000.0;
            }

            const meanQ = sumQ / dailyList.length;
            const c_eff = totalP > 0.05 ? totalQmm / totalP : 0;

            this.currentStats = {
                total_precip_mm: Math.round(totalP * 10) / 10,
                total_sim_volume_hm3: Math.round(totalVol * 100) / 100,
                mean_sim_discharge_m3s: Math.round(meanQ * 100) / 100,
                peak_sim_discharge_m3s: Math.round(peakQ * 100) / 100,
                mean_sim_runoff_mm: Math.round(totalQmm * 10) / 10,
                runoff_coefficient: Math.round(c_eff * 1000) / 1000
            };
        },

        showToast(title, message, type = 'info', hint = '', duration = 6000) {
            if (this.toast.timeout) clearTimeout(this.toast.timeout);
            this.toast.title = title;
            this.toast.message = message;
            this.toast.type = type;
            this.toast.hint = hint;
            this.toast.visible = true;

            if (duration > 0) {
                this.toast.timeout = setTimeout(() => {
                    this.toast.visible = false;
                }, duration);
            }
        },

        closeToast() {
            this.toast.visible = false;
            if (this.toast.timeout) clearTimeout(this.toast.timeout);
        },

        setChartMode(mode) {
            this.chartMode = mode;
            this.updateChart();
        },

        updateChart() {
            const canvas = document.getElementById('hydrographCanvas');
            if (!canvas || !this.simulationCache) return;

            // Attach ResizeObserver sur le conteneur du canvas si pas encore fait
            if (window.ResizeObserver) {
                const container = canvas.parentElement;
                if (container && !container._hasResizeObserver) {
                    container._hasResizeObserver = true;
                    const ro = new ResizeObserver(() => {
                        if (this.chartInstance) {
                            this.chartInstance.resize();
                        }
                    });
                    ro.observe(container);
                }
            }

            // Détruire l'instance précédente
            if (this.chartInstance) {
                this.chartInstance.destroy();
                this.chartInstance = null;
            }

            const cache = this.simulationCache;
            const ctx = canvas.getContext('2d');

            // Extraction et filtrage temporel sur la plage [dateFilterStart, dateFilterEnd]
            let daily = cache.daily || [];
            let monthly = cache.monthly || [];

            if (this.dateFilterStart) {
                daily = daily.filter(d => d.date >= this.dateFilterStart);
                const startMonth = this.dateFilterStart.slice(0, 7);
                monthly = monthly.filter(m => m.month_str >= startMonth);
            }
            if (this.dateFilterEnd) {
                daily = daily.filter(d => d.date <= this.dateFilterEnd);
                const endMonth = this.dateFilterEnd.slice(0, 7);
                monthly = monthly.filter(m => m.month_str <= endMonth);
            }

            // Recalculer les statistiques sur la sous-période filtrée en temps réel
            this.recalculateFilteredStats(daily, monthly);

            if (this.chartMode === 'daily') {
                let dailyDisplay = daily;
                const isFullChronicle = (!this.dateFilterStart || this.dateFilterStart === this.forcingIntervalStart) &&
                                        (!this.dateFilterEnd || this.dateFilterEnd === this.forcingIntervalEnd);
                if (isFullChronicle && dailyDisplay.length > 730) {
                    dailyDisplay = dailyDisplay.slice(-730);
                }

                const labels = dailyDisplay.map(d => d.date);
                const qSim = dailyDisplay.map(d => d.q_sim_m3s);
                const precip = dailyDisplay.map(d => d.prcp_mm);

                let maxP = 5;
                let maxQ = 1;
                for (let i = 0; i < precip.length; i++) {
                    if (precip[i] > maxP) maxP = precip[i];
                }
                for (let i = 0; i < qSim.length; i++) {
                    if (qSim[i] > maxQ) maxQ = qSim[i];
                }

                this.chartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                type: 'line',
                                label: 'Débit Simulé LSTM (m³/s)',
                                data: qSim,
                                borderColor: '#0284c7',
                                backgroundColor: 'rgba(2, 132, 199, 0.12)',
                                borderWidth: 2,
                                pointRadius: 0,
                                fill: true,
                                tension: 0.15,
                                yAxisID: 'y'
                            },
                            {
                                type: 'bar',
                                label: 'Précipitation (mm/j)',
                                data: precip,
                                backgroundColor: 'rgba(15, 118, 110, 0.45)',
                                borderColor: '#0f766e',
                                borderWidth: 0.5,
                                yAxisID: 'yRain',
                                barThickness: 2
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        layout: {
                            padding: {
                                bottom: 6,
                                top: 4,
                                left: 4,
                                right: 4
                            }
                        },
                        interaction: {
                            mode: 'index',
                            intersect: false
                        },
                        plugins: {
                            legend: {
                                position: 'top',
                                labels: {
                                    color: '#475569',
                                    font: { size: 11, family: 'Inter', weight: '500' },
                                    boxWidth: 12,
                                    padding: 8
                                }
                            },
                            tooltip: {
                                backgroundColor: 'rgba(255, 255, 255, 0.96)',
                                borderColor: '#e2e8f0',
                                borderWidth: 1,
                                titleColor: '#0f172a',
                                bodyColor: '#334155',
                                padding: 8,
                                boxPadding: 4,
                                usePointStyle: true
                            }
                        },
                        scales: {
                            x: {
                                grid: { color: '#f8fafc' },
                                ticks: { 
                                    color: '#64748b', 
                                    maxTicksLimit: 10,
                                    maxRotation: 0,
                                    font: { size: 10, family: 'Inter' } 
                                }
                            },
                            y: {
                                position: 'left',
                                title: {
                                    display: true,
                                    text: 'Débit (m³/s)',
                                    color: '#0284c7',
                                    font: { size: 10, family: 'Inter', weight: '600' }
                                },
                                grid: { color: '#f1f5f9' },
                                ticks: { color: '#475569', font: { size: 9 } },
                                min: 0,
                                max: Math.ceil(maxQ * 1.25)
                            },
                            yRain: {
                                position: 'right',
                                reverse: true,
                                title: {
                                    display: true,
                                    text: 'Pluie (mm/j)',
                                    color: '#0f766e',
                                    font: { size: 10, family: 'Inter', weight: '600' }
                                },
                                grid: { display: false },
                                ticks: { color: '#0f766e', font: { size: 9 } },
                                min: 0,
                                max: Math.ceil(maxP * 2.8)
                            }
                        }
                    }
                });
            } else {
                // Mode Mensuel : Volume (hm³/mois) — uses pre-filtered 'monthly' from above

                const labels = monthly.map(m => m.month_str);
                const simVol = monthly.map(m => m.sim_hm3);
                const hasObs = cache.metrics && cache.metrics.has_obs;

                const datasets = [
                    {
                        type: 'bar',
                        label: 'Volume Simulé LSTM (hm³/mois)',
                        data: simVol,
                        backgroundColor: 'rgba(2, 132, 199, 0.65)',
                        borderColor: '#0284c7',
                        borderWidth: 1.2,
                        borderRadius: 4,
                        yAxisID: 'y'
                    }
                ];

                if (hasObs) {
                    const obsVol = monthly.map(m => (m.obs_hm3 !== undefined && m.obs_hm3 !== "" && m.obs_hm3 !== null) ? Number(m.obs_hm3) : null);
                    datasets.push({
                        type: 'line',
                        label: 'Débit Observé In Situ (hm³/mois)',
                        data: obsVol,
                        borderColor: '#d97706',
                        backgroundColor: 'transparent',
                        borderWidth: 2.4,
                        pointRadius: 3,
                        pointBackgroundColor: '#d97706',
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 1.5,
                        tension: 0.18,
                        yAxisID: 'y'
                    });
                }

                this.chartInstance = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: datasets
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        layout: {
                            padding: {
                                bottom: 6,
                                top: 4,
                                left: 4,
                                right: 4
                            }
                        },
                        interaction: {
                            mode: 'index',
                            intersect: false
                        },
                        plugins: {
                            legend: {
                                position: 'top',
                                labels: {
                                    color: '#475569',
                                    font: { size: 11, family: 'Inter', weight: '500' },
                                    boxWidth: 12,
                                    padding: 8
                                }
                            },
                            tooltip: {
                                backgroundColor: 'rgba(255, 255, 255, 0.96)',
                                borderColor: '#e2e8f0',
                                borderWidth: 1,
                                titleColor: '#0f172a',
                                bodyColor: '#334155',
                                padding: 8
                            }
                        },
                        scales: {
                            x: {
                                grid: { color: '#f8fafc' },
                                ticks: { color: '#64748b', font: { size: 10, family: 'Inter' } }
                            },
                            y: {
                                position: 'left',
                                title: {
                                    display: true,
                                    text: 'Volume (hm³/mois)',
                                    color: '#0284c7',
                                    font: { size: 10, family: 'Inter', weight: '600' }
                                },
                                grid: { color: '#f1f5f9' },
                                ticks: { color: '#475569', font: { size: 9 } },
                                min: 0
                            }
                        }
                    }
                });
            }
        },

        toggleRiversLayer(visible) {
            if (!visible) {
                if (this.leafletLayers['morocco_rivers'] && this.map) {
                    this.map.removeLayer(this.leafletLayers['morocco_rivers']);
                    delete this.leafletLayers['morocco_rivers'];
                }
                return;
            }

            if (this.leafletLayers['morocco_rivers'] && this.map) {
                this.leafletLayers['morocco_rivers'].addTo(this.map);
                return;
            }

            this.showToast('Chargement réseau', 'Affichage du réseau hydrographique des oueds...', 'info', '', 2000);

            // Charger morocco_rivers_light.geojson via /api/rivers/ ou statique
            fetch('/api/rivers/')
                .then(r => {
                    if (!r.ok) return fetch('/static/data/morocco_rivers_light.geojson').then(res => res.json());
                    return r.json();
                })
                .then(geojson => {
                    const riversLayer = L.geoJSON(geojson, {
                        style: {
                            color: '#0284c7',
                            weight: 1.6,
                            opacity: 0.82
                        },
                        onEachFeature: (feature, layer) => {
                            const props = feature.properties || {};
                            const len = props.LENGTH_KM ? `${props.LENGTH_KM.toFixed(1)} km` : '';
                            const ord = props.ORD_STRA ? `Ordre ${props.ORD_STRA}` : '';
                            layer.bindTooltip(`<b>Oued (HydroRIVERS)</b><br>${ord} ${len ? '• ' + len : ''}`, { sticky: true });
                        }
                    });

                    this.leafletLayers['morocco_rivers'] = riversLayer;
                    riversLayer.addTo(this.map);
                    this.showToast('Réseau actif', 'Réseau hydrographique affiché sur la carte.', 'success', '', 2500);
                })
                .catch(err => {
                    console.error('Erreur chargement oueds:', err);
                    this.showToast('Erreur', 'Impossible de charger le réseau hydrographique.', 'error');
                });
        },

        toggleAllDamsLayer(visible) {
            if (!visible) {
                if (this.allDamsLayer && this.map && this.map.hasLayer(this.allDamsLayer)) {
                    this.map.removeLayer(this.allDamsLayer);
                }
                return;
            }

            if (this.allDamsLayer && this.map) {
                this.allDamsLayer.addTo(this.map);
                return;
            }

            fetch('/api/dams/')
                .then(res => res.json())
                .then(data => {
                    this.allDamsLayer = L.geoJSON(data, {
                        pointToLayer: (feature, latlng) => {
                            const damIcon = L.divIcon({
                                className: 'custom-dam-marker',
                                html: `<div class="w-7 h-7 bg-indigo-700 hover:bg-indigo-800 text-white rounded-full flex items-center justify-center shadow-md border-2 border-white transition-transform hover:scale-125 cursor-pointer">
                                           <i class="fa-solid fa-landmark-dome text-[11px]"></i>
                                       </div>`,
                                iconSize: [28, 28],
                                iconAnchor: [14, 14],
                                popupAnchor: [0, -14]
                            });
                            return L.marker(latlng, { icon: damIcon });
                        },
                        onEachFeature: (feature, layer) => {
                            const p = feature.properties || {};
                            const cap = p.capacity_hm3 || p.cap_hm3 || p.capacity_Mm3 || '--';
                            const popupHtml = `
                                <div class="p-2.5 font-sans min-w-[240px]">
                                    <div class="flex items-center space-x-2 border-b border-indigo-100 pb-1.5 mb-2">
                                        <span class="w-6 h-6 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs">
                                            <i class="fa-solid fa-landmark-dome"></i>
                                        </span>
                                        <div>
                                            <h4 class="font-bold text-xs text-slate-900 leading-tight">${p.name || 'Barrage'}</h4>
                                            <span class="text-[10px] text-slate-500">${p.basin || ''} — Oued ${p.river || ''}</span>
                                        </div>
                                    </div>
                                    <div class="grid grid-cols-2 gap-1.5 text-[11px] mb-2">
                                        <div class="bg-indigo-50/70 p-1.5 rounded-lg border border-indigo-100">
                                            <span class="text-[9.5px] text-indigo-700 font-semibold block">Capacité Retenue</span>
                                            <span class="font-bold text-indigo-950">${cap} Mm³</span>
                                        </div>
                                        <div class="bg-slate-50 p-1.5 rounded-lg border border-slate-200">
                                            <span class="text-[9.5px] text-slate-500 font-semibold block">Hauteur Digue</span>
                                            <span class="font-bold text-slate-800">${p.height_m ? p.height_m + ' m' : '--'}</span>
                                        </div>
                                    </div>
                                    <div class="text-[10px] text-slate-600 space-y-0.5 border-t border-slate-100 pt-1.5">
                                        <div><strong class="text-slate-700">Mise en service :</strong> ${p.year || '--'}</div>
                                        <div><strong class="text-slate-700">Usage :</strong> ${p.purpose || 'Irrigation, AEP'}</div>
                                    </div>
                                </div>
                            `;
                            layer.bindPopup(popupHtml, { maxWidth: 300, className: 'modern-dam-popup' });
                            layer.bindTooltip((p.name || 'Barrage') + ` (${cap} Mm³)`, {
                                direction: 'top',
                                offset: [0, -12],
                                opacity: 0.95
                            });
                        }
                    });
                    if (this.map) this.allDamsLayer.addTo(this.map);
                    this.showToast('Barrages affichés', '45 grands barrages du Maroc affichés sur la carte.', 'success', '', 2500);
                })
                .catch(err => {
                    console.error("Erreur de chargement des barrages:", err);
                    this.showToast('Erreur', 'Impossible de charger la couche des barrages.', 'error');
                });
        },

        exportCSV(overrideMode = null) {
            if (!this.hasSimulationData || !this.simulationCache) {
                this.showToast('Export impossible', 'Veuillez d\'abord sélectionner une station ou délinéer un bassin.', 'warning');
                return;
            }

            const step = overrideMode || (this.chartMode === 'monthly' ? 'mensuel' : 'journalier');

            // 1. Privilégier l'API serveur Django native (fiabilité 100%, streaming HTTP avec Content-Disposition, aucun risque de révocation Blob)
            if (this.currentRunId) {
                const url = `/api/export-csv/?run_id=${encodeURIComponent(this.currentRunId)}&timestep=${encodeURIComponent(step)}`;
                const link = document.createElement('a');
                link.href = url;
                link.setAttribute('download', '');
                link.style.display = 'none';
                document.body.appendChild(link);
                link.click();
                setTimeout(() => {
                    if (link.parentNode) link.parentNode.removeChild(link);
                }, 2000);

                const label = (step === 'mensuel') ? 'mensuelles (hm³)' : 'journalières (m³/s)';
                this.showToast('Export CSV', `Téléchargement des données ${label} lancé.`, 'success', '', 3500);
                return;
            }

            // 2. Mode de secours côté client (si run_id non encore synchronisé)
            const basin = (this.currentBasinName || 'bassin')
                .normalize('NFKD')
                .replace(/[\u0300-\u036f]/g, '')
                .replace(/[^a-zA-Z0-9_-]/g, '_')
                .replace(/_+/g, '_')
                .replace(/^_|_$/g, '');
            
            const area = this.currentArea ? `${Math.round(this.currentArea)}km2` : '';
            
            let csvRows = [];
            let filename = '';

            if (step === 'mensuel') {
                const monthly = this.simulationCache.monthly || [];
                if (monthly.length === 0) {
                    this.showToast('Erreur', 'Aucune donnée mensuelle disponible pour l\'export.', 'error');
                    return;
                }

                const startYr = monthly[0].month_str ? monthly[0].month_str.substring(0, 4) : '';
                const endYr = monthly[monthly.length - 1].month_str ? monthly[monthly.length - 1].month_str.substring(0, 4) : '';
                const periodStr = (startYr && endYr) ? `_${startYr}_${endYr}` : '';
                
                filename = `hydrogramme_mensuel_${basin}${area ? '_' + area : ''}${periodStr}.csv`;

                const hasObs = monthly.some(r => r.obs_hm3 !== null && r.obs_hm3 !== undefined && r.obs_hm3 !== '');
                
                if (hasObs) {
                    csvRows.push([
                        "mois", "nom_bassin", "superficie_km2", "precipitation_mm",
                        "debit_simule_m3s", "volume_simule_hm3",
                        "debit_observe_m3s", "volume_observe_hm3",
                        "ecart_volume_hm3", "ratio_sim_obs"
                    ].join(","));

                    for (const r of monthly) {
                        const vSim = (r.sim_hm3 !== null && r.sim_hm3 !== undefined) ? Number(r.sim_hm3) : 0;
                        const vObs = (r.obs_hm3 !== null && r.obs_hm3 !== undefined && r.obs_hm3 !== '') ? Number(r.obs_hm3) : null;
                        const diff = (vObs !== null) ? (vSim - vObs).toFixed(3) : '';
                        const ratio = (vObs !== null && vObs > 0) ? (vSim / vObs).toFixed(3) : '';
                        const qObs = (r.obs_q_m3s !== null && r.obs_q_m3s !== undefined) ? r.obs_q_m3s : '';

                        csvRows.push([
                            r.month_str || '',
                            `"${this.currentBasinName}"`,
                            this.currentArea || '',
                            r.prcp_mm !== undefined ? r.prcp_mm : '',
                            r.sim_q_m3s !== undefined ? r.sim_q_m3s : '',
                            r.sim_hm3 !== undefined ? r.sim_hm3 : '',
                            qObs,
                            vObs !== null ? vObs : '',
                            diff,
                            ratio
                        ].join(","));
                    }
                } else {
                    csvRows.push([
                        "mois", "nom_bassin", "superficie_km2", "precipitation_mm",
                        "debit_simule_m3s", "volume_simule_hm3"
                    ].join(","));

                    for (const r of monthly) {
                        csvRows.push([
                            r.month_str || '',
                            `"${this.currentBasinName}"`,
                            this.currentArea || '',
                            r.prcp_mm !== undefined ? r.prcp_mm : '',
                            r.sim_q_m3s !== undefined ? r.sim_q_m3s : '',
                            r.sim_hm3 !== undefined ? r.sim_hm3 : ''
                        ].join(","));
                    }
                }
            } else {
                const daily = this.simulationCache.daily || [];
                if (daily.length === 0) {
                    this.showToast('Erreur', 'Aucune donnée journalière disponible pour l\'export.', 'error');
                    return;
                }

                const startYr = daily[0].date ? daily[0].date.substring(0, 4) : '';
                const endYr = daily[daily.length - 1].date ? daily[daily.length - 1].date.substring(0, 4) : '';
                const periodStr = (startYr && endYr) ? `_${startYr}_${endYr}` : '';
                
                filename = `hydrogramme_journalier_${basin}${area ? '_' + area : ''}${periodStr}.csv`;

                csvRows.push([
                    "date", "nom_bassin", "superficie_km2",
                    "precipitation_era5_mm", "evapotranspiration_pet_mm",
                    "temperature_min_c", "temperature_max_c",
                    "lame_ecoulee_simulee_mm", "debit_simule_m3s", "volume_simule_hm3"
                ].join(","));

                for (const r of daily) {
                    const qM3s = (r.q_sim_m3s !== null && r.q_sim_m3s !== undefined) ? Number(r.q_sim_m3s) : 0;
                    const volHm3 = (qM3s * 0.0864).toFixed(4);
                    csvRows.push([
                        r.date || '',
                        `"${this.currentBasinName}"`,
                        this.currentArea || '',
                        r.prcp_mm !== undefined ? r.prcp_mm : '',
                        r.pet_mm !== undefined ? r.pet_mm : '',
                        r.tmin_c !== undefined ? r.tmin_c : '',
                        r.tmax_c !== undefined ? r.tmax_c : '',
                        r.q_sim_mm !== undefined ? r.q_sim_mm : '',
                        qM3s.toFixed(4),
                        volHm3
                    ].join(","));
                }
            }

            // Ajout du BOM UTF-8 (\ufeff) pour ouverture directe et correcte sous Excel (Windows)
            const csvContent = "\ufeff" + csvRows.join("\r\n");
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            
            // Déclencheur de téléchargement natif du navigateur avec nom explicite garanti
            const link = document.createElement("a");
            const blobUrl = URL.createObjectURL(blob);
            link.setAttribute("href", blobUrl);
            link.setAttribute("download", filename);
            link.style.display = 'none';
            document.body.appendChild(link);
            link.click();
            
            // Sécurité : Ne jamais révoquer le blob immédiatement (ex: 500ms).
            // Sur Edge et Chrome sous Windows, Windows Defender SmartScreen et l'allocation disque
            // prennent du temps. Si le blob est révoqué avant la fin de l'écriture disque,
            // le navigateur avorte le téléchargement, le marque "Supprimé" et affiche l'UUID du blob sans extension.
            setTimeout(() => {
                if (link.parentNode) link.parentNode.removeChild(link);
                setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
            }, 1000);

            const label = (step === 'mensuel') ? 'mensuelles (hm³)' : 'journalières (m³/s)';
            this.showToast('Export CSV Réussi', `Fichier "${filename}" téléchargé (${label}).`, 'success', '', 3500);
        }
    };
}
