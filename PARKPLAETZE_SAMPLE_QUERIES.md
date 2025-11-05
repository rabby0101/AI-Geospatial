# Berlin Parking Locations (Parkplätze) - Sample Queries

Berlin's comprehensive parking dataset with 45,917 parking locations and detailed information
- **Table**: `vector.parkplaetze`
- **Features**: 45,917 parking locations
- **Provider**: Berlin GDI (Geospatial Data Infrastructure)
- **Data Type**: POLYGON geometry (parking area boundaries)

## Key Columns

- `bezirk`: District name (e.g., "Mitte", "Charlottenburg-Wilmersdorf")
- `parkgebuehr`: Parking fee information (paid/free)
- `hoechstparkdauer`: Maximum parking duration
- `beschraenkung`: Parking restrictions
- `carsharing`: Carsharing zone indicator
- `ladesaeule`: EV charging station indicator
- `zone`: Parking zone designation
- `strassenname`: Street name
- `bewirtschaftungszeit`: Management/operation hours
- `nur_schwerbehinderte`: Disabled parking only
- `geometry`: POLYGON parking area boundaries

## Sample Queries

### Query 1: Free parking zones
```
"Show me free parking zones in Mitte"
```
**Expected**: Returns parking areas without fees in Mitte district

### Query 2: Carsharing parking zones
```
"Where are carsharing parking zones in Berlin?"
```
**Expected**: Returns parking areas designated for carsharing services

### Query 3: Parking with EV charging
```
"Find parking locations with EV charging stations"
```
**Expected**: Returns parking areas with electric vehicle charging capability

### Query 4: Maximum parking duration
```
"Show me parking zones with 2-hour maximum duration in Charlottenburg-Wilmersdorf"
```
**Expected**: Returns parking areas with 2-hour parking limit in the district

### Query 5: Disabled parking spots
```
"Where are disabled parking only zones?"
```
**Expected**: Returns parking areas restricted to disabled users

### Query 6: Parking by district
```
"How many parking areas are in Kreuzberg?"
```
**Expected**: Returns count of parking locations in Kreuzberg

### Query 7: Restricted parking zones
```
"Show parking areas with restrictions in Friedrichshain"
```
**Expected**: Returns parking with special restrictions in the district

### Query 8: Parking near landmarks
```
"Find parking near Brandenburger Tor"
```
**Expected**: Returns parking zones within proximity to Brandenburg Gate

### Query 9: All paid parking
```
"List all paid parking zones in Berlin"
```
**Expected**: Returns all parking areas with parking fees

### Query 10: Parking zone analysis
```
"Which district has the most parking zones?"
```
**Expected**: Returns district with highest parking location count

## Query Testing Tips

1. **District names**: "Mitte", "Charlottenburg-Wilmersdorf", "Kreuzberg", "Friedrichshain", "Prenzlauer Berg", "Tempelhof-Schöneberg", etc.
2. **Fee keywords**: "free", "paid", "gebühren", "kostenpflichtig", "gebührenfrei"
3. **Duration keywords**: "2-hour", "3-hour", "maximum duration", "limit"
4. **Special features**: "charging", "EV", "carsharing", "disabled", "schwerbehinderte"
5. **Zone keywords**: "zone", "restricted", "limitation"
6. **Spatial relationships**: "near", "in", "within", "close to"

## Testing via API

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Show me free parking zones in Mitte"}'
```

## Data Notes

- All locations use EPSG:4326 (geographic coordinates)
- Parking areas are represented as POLYGON geometries (boundaries)
- Data includes detailed street-level parking information
- Covers all 12 Berlin districts (Bezirke)
- Regularly updated by Berlin's GDI service
- Includes both street parking and parking lot information
- EV charging and carsharing data integrated where applicable

## Key Statistics

- **Total Parking Locations**: 45,917
- **Total Columns**: 26 detailed attributes
- **Coverage**: All 12 Berlin districts
- **Geometry Type**: POLYGON (parking area boundaries)
- **Coordinate System**: EPSG:4326 (WGS84)

## Column Reference

| Column Name | Description |
|---|---|
| `geometry` | POLYGON boundaries of parking area |
| `bezirk` | District name |
| `parkgebuehr` | Parking fee status |
| `hoechstparkdauer` | Max parking duration |
| `beschraenkung` | Parking restrictions |
| `carsharing` | Carsharing zone? |
| `ladesaeule` | EV charging available? |
| `zone` | Parking zone designation |
| `strassenname` | Street location |
| `bewirtschaftungszeit` | Operating hours |
| `nur_schwerbehinderte` | Disabled only? |
| `geltungszeit_der_beschraenkung` | When restrictions apply |
| `geltungszeit_der_hoechstparkdauer` | When duration limit applies |
| `errechnete_anzahl_parkplaetze` | Estimated number of spaces |
| `markierung_parkraum` | Parking area marking type |
| `ausrichtung` | Orientation |
| `planungsraum` | Planning area |
| `bezirksregion` | District region |
| `prognoseraum` | Forecast area |
