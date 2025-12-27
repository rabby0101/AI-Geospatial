# SPARQL Query Examples for GeoAssist Knowledge Graph

This document provides example SPARQL queries to demonstrate the semantic capabilities of the Cognitive Geospatial Assistant. These queries run against the RDF knowledge graph containing Berlin geodata metadata.

## Running Queries

### Via API

```bash
curl -X POST "http://localhost:8000/api/semantic/sparql" \
  -H "Content-Type: application/json" \
  -d '{"query": "YOUR_SPARQL_QUERY_HERE"}'
```

### Via Swagger UI

1. Open http://localhost:8000/docs
2. Navigate to `/api/semantic/sparql`
3. Click "Try it out"
4. Paste query and execute

---

## 1. Basic Knowledge Graph Exploration

### List All Dataset Types

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?type (COUNT(?dataset) AS ?count)
WHERE {
    ?dataset rdf:type ?type .
    FILTER(STRSTARTS(STR(?type), "http://geoassist.ai/ontology#"))
}
GROUP BY ?type
ORDER BY DESC(?count)
```

### List All Datasets with Titles

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?dataset ?title ?type
WHERE {
    ?dataset rdf:type ?type ;
             dct:title ?title .
    FILTER(STRSTARTS(STR(?type), "http://geoassist.ai/ontology#"))
}
ORDER BY ?title
```

---

## 2. Analytical Purpose Queries

### Find Datasets for Accessibility Analysis

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?description
WHERE {
    ?dataset geo:hasAnalyticalPurpose geo:AccessibilityAnalysis ;
             dct:title ?title .
    OPTIONAL { ?dataset dct:description ?description }
}
ORDER BY ?title
```

### Find Datasets for Emergency Planning

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?table
WHERE {
    ?dataset geo:hasAnalyticalPurpose geo:EmergencyPlanning ;
             dct:title ?title .
    OPTIONAL { ?dataset geo:hasTableName ?table }
}
```

### Find Datasets Supporting Environmental Monitoring

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?type
WHERE {
    ?dataset geo:hasAnalyticalPurpose geo:EnvironmentalMonitoring ;
             dct:title ?title ;
             rdf:type ?type .
}
```

---

## 3. Spatial Capability Queries

### Find Datasets That Support Buffer Operations

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title
WHERE {
    ?dataset geo:hasSpatialCapability geo:BufferOperation ;
             dct:title ?title .
}
ORDER BY ?title
```

### Find Datasets Supporting Zonal Statistics

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?geometryType
WHERE {
    ?dataset geo:hasSpatialCapability geo:ZonalStatistics ;
             dct:title ?title .
    OPTIONAL { ?dataset geo:hasGeometryType ?geometryType }
}
```

### Find Datasets for Distance Calculations

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?table
WHERE {
    ?dataset geo:hasSpatialCapability geo:DistanceCalculation ;
             dct:title ?title .
    OPTIONAL { ?dataset geo:hasTableName ?table }
}
```

---

## 4. Domain-Specific Queries

### List All Healthcare Facility Datasets

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?table
WHERE {
    ?dataset a geo:HealthcareFacilityDataset ;
             dct:title ?title .
    OPTIONAL { ?dataset geo:hasTableName ?table }
}
```

### List All Emergency Service Datasets

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?description
WHERE {
    ?dataset a geo:EmergencyServiceDataset ;
             dct:title ?title .
    OPTIONAL { ?dataset dct:description ?description }
}
```

### List All Raster Datasets with Resolution

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?resolution ?bands
WHERE {
    { ?dataset a geo:RasterDataset }
    UNION
    { ?dataset a geo:VegetationIndexDataset }
    
    ?dataset dct:title ?title .
    OPTIONAL { ?dataset geo:hasResolution ?resolution }
    OPTIONAL { ?dataset geo:hasBandCount ?bands }
}
```

---

## 5. Provenance & Derivation Queries

### Find Derived Datasets

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?derived ?derivedTitle ?source ?sourceTitle
WHERE {
    ?derived geo:derivedFrom ?source ;
             dct:title ?derivedTitle .
    ?source dct:title ?sourceTitle .
}
```

