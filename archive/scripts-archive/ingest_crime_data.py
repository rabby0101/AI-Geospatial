import pandas as pd
import sqlalchemy
from sqlalchemy import text
import os
import re

# Database connection details
DB_URL = "postgresql://geoassist:geoassist_password@localhost:5433/geoassist"
EXCEL_PATH = "/Users/skfazlarabby/Documents/GitHub/AI-Geospatial/Fallzahlen&HZ 2015-2024.xlsx"
TABLE_NAME = "berlin_crime_stats"
SCHEMA_NAME = "vector"

COLUMN_MAPPING = {
    'LOR-Schlüssel (Bezirksregion)': 'lor_code',
    'Bezeichnung (Bezirksregion)': 'lor_name',
    'Straftaten \n-insgesamt-': 'total_crimes',
    'Raub': 'robbery',
    'Straßenraub,\nHandtaschen-raub': 'street_robbery',
    'Körper-verletzungen \n-insgesamt-': 'assault_total',
    'Gefährl. und schwere Körper-verletzung': 'aggravated_assault',
    'Freiheits-beraubung, Nötigung,\nBedrohung, Nachstellung': 'threat_coercion',
    'Diebstahl \n-insgesamt-': 'theft_total',
    'Diebstahl von Kraftwagen': 'car_theft',
    'Diebstahl \nan/aus Kfz': 'theft_from_car',
    'Fahrrad-\ndiebstahl': 'bicycle_theft',
    'Wohnraum-\neinbruch': 'burglary',
    'Branddelikte \n-insgesamt-': 'arson_total',
    'Brand-\nstiftung': 'arson',
    'Sach-beschädigung -insgesamt-': 'vandalism_total',
    'Sach-beschädigung durch Graffiti': 'graffiti',
    'Rauschgift-delikte': 'drug_offenses',
    'Kieztaten': 'kieztaten'
}

def clean_column_name(col):
    if col in COLUMN_MAPPING:
        return COLUMN_MAPPING[col]
    # Fallback cleaning
    col = col.replace('\n', ' ').replace('-', '_').strip()
    col = re.sub(r'[^a-zA-Z0-9_]', '_', col).lower()
    return col

def ingest_data():
    engine = sqlalchemy.create_engine(DB_URL)
    
    all_data = []
    
    xl = pd.ExcelFile(EXCEL_PATH)
    fallzahlen_sheets = [s for s in xl.sheet_names if s.startswith('Fallzahlen_')]
    
    print(f"📂 Found {len(fallzahlen_sheets)} years of data to process...")
    
    for sheet in fallzahlen_sheets:
        year = sheet.split('_')[1]
        print(f"📊 Processing {year}...")
        
        # Load the sheet, searching for the header row
        df_raw = pd.read_excel(EXCEL_PATH, sheet_name=sheet, header=None)
        
        # Find row index with 'LOR-Schlüssel'
        header_idx = -1
        for i, row in df_raw.iterrows():
            if 'LOR-Schlüssel' in str(row.values):
                header_idx = i
                break
        
        if header_idx == -1:
            print(f"⚠️ Could not find header in {sheet}, skipping.")
            continue
            
        df = pd.read_excel(EXCEL_PATH, sheet_name=sheet, header=header_idx)
        
        # Clean columns
        df.columns = [clean_column_name(c) for c in df.columns]
        
        # Keep only mapped columns + some safety
        valid_cols = list(COLUMN_MAPPING.values())
        existing_cols = [c for c in valid_cols if c in df.columns]
        df = df[existing_cols]
        
        # Add year
        df['year'] = int(year)
        
        # Filter out invalid LOR codes (totals, text, etc)
        # Valid LOR codes are 6-digit integers or strings looking like integers
        df = df[df['lor_code'].notna()]
        
        def is_valid_lor(val):
            try:
                s = str(int(float(val)))
                return len(s) == 5 or len(s) == 6 or len(s) == 8 # Some codes might be shorter/longer but we want granular ones
            except:
                return False
                
        df = df[df['lor_code'].apply(is_valid_lor)]
        
        # Convert lor_code to standard 6-digit string with leading zero if needed
        def format_lor(val):
            try:
                s = str(int(float(val)))
                return s.zfill(6)
            except:
                return val
                
        df['lor_code'] = df['lor_code'].apply(format_lor)
        
        # Drop rows where lor_name contains "Bezirk" or "Gesamt" (totals)
        df = df[~df['lor_name'].str.contains('Bezirk|Gesamt|nicht zuzuordnen', na=False, case=False)]
        
        all_data.append(df)
        
    if not all_data:
        print("❌ No data processed!")
        return
        
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Final cleanup: ensure numeric columns are numeric
    numeric_cols = [c for c in COLUMN_MAPPING.values() if c not in ['lor_code', 'lor_name']]
    for col in numeric_cols:
        if col in final_df.columns:
            final_df[col] = pd.to_numeric(final_df[col], errors='coerce').fillna(0).astype(int)
            
    print(f"✅ Processed {len(final_df)} rows in total.")
    
    # Upload to database
    print(f"🚀 Uploading to {SCHEMA_NAME}.{TABLE_NAME}...")
    final_df.to_sql(TABLE_NAME, engine, schema=SCHEMA_NAME, if_exists='replace', index=False)
    
    # Add index and metadata
    with engine.connect() as conn:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_crime_stats_lor ON {SCHEMA_NAME}.{TABLE_NAME} (lor_code);"))
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_crime_stats_year ON {SCHEMA_NAME}.{TABLE_NAME} (year);"))
        conn.commit()
        
    print("✨ Ingestion complete!")

if __name__ == "__main__":
    ingest_data()
