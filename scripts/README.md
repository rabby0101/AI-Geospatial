# Scripts Directory

This directory contains utility scripts for managing geospatial data in the Cognitive Geospatial Assistant API project.

## 📜 Available Scripts

### 1. `download_berlin_osm.py`
**Purpose:** Download OpenStreetMap data for Berlin from Overpass API

**What it downloads:**
- Hospitals (59)
- Public Toilets (1,160)
- Pharmacies (768)
- Fire Stations (179)
- Police Stations (81)
- Parks (2,785)
- Schools (1,195)
- Restaurants (5,013)
- Transport Stops (14,899)

**Usage:**
```bash
cd /Users/skfazlarabby/projects/AI\ Geospatial
python scripts/download_berlin_osm.py
```

**Output:** GeoJSON files in `data/vector/osm/`

**Notes:**
- Respects Overpass API rate limits
- Shows progress and statistics
- Handles errors gracefully

---

### 2. `verify_berlin_data.py`
**Purpose:** Verify loaded data and run spatial query tests

**What it does:**
- Counts all loaded datasets
- Runs 6 different spatial queries
- Verifies spatial coverage
- Tests database connectivity

**Usage:**
```bash
python scripts/verify_berlin_data.py
```

**Sample Output:**
```
📊 Dataset Summary
  osm_hospitals            :      59 features
  osm_toilets              :   1,160 features
  osm_pharmacies           :     768 features
  ...

🚏 Test Query 1: Public toilets near transport stops (within 100m)
  Found 10 toilets near transport stops:
    • rail&fresh near Berlin Hauptbahnhof (Tief) (4.5m)
    ...
```

---

## 🔄 Typical Workflow

### Initial Setup
```bash
# 1. Download OSM data
python scripts/download_berlin_osm.py

# 2. Load into PostGIS
python load_data_to_postgis.py

# 3. Verify everything works
python scripts/verify_berlin_data.py
```

### Update Data (Monthly)
```bash
# Re-download and reload
python scripts/download_berlin_osm.py
python load_data_to_postgis.py
```

---

## 🛠️ Requirements

All scripts require:
- Python 3.11+
- Dependencies from `requirements.txt`
- Running PostGIS database (Docker container)

---

## 📊 Data Statistics

After running both scripts, you will have:
- **26,139 features** in PostGIS
- **9 GeoJSON files** (~50 MB total)
- **9 PostGIS tables** with spatial indexes
- **Verified spatial queries** with sample results

---

## 🔗 Related Files

- **Configuration:** `config/settings.yaml`
- **Database Loader:** `load_data_to_postgis.py`
- **OSM Loader Module:** `app/utils/data_loaders/osm_loader.py`
- **Data Catalog:** `data/metadata/berlin_osm_catalog.json`
- **Summary Report:** `BERLIN_OSM_INTEGRATION_SUMMARY.md`

---

## 💡 Tips

1. **Rate Limiting:** If download fails, wait a few minutes and retry
2. **Large Downloads:** Restaurants and transport stops take longer
3. **Database:** Ensure PostGIS is running before loading data
4. **Verification:** Always run verify script after loading data
5. **Logs:** Check terminal output for detailed progress

---

## 🐛 Troubleshooting

### Download fails with "429 Too Many Requests"
**Solution:** Wait 5-10 minutes, then retry. Overpass API has rate limits.

### Database connection error
**Solution:** Check Docker container is running:
```bash
docker ps | grep postgis
```

### Missing dependencies
**Solution:** Install requirements:
```bash
pip install -r requirements.txt
```

---

## 📚 Documentation

For complete documentation, see:
- [BERLIN_OSM_INTEGRATION_SUMMARY.md](../BERLIN_OSM_INTEGRATION_SUMMARY.md)
- [CLAUDE.md](../CLAUDE.md)
- [Data Catalog](../data/metadata/berlin_osm_catalog.json)

---

**Maintained by:** Sk Fazla Rabby
**Last Updated:** October 19, 2025