### NDVI Change Detection Lineage

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?source
WHERE {
    geo:berlin_ndvi_change dct:title ?title ;
                           geo:derivedFrom ?source .
    ?source dct:title ?sourceTitle .
}
```

---

## 6. Multi-Criteria Dataset Discovery

### Find Datasets for Urban Heat Island Analysis

This query finds datasets that could support green roof potential analysis:

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?purpose
WHERE {
    # Find datasets with environmental or urban planning purposes
    {
        ?dataset geo:hasAnalyticalPurpose geo:EnvironmentalMonitoring ;
                 dct:title ?title .
        BIND("Environmental Monitoring" AS ?purpose)
    }
    UNION
    {
        ?dataset geo:hasAnalyticalPurpose geo:UrbanPlanning ;
                 dct:title ?title .
        BIND("Urban Planning" AS ?purpose)
    }
    UNION
    {
        ?dataset geo:hasAnalyticalPurpose geo:ChangeDetection ;
                 dct:title ?title .
        BIND("Change Detection" AS ?purpose)
    }
}
ORDER BY ?title
```

### Find Datasets Supporting Complete Spatial Analysis

Find datasets that support multiple spatial operations:

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title (COUNT(?capability) AS ?capabilityCount)
WHERE {
    ?dataset geo:hasSpatialCapability ?capability ;
             dct:title ?title .
}
GROUP BY ?dataset ?title
HAVING (COUNT(?capability) >= 2)
ORDER BY DESC(?capabilityCount)
```

---

## 7. Metadata & Structure Queries

### Get All Properties of a Specific Dataset

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>

SELECT ?property ?value
WHERE {
    geo:osm_hospitals ?property ?value .
}
```

### List All Datasets with Their CRS

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?crs
WHERE {
    ?dataset dct:title ?title ;
             geo:hasCRS ?crs .
}
GROUP BY ?crs ?dataset ?title
ORDER BY ?crs
```

### Count Datasets by Category

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?type (COUNT(?dataset) AS ?count)
WHERE {
    ?dataset rdf:type ?type .
    FILTER(STRSTARTS(STR(?type), "http://geoassist.ai/ontology#"))
    FILTER(?type != geo:GeoDataset)
    FILTER(?type != geo:VectorDataset)
    FILTER(?type != geo:RasterDataset)
}
GROUP BY ?type
ORDER BY DESC(?count)
```

---

## 8. GeoQA Research Queries

### Find Datasets That Can Answer "What is near hospitals?"

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?dataset ?title ?capability
WHERE {
    # Find the hospital dataset
    geo:osm_hospitals a geo:HealthcareFacilityDataset .
    
    # Find datasets with distance calculation capability
    ?dataset geo:hasSpatialCapability geo:DistanceCalculation ;
             dct:title ?title .
    
    # Get all their capabilities
    ?dataset geo:hasSpatialCapability ?capability .
}
ORDER BY ?title
```

### Find Datasets for Multi-Step Workflow (Accessibility + Environmental)

```sparql
PREFIX geo: <http://geoassist.ai/ontology#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT DISTINCT ?dataset ?title ?purpose1 ?purpose2
WHERE {
    ?dataset geo:hasAnalyticalPurpose geo:AccessibilityAnalysis ;
             geo:hasAnalyticalPurpose ?purpose2 ;
             dct:title ?title .
    FILTER(?purpose2 != geo:AccessibilityAnalysis)
    BIND(geo:AccessibilityAnalysis AS ?purpose1)
}
```

---

## Quick Reference

| Prefix | Namespace |
|--------|-----------|
| `geo:` | `http://geoassist.ai/ontology#` |
| `dct:` | `http://purl.org/dc/terms/` |
| `rdf:` | `http://www.w3.org/1999/02/22-rdf-syntax-ns#` |
| `rdfs:` | `http://www.w3.org/2000/01/rdf-schema#` |

### Main Classes

- `geo:HealthcareFacilityDataset`
- `geo:RecreationFacilityDataset`
- `geo:InfrastructureDataset`
- `geo:TransportDataset`
- `geo:EmergencyServiceDataset`
- `geo:EnvironmentalDataset`
- `geo:VegetationIndexDataset`
- `geo:AdministrativeDataset`

### Analytical Purposes

- `geo:AccessibilityAnalysis`
- `geo:EmergencyPlanning`
- `geo:UrbanPlanning`
- `geo:EnvironmentalMonitoring`
- `geo:ChangeDetection`
- `geo:ProximityAnalysis`
- `geo:CoverageAnalysis`

### Spatial Capabilities

- `geo:BufferOperation`
- `geo:SpatialJoinOperation`
- `geo:IntersectionOperation`
- `geo:DistanceCalculation`
- `geo:ZonalStatistics`
