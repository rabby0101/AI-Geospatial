/**
 * Turf.js Utilities Module
 * Provides convenient wrapper functions for common geospatial operations
 * using the Turf.js library.
 */

const TurfUtils = {
    /**
     * Calculate distance between two points
     * @param {Array} point1 - [longitude, latitude]
     * @param {Array} point2 - [longitude, latitude]
     * @param {string} units - 'kilometers', 'miles', 'meters', etc.
     * @returns {number} Distance in specified units
     */
    calculateDistance: function (point1, point2, units = 'kilometers') {
        const from = turf.point(point1);
        const to = turf.point(point2);
        return turf.distance(from, to, { units: units });
    },

    /**
     * Create a buffer around a geometry
     * @param {Object} geometry - GeoJSON geometry or Leaflet layer
     * @param {number} radius - Buffer radius
     * @param {string} units - 'kilometers', 'miles', 'meters', etc.
     * @returns {Object} Buffered GeoJSON polygon
     */
    createBuffer: function (geometry, radius, units = 'kilometers') {
        const geojson = this._toGeoJSON(geometry);
        return turf.buffer(geojson, radius, { units: units });
    },

    /**
     * Check if a point is inside a polygon
     * @param {Array} point - [longitude, latitude]
     * @param {Object} polygon - GeoJSON polygon or Leaflet layer
     * @returns {boolean} True if point is inside polygon
     */
    pointInPolygon: function (point, polygon) {
        const pt = turf.point(point);
        const poly = this._toGeoJSON(polygon);
        return turf.booleanPointInPolygon(pt, poly);
    },

    /**
     * Calculate area of a polygon
     * @param {Object} polygon - GeoJSON polygon or Leaflet layer
     * @param {string} units - 'kilometers', 'miles', 'meters', 'acres', 'hectares'
     * @returns {number} Area in specified units
     */
    calculateArea: function (polygon, units = 'kilometers') {
        const geojson = this._toGeoJSON(polygon);
        const areaInMeters = turf.area(geojson);

        const conversions = {
            'meters': 1,
            'kilometers': 1e-6,
            'miles': 3.861e-7,
            'acres': 0.000247105,
            'hectares': 0.0001
        };

        return areaInMeters * (conversions[units] || conversions['kilometers']);
    },

    /**
     * Get bounding box of a geometry
     * @param {Object} geometry - GeoJSON geometry or Leaflet layer
     * @returns {Array} [minX, minY, maxX, maxY]
     */
    getBbox: function (geometry) {
        const geojson = this._toGeoJSON(geometry);
        return turf.bbox(geojson);
    },

    /**
     * Calculate centroid of a geometry
     * @param {Object} geometry - GeoJSON geometry or Leaflet layer
     * @returns {Object} GeoJSON point at centroid
     */
    calculateCentroid: function (geometry) {
        const geojson = this._toGeoJSON(geometry);
        return turf.centroid(geojson);
    },

    /**
     * Find the nearest point from a collection of points
     * @param {Array} targetPoint - [longitude, latitude]
     * @param {Object} pointsCollection - GeoJSON FeatureCollection of points
     * @returns {Object} Nearest point feature with distance property
     */
    findNearestPoint: function (targetPoint, pointsCollection) {
        const target = turf.point(targetPoint);
        return turf.nearestPoint(target, pointsCollection);
    },

    /**
     * Measure total length of a line
     * @param {Array} lineCoords - Array of [longitude, latitude] pairs
     * @param {string} units - 'kilometers', 'miles', 'meters', etc.
     * @returns {number} Total length in specified units
     */
    measureLine: function (lineCoords, units = 'kilometers') {
        const line = turf.lineString(lineCoords);
        return turf.length(line, { units: units });
    },

    /**
     * Calculate bearing from one point to another
     * @param {Array} point1 - [longitude, latitude]
     * @param {Array} point2 - [longitude, latitude]
     * @returns {number} Bearing in degrees (0-360)
     */
    calculateBearing: function (point1, point2) {
        const from = turf.point(point1);
        const to = turf.point(point2);
        return turf.bearing(from, to);
    },

    /**
     * Get a point at a specific distance along a line
     * @param {Array} lineCoords - Array of [longitude, latitude] pairs
     * @param {number} distance - Distance along the line
     * @param {string} units - 'kilometers', 'miles', 'meters', etc.
     * @returns {Object} GeoJSON point
     */
    pointAlongLine: function (lineCoords, distance, units = 'kilometers') {
        const line = turf.lineString(lineCoords);
        return turf.along(line, distance, { units: units });
    },

    /**
     * Calculate intersection of two polygons
     * @param {Object} polygon1 - GeoJSON polygon
     * @param {Object} polygon2 - GeoJSON polygon
     * @returns {Object|null} Intersection geometry or null if no intersection
     */
    intersect: function (polygon1, polygon2) {
        const poly1 = this._toGeoJSON(polygon1);
        const poly2 = this._toGeoJSON(polygon2);
        return turf.intersect(turf.featureCollection([poly1, poly2]));
    },

    /**
     * Calculate union of two or more polygons
     * @param {Array} polygons - Array of GeoJSON polygons
     * @returns {Object} United polygon
     */
    union: function (polygons) {
        const geojsonPolygons = polygons.map(p => this._toGeoJSON(p));
        return turf.union(turf.featureCollection(geojsonPolygons));
    },

    /**
     * Simplify a geometry to reduce complexity
     * @param {Object} geometry - GeoJSON geometry
     * @param {number} tolerance - Simplification tolerance
     * @returns {Object} Simplified geometry
     */
    simplify: function (geometry, tolerance = 0.01) {
        const geojson = this._toGeoJSON(geometry);
        return turf.simplify(geojson, { tolerance: tolerance });
    },

    /**
     * Get points within a polygon from a collection
     * @param {Object} points - GeoJSON FeatureCollection of points
     * @param {Object} polygon - GeoJSON polygon
     * @returns {Object} FeatureCollection of points within the polygon
     */
    pointsWithinPolygon: function (points, polygon) {
        const poly = this._toGeoJSON(polygon);
        return turf.pointsWithinPolygon(points, poly);
    },

    /**
     * Convert a Leaflet layer to GeoJSON if needed
     * @param {Object} geometry - GeoJSON or Leaflet layer
     * @returns {Object} GeoJSON geometry
     */
    _toGeoJSON: function (geometry) {
        // If it's a Leaflet layer, convert to GeoJSON
        if (geometry && typeof geometry.toGeoJSON === 'function') {
            return geometry.toGeoJSON();
        }
        // If it's already a feature, return as-is
        if (geometry && geometry.type === 'Feature') {
            return geometry;
        }
        // If it's a raw geometry, wrap it in a feature
        if (geometry && geometry.type && geometry.coordinates) {
            return turf.feature(geometry);
        }
        return geometry;
    },

    /**
     * Convert Leaflet LatLng to Turf-compatible coordinates [lng, lat]
     * @param {Object} latLng - Leaflet LatLng object
     * @returns {Array} [longitude, latitude]
     */
    latLngToCoords: function (latLng) {
        return [latLng.lng, latLng.lat];
    },

    /**
     * Convert Turf coordinates [lng, lat] to Leaflet LatLng
     * @param {Array} coords - [longitude, latitude]
     * @returns {Object} Leaflet-compatible {lat, lng} object
     */
    coordsToLatLng: function (coords) {
        return { lat: coords[1], lng: coords[0] };
    }
};

// Make TurfUtils available globally
window.TurfUtils = TurfUtils;

console.log('✓ TurfUtils geospatial utilities loaded');
