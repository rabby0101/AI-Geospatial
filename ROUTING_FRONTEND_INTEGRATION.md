# Frontend Routing Integration Guide

This guide provides the exact code changes needed to integrate the routing feature into the frontend.

## Phase 3: Frontend Integration

### 1. Modify executeSearch() Function (Line 5918)

**Add routing detection logic at the start of executeSearch:**

```javascript
// Add this after line 5931 (after setLoading(true))
const routingKeywords = ['route', 'directions', 'navigate', 'routing', 'path', 'journey', 'tour', 'visit', 'loop', 'best route', 'find route'];
const isRoutingQuery = routingKeywords.some(keyword => query.toLowerCase().includes(keyword));
const hasSelectedFeatures = selectedFeatures && selectedFeatures.length >= 2;

// If routing query with 2+ selected features, call routing endpoint directly
if (isRoutingQuery && hasSelectedFeatures) {
    console.log(`🛣️  Routing query detected with ${selectedFeatures.length} selected features`);

    try {
        const payload = {
            geometries: selectedFeatures.map(f => f.geometry),
            feature_names: selectedFeatures.map(f => {
                if (f.properties && f.properties.name) return f.properties.name;
                if (f.name) return f.name;
                return `Point ${selectedFeatures.indexOf(f) + 1}`;
            })
        };

        const response = await fetch(`${API_URL}/routing/optimal-tour`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const routingData = await response.json();
        console.log('🛣️  Routing response:', routingData);

        if (routingData.success) {
            // Create GeoJSON FeatureCollection
            const geojson = {
                type: 'FeatureCollection',
                features: [{
                    type: 'Feature',
                    geometry: routingData.geometry,
                    properties: {
                        total_distance_m: routingData.total_distance_m,
                        total_time_minutes: routingData.total_time_minutes,
                        waypoint_count: routingData.waypoints.length
                    }
                }]
            };

            // Clear previous layers in single mode
            if (queryMode === 'single') {
                clearAllQueries();
            }

            // Add route layer
            const layerName = routingData.layer_name || 'optimal_route';
            addLayer(
                layerName,
                geojson,
                query,
                [],
                routingData.reasoning || 'Computed optimal route',
                ['routing.ways', 'routing.ways_vertices_pgr'],
                routingData.metadata,
                routingData.execution_time_ms / 1000
            );

            // Show directions panel
            if (routingData.directions && routingData.directions.length > 0) {
                showDirectionsPanel(routingData.directions, layerName);
            }

            showNotification(`✅ Route computed: ${routingData.total_distance_m}m (${routingData.total_time_minutes} min)`, 'success');

            // Clear selected features after routing
            clearAllSelections();
        } else {
            showNotification(routingData.error || 'Routing failed', 'error');
        }

        return; // Exit early - routing handled

    } catch (error) {
        console.error('Routing error:', error);
        showNotification('Error computing route: ' + error.message, 'error');
        return;
    }
}
```

### 2. Add Directions Panel Function

Add this new function somewhere in the global scope:

```javascript
function showDirectionsPanel(directions, layerName) {
    // Create or update directions panel
    let directionsPanel = document.getElementById('directionsPanel');

    if (!directionsPanel) {
        // Create panel if it doesn't exist
        directionsPanel = document.createElement('div');
        directionsPanel.id = 'directionsPanel';
        directionsPanel.className = 'operations-panel';
        directionsPanel.style.right = '0px';
        directionsPanel.innerHTML = `
            <div style="padding: 15px; color: white;">
                <div style="font-size: 14px; font-weight: bold; margin-bottom: 10px;">
                    📍 Directions
                    <button onclick="closeDirectionsPanel()" style="float: right; background: none; border: none; color: #F1642E; cursor: pointer; font-size: 18px;">×</button>
                </div>
                <div id="directionsContent" style="max-height: 500px; overflow-y: auto;"></div>
            </div>
        `;
        document.body.appendChild(directionsPanel);
    }

    // Populate directions
    const directionsContent = document.getElementById('directionsContent');
    let html = '<ol style="padding-left: 20px; line-height: 1.6; font-size: 13px;">';

    directions.forEach((step, idx) => {
        const bgColor = idx % 2 === 0 ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0)';
        html += `
            <li style="background: ${bgColor}; padding: 8px; margin: 4px 0; border-radius: 4px;">
                <strong>${step.instruction}</strong>
                ${step.street ? `<br><small>📍 ${step.street}</small>` : ''}
                ${step.distance_m > 0 ? `<br><small>📏 ${Math.round(step.distance_m)}m` : ''}
                ${step.duration_seconds ? ` (${Math.round(step.duration_seconds / 60)} min)</small>` : ''}
            </li>
        `;
    });

    html += '</ol>';
    directionsContent.innerHTML = html;
}

function closeDirectionsPanel() {
    const panel = document.getElementById('directionsPanel');
    if (panel) {
        panel.remove();
    }
}
```

