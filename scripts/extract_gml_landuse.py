#!/usr/bin/env python3
"""
Extract land use attributes from ALKIS ELU GML file.

This script parses the GML XML structure to extract:
- hilucsPresence: HILUCS classification
- specificLandUse: Dataset-specific land use classification
- specificPresence: Specific land use presence data

Then updates the PostGIS table with these attributes.
"""

import os
import sys
import logging
from pathlib import Path
from lxml import etree
import pandas as pd
from sqlalchemy import create_engine, text

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
GML_FILE = Path(__file__).parent.parent / "data/ELU_ALKIS/ELU_ALKIS_2025_04_06.gml"
DB_USER = os.getenv("POSTGRES_USER", "geoassist")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "geoassist_password")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5433")
DB_NAME = os.getenv("POSTGRES_DB", "geoassist")

# XML Namespaces
NAMESPACES = {
    'gml': 'http://www.opengis.net/gml/3.2',
    'elu': 'http://inspire.ec.europa.eu/schemas/elu/4.0',
    'lunom': 'http://inspire.ec.europa.eu/schemas/lunom/4.0',
    'base': 'http://inspire.ec.europa.eu/schemas/base/3.3',
    'xlink': 'http://www.w3.org/1999/xlink'
}


def parse_gml_landuse_attributes(gml_file):
    """Parse GML file and extract land use attributes."""
    logger.info(f"Parsing GML file: {gml_file}")

    landuse_data = {}

    try:
        # Parse the GML file
        tree = etree.parse(str(gml_file))
        root = tree.getroot()

        logger.info("Extracted XML structure")

        # Find all ExistingLandUseObject elements
        objects = root.findall('.//elu:ExistingLandUseObject', NAMESPACES)
        logger.info(f"Found {len(objects)} ExistingLandUseObject elements")

        for i, obj in enumerate(objects):
            if i % 10000 == 0:
                logger.info(f"Processing feature {i}...")

            # Extract GML ID
            gml_id = obj.get('{http://www.opengis.net/gml/3.2}id')

            if not gml_id:
                continue

            # Extract hilucsPresence
            hilucs_elem = obj.find('.//elu:hilucsPresence', NAMESPACES)
            hilucs_value = None
            if hilucs_elem is not None:
                # Try to get the text or reference
                hilucs_presence = hilucs_elem.find('.//lunom:HILUCSPresence', NAMESPACES)
                if hilucs_presence is not None:
                    # Get HILUCS code (might be in attributes or nested elements)
                    hilucs_value = hilucs_presence.text or hilucs_presence.get('href')
                    if hilucs_value and '#' in hilucs_value:
                        hilucs_value = hilucs_value.split('#')[-1]

            # Extract specificPresence
            specific_presence_elem = obj.find('.//elu:specificPresence', NAMESPACES)
            specific_presence_value = None
            if specific_presence_elem is not None:
                spec_presence = specific_presence_elem.find('.//lunom:SpecificPresence', NAMESPACES)
                if spec_presence is not None:
                    specific_presence_value = spec_presence.text or spec_presence.get('href')
                    if specific_presence_value and '#' in specific_presence_value:
                        specific_presence_value = specific_presence_value.split('#')[-1]

            # Extract specificLandUse references
            spec_landuse_elems = obj.findall('.//elu:specificLandUse', NAMESPACES)
            specific_landuse_values = []
            for elem in spec_landuse_elems:
                ref = elem.get('{http://www.w3.org/1999/xlink}href')
                if ref:
                    if '#' in ref:
                        ref = ref.split('#')[-1]
                    specific_landuse_values.append(ref)

            # Store the extracted data
            landuse_data[gml_id] = {
                'hilucspresence': hilucs_value,
                'specificpresence': specific_presence_value,
                'specificlanduse': '|'.join(specific_landuse_values) if specific_landuse_values else None
            }

        logger.info(f"✓ Extracted land use data for {len(landuse_data)} features")
        return landuse_data

    except Exception as e:
        logger.error(f"Error parsing GML: {e}", exc_info=True)
        raise


