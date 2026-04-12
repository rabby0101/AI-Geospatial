# Schema

### hospitals
- id: integer(auto) (pk)
- name: varchar
- city: varchar
- geom: geometry(point

### flood_zones
- id: integer(auto) (pk)
- zone_name: varchar
- risk_level: varchar
- city: varchar
- geom: geometry(polygon

### urban_areas
- id: integer(auto) (pk)
- area_name: varchar
- city: varchar
- population: integer
- geom: geometry(polygon