### 3. Add Directions Panel CSS

Add this CSS to the `<style>` section (around line 300-400):

```css
#directionsPanel {
    position: fixed;
    right: 0;
    top: 120px;
    width: 350px;
    height: calc(100vh - 140px);
    background: linear-gradient(135deg, rgba(15, 13, 26, 0.95) 0%, rgba(37, 31, 53, 0.95) 100%);
    border: 1px solid rgba(241, 100, 46, 0.3);
    border-left: 2px solid #F1642E;
    border-radius: 12px;
    padding: 0;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(25px);
    z-index: 999;
    overflow: hidden;
}

#directionsPanel > div {
    height: 100%;
    overflow-y: auto;
}

#directionsContent ol {
    margin: 0;
}

#directionsContent li {
    word-wrap: break-word;
    list-style-position: inside;
}
```

### 4. Update Existing addLayer() Function

The addLayer() function needs to handle routing results properly. Find the addLayer function and ensure it handles the new routing metadata format.

If routing metadata includes waypoints and directions, update the operation details display to show them.

### 5. Update Selected Features Collection

Ensure selectedFeatures is properly populated. Find where selectedFeatures array is used and verify it contains full feature objects with geometry and properties.

Current structure should be:
```javascript
selectedFeatures = [
    {
        geometry: {type: "Point", coordinates: [...]},
        properties: {name: "Hospital A", ...},
        name: "Hospital A"
    },
    ...
]
```

### 6. Update Multi-Select Feature Storage

When features are selected, ensure they're stored in the selectedFeatures array with full geometry and properties:

Find `addFeatureToSelection()` function (around line 5500-5600) and update it to store full feature data:

```javascript
function addFeatureToSelection(feature, layer) {
    if (!selectedFeatures) selectedFeatures = [];

    // Store full feature with geometry and properties
    const selectedFeature = {
        geometry: feature.geometry ? feature.geometry : L.GeoJSON.asFeature(feature).geometry,
        properties: feature.properties || {},
        name: feature.properties?.name || feature.name || `Feature ${selectedFeatures.length + 1}`
    };

    selectedFeatures.push(selectedFeature);
    selectedFeatureLayers.push(layer);

    // Update UI
    updateSelectedFeaturePill();
}
```

### 7. Verify Selected Feature Pill Display

The selected features pill should show: "N items selected" - this already exists in the code, no changes needed.

## Testing the Implementation

Once all changes are made:

1. Open the application in browser
2. Select 2-3 features on the map with Shift+click
3. Type in search: "find the best route"
4. Click Search button
5. Verify:
   - Route line appears on map (orange color)
   - Directions panel appears on right side
   - Total distance and time displayed
   - Turn-by-turn directions shown

## Expected Output

When routing query is executed with 3 selected points (Hospital A, School B, Park C):

**Map Display:**
- Single orange LineString connecting all 3 points in optimal order
- Numbered waypoint markers (1, 2, 3)

**Directions Panel:**
- Start at Hospital A
- Head northeast on Hauptstrasse for 1200m
- Turn left on Friedrichstrasse for 800m
- Arrive at School B (waypoint 2)
- ... (continue for all segments)
- Return to Hospital A (end)

**Layers Panel:**
- New layer: "Optimal Route: Hospital A → School B → Park C"
- Color picker available
- Toggle visibility
- Delete button

**Metadata Display:**
- Total Distance: 5.2 km
- Estimated Time: 12 minutes
- Waypoints: 3
- Algorithm: Nearest Neighbor TSP
