# Micro-Mobility Parking Data (Abstellflächen) - Sample Queries

Berlin's micro-mobility parking and drop-off zones for sharing services (e-scooters, bikes, etc.)
- **Table**: `vector.abstell_mikromob`
- **Features**: 505 parking/drop-off locations
- **Provider**: Berlin GDI (Geospatial Data Infrastructure)
- **Data Type**: POINT geometry (drop-off coordinates)

## Columns
- `gisid`: Unique identifier
- `typ`: Type of parking (e.g., "Jelbi-Punkt")
- `beschreibung`: Description (JELBI, etc.)
- `name`: Location name
- `gem`: Municipal ID
- `namgem`: District name
- `geometry`: POINT location

## Sample Queries

### Query 1: Find micro-mobility parking near a landmark
```
"Show me micro-mobility parking zones near Alexanderplatz"
```
**Expected**: Returns JELBI parking points near S+U Alexanderplatz

### Query 2: Parking zones by district
```
"How many micro-mobility parking zones are in Mitte?"
```
**Expected**: Count of parking locations in Mitte district

### Query 3: All parking locations
```
"List all e-scooter parking locations in Berlin"
```
**Expected**: Returns all 505 micro-mobility parking points

### Query 4: Parking near public transport
```
"Find micro-mobility parking zones near train stations"
```
**Expected**: Parking locations near osm_transport_stops

### Query 5: Parking in multiple districts
```
"Show bike-sharing parking zones in Charlottenburg-Wilmersdorf and Schöneberg"
```
**Expected**: Parking locations in both districts

## Query Testing Tips

1. Use keywords: "micro-mobility", "e-scooter", "bike-sharing", "parking", "drop", "Jelbi"
2. Combine with district names: "Mitte", "Charlottenburg-Wilmersdorf", "Kreuzberg", etc.
3. Try spatial relationships: "near", "in", "within"
4. Ask for counts: "How many...", "Show all..."

## Testing via API

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Show micro-mobility parking zones near Alexanderplatz"}'
```

## Data Notes

- All locations use EPSG:4326 (geographic coordinates)
- Most locations are "Jelbi-Punkt" (Berlin's unified mobility platform)
- Parking zones are drop-off/parking points for rental vehicles
- Data is regularly updated by Berlin's GDI service
