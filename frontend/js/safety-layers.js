/**
 * Safety Layers Module
 * Handles safety analysis visualization and interaction
 */

class SafetyLayersManager {
    constructor(map) {
        this.map = map;
        this.layers = {};
        this.controls = {};
        this.safetyData = null;
        this.init();
    }

    async init() {
        console.log('Shield Initializing Safety Layers Manager...');
        await this.loadSafetyData();
        this.createSafetyPanel();
        this.createLayers();
    }

    async loadSafetyData() {
        try {
            const response = await fetch('/api/safety/mitte/summary');
            const data = await response.json();
            this.safetyData = data.data;
            console.log('Checkmark Safety data loaded:', this.safetyData);
        } catch (error) {
            console.error('X Failed to load safety data:', error);
        }
    }

    createSafetyPanel() {
        // Find the layers panel
        const layersPanel = document.querySelector('.layers-panel');
        if (!layersPanel) return;

        // Create safety section
        const safetySection = document.createElement('div');
        safetySection.className = 'safety-section';
        safetySection.innerHTML = `
            <div class="safety-header">
                <h3>Shield Safety Analysis (Mitte)</h3>
                <span class="safety-badge">
                    ${this.safetyData && this.safetyData.risk_level ? this.safetyData.risk_level : 'Loading...'}
                </span>
            </div>
            <div class="safety-score">
                <div class="score-bar">
                    <div class="score-fill" style="width: ${this.safetyData && this.safetyData.composite_risk_score ? this.safetyData.composite_risk_score : 0}%"></div>
                </div>
                <span class="score-text">${this.safetyData && this.safetyData.composite_risk_score ? this.safetyData.composite_risk_score : 0}/100</span>
            </div>
            <div class="safety-toggles">
                <label class="toggle-item">
                    <input type="checkbox" id="toggle-lighting" checked>
                    <span>Lightbulb Street Lighting (${this.safetyData && this.safetyData.assessments && this.safetyData.assessments.A_Lighting ? this.safetyData.assessments.A_Lighting.street_lights_count : 0})</span>
                </label>
                <label class="toggle-item">
                    <input type="checkbox" id="toggle-activity" checked>
                    <span>Car Activity Nodes (${this.safetyData && this.safetyData.assessments && this.safetyData.assessments.B_Mobility ? this.safetyData.assessments.B_Mobility.findings.total_activity_pois : 0})</span>
                </label>
                <label class="toggle-item">
                    <input type="checkbox" id="toggle-emergency" checked>
                    <span>Ambulance Emergency Services</span>
                </label>
                <label class="toggle-item">
                    <input type="checkbox" id="toggle-buildings">
                    <span>Building Buildings</span>
                </label>
            </div>
            <div class="safety-details">
                <h4>Component Scores</h4>
                <div class="component-score">
                    <span>Lighting</span>
                    <span class="score">${this.safetyData && this.safetyData.component_scores ? this.safetyData.component_scores.lighting_visibility : 0}</span>
                </div>
                <div class="component-score">
                    <span>Mobility</span>
                    <span class="score">${this.safetyData && this.safetyData.component_scores ? this.safetyData.component_scores.mobility_crowdedness : 0}</span>
                </div>
                <div class="component-score">
                    <span>Connectivity</span>
                    <span class="score">${this.safetyData && this.safetyData.component_scores ? this.safetyData.component_scores.connectivity_accessibility : 0}</span>
                </div>
                <div class="component-score">
                    <span>Visibility</span>
                    <span class="score">${this.safetyData && this.safetyData.component_scores ? this.safetyData.component_scores.visibility_surveillance : 0}</span>
                </div>
                <div class="component-score">
                    <span>Operations</span>
                    <span class="score">${this.safetyData && this.safetyData.component_scores ? this.safetyData.component_scores.operational_safety : 0}</span>
                </div>
            </div>
        `;

        layersPanel.insertBefore(safetySection, layersPanel.firstChild);

        // Add event listeners
        const lightingToggle = document.getElementById('toggle-lighting');
        const activityToggle = document.getElementById('toggle-activity');
        const emergencyToggle = document.getElementById('toggle-emergency');
        const buildingsToggle = document.getElementById('toggle-buildings');

        if (lightingToggle) lightingToggle.addEventListener('change', (e) => {
            this.toggleLayer('lighting', e.target.checked);
        });
        if (activityToggle) activityToggle.addEventListener('change', (e) => {
            this.toggleLayer('activity', e.target.checked);
        });
        if (emergencyToggle) emergencyToggle.addEventListener('change', (e) => {
            this.toggleLayer('emergency', e.target.checked);
        });
        if (buildingsToggle) buildingsToggle.addEventListener('change', (e) => {
            this.toggleLayer('buildings', e.target.checked);
        });
    }