def update_postgis_with_landuse(landuse_data):
    """Update PostGIS table with extracted land use attributes."""
    logger.info("Updating PostGIS with land use data...")

    connection_string = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(connection_string)

    updated_count = 0

    try:
        with engine.connect() as conn:
            # Check if columns exist, if not create them
            logger.info("Checking table structure...")

            for col in ['hilucspresence', 'specificpresence', 'specificlanduse']:
                try:
                    # Try adding column if it doesn't exist
                    conn.execute(text(f"""
                        ALTER TABLE vector.osm_landuse
                        ADD COLUMN {col} VARCHAR(255)
                    """))
                    logger.info(f"  Created column: {col}")
                except:
                    logger.info(f"  Column {col} already exists")

            conn.commit()

            # Update records in batches
            batch_size = 1000
            batch = []

            for gml_id, data in landuse_data.items():
                batch.append((
                    gml_id,
                    data['hilucspresence'],
                    data['specificpresence'],
                    data['specificlanduse']
                ))

                if len(batch) >= batch_size:
                    # Execute batch update
                    for gml_id, hilucs, specific_p, specific_l in batch:
                        try:
                            conn.execute(text("""
                                UPDATE vector.osm_landuse
                                SET
                                    hilucspresence = :hilucs,
                                    specificpresence = :spec_p,
                                    specificlanduse = :spec_l
                                WHERE gml_id = :gml_id
                            """), {
                                'gml_id': gml_id,
                                'hilucs': hilucs,
                                'spec_p': specific_p,
                                'spec_l': specific_l
                            })
                            updated_count += 1
                        except Exception as e:
                            logger.debug(f"Error updating {gml_id}: {e}")

                    conn.commit()
                    batch = []
                    logger.info(f"  Updated {updated_count} records...")

            # Final batch
            for gml_id, hilucs, specific_p, specific_l in batch:
                try:
                    conn.execute(text("""
                        UPDATE vector.osm_landuse
                        SET
                            hilucspresence = :hilucs,
                            specificpresence = :spec_p,
                            specificlanduse = :spec_l
                        WHERE gml_id = :gml_id
                    """), {
                        'gml_id': gml_id,
                        'hilucs': hilucs,
                        'spec_p': specific_p,
                        'spec_l': specific_l
                    })
                    updated_count += 1
                except Exception as e:
                    logger.debug(f"Error updating {gml_id}: {e}")

            conn.commit()

        logger.info(f"✓ Updated {updated_count} records with land use attributes")
        return updated_count

    except Exception as e:
        logger.error(f"Error updating PostGIS: {e}", exc_info=True)
        raise


def verify_updates():
    """Verify that land use data was properly imported."""
    logger.info("Verifying land use data...")

    connection_string = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(connection_string)

    with engine.connect() as conn:
        # Check non-null counts
        result = conn.execute(text("""
            SELECT
                COUNT(CASE WHEN hilucspresence IS NOT NULL THEN 1 END) as hilucs_count,
                COUNT(CASE WHEN specificpresence IS NOT NULL THEN 1 END) as spec_pres_count,
                COUNT(CASE WHEN specificlanduse IS NOT NULL THEN 1 END) as spec_land_count,
                COUNT(DISTINCT hilucspresence) as hilucs_unique
            FROM vector.osm_landuse
        """)).first()

        if result:
            hilucs_count, spec_pres_count, spec_land_count, hilucs_unique = result
            logger.info(f"✓ Verification Results:")
            logger.info(f"  HILUCS Presence (non-null): {hilucs_count:,}")
            logger.info(f"  Specific Presence (non-null): {spec_pres_count:,}")
            logger.info(f"  Specific Land Use (non-null): {spec_land_count:,}")
            logger.info(f"  Unique HILUCS values: {hilucs_unique}")


def main():
    """Main workflow."""
    try:
        logger.info("=" * 70)
        logger.info("ALKIS Land Use Attribute Extraction")
        logger.info("=" * 70)

        # Parse GML
        landuse_data = parse_gml_landuse_attributes(GML_FILE)

        # Update PostGIS
        update_postgis_with_landuse(landuse_data)

        # Verify
        verify_updates()

        logger.info("=" * 70)
        logger.info("✓ Land use attribute extraction completed!")
        logger.info("=" * 70)

        return 0

    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