    async createLayers() {
        try {
            // Load and create Mitte boundary
            const boundaryResponse = await fetch('/api/safety/mitte/geojson');
            const boundaryData = await boundaryResponse.json();

            this.layers.boundary = L.geoJSON(boundaryData, {
                style: {
                    color: '#FFB162',
                    weight: 3,
                    opacity: 0.7,
                    fillOpacity: 0.1
                },
                onEachFeature: (feature, layer) => {
                    const props = feature.properties;
                    layer.bindPopup(`
                        <strong>${props.name}</strong><br>
                        Safety Score: ${props.safety_score}/100<br>
                        Risk Level: ${props.risk_level}<br>
                        Area: ${props.area_km2 ? props.area_km2.toFixed(2) : 'N/A'} km²
                    `);
                }
            }).addTo(this.map);

            // Load street lighting
            const lightingResponse = await fetch('/api/safety/mitte/lighting');
            const lightingData = await lightingResponse.json();

            this.layers.lighting = L.geoJSON(lightingData, {
                pointToLayer: (feature, latlng) => {
                    return L.circleMarker(latlng, {
                        radius: 2,
                        fillColor: '#FFD700',
                        color: '#FFA500',
                        weight: 1,
                        opacity: 0.8,
                        fillOpacity: 0.6
                    });
                },
                onEachFeature: (feature, layer) => {
                    layer.bindPopup('Street Light');
                }
            }).addTo(this.map);

            // Load activity nodes
            const activityResponse = await fetch('/api/safety/mitte/activity-nodes');
            const activityData = await activityResponse.json();

            this.layers.activity = L.geoJSON(activityData, {
                pointToLayer: (feature, latlng) => {
                    const poiType = feature.properties.poi_type;
                    let color = '#FF6B6B';

                    if (poiType === 'transport_stop') {
                        color = '#4ECDC4';
                    } else if (poiType === 'park') {
                        color = '#95E1D3';
                    }

                    return L.circleMarker(latlng, {
                        radius: 4,
                        fillColor: color,
                        color: color,
                        weight: 2,
                        opacity: 0.9,
                        fillOpacity: 0.7
                    });
                },
                onEachFeature: (feature, layer) => {
                    const name = feature.properties.name || 'Activity Node';
                    layer.bindPopup(`
                        <strong>${name}</strong><br>
                        Type: ${feature.properties.poi_type}
                    `);
                }
            }).addTo(this.map);

            // Load emergency services
            const emergencyResponse = await fetch('/api/safety/mitte/emergency-services');
            const emergencyData = await emergencyResponse.json();

            this.layers.emergency = L.geoJSON(emergencyData, {
                pointToLayer: (feature, latlng) => {
                    const serviceType = feature.properties.service_type;
                    let color = '#FF0000';
                    let radius = 5;

                    if (serviceType === 'hospital') {
                        color = '#FF1744';
                        radius = 6;
                    } else if (serviceType === 'police') {
                        color = '#2196F3';
                    } else if (serviceType === 'fire_station') {
                        color = '#FF9800';
                    }

                    return L.circleMarker(latlng, {
                        radius: radius,
                        fillColor: color,
                        color: 'white',
                        weight: 2,
                        opacity: 1,
                        fillOpacity: 0.8
                    });
                },
                onEachFeature: (feature, layer) => {
                    const name = feature.properties.name || 'Emergency Service';
                    layer.bindPopup(`
                        <strong>${name}</strong><br>
                        Type: ${feature.properties.service_type}
                    `);
                }
            }).addTo(this.map);

            // Load buildings sample
            const buildingsResponse = await fetch('/api/safety/mitte/buildings');
            const buildingsData = await buildingsResponse.json();

            this.layers.buildings = L.geoJSON(buildingsData, {
                style: {
                    color: '#9C27B0',
                    weight: 1,
                    opacity: 0.4,
                    fillOpacity: 0.2
                }
            });

            console.log('Checkmark All safety layers created');

            // Zoom to Mitte
            this.map.fitBounds(this.layers.boundary.getBounds());

        } catch (error) {
            console.error('X Failed to create layers:', error);
        }
    }

    toggleLayer(layerName, isVisible) {
        const layer = this.layers[layerName];
        if (!layer) return;

        if (isVisible) {
            this.map.addLayer(layer);
        } else {
            this.map.removeLayer(layer);
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (typeof map !== 'undefined') {
        window.safetyManager = new SafetyLayersManager(map);
    }
});
