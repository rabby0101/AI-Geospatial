"""
Automatic Table Discovery and Description Generation

Automatically discovers new tables added to the database and generates
descriptions using the LLM (DeepSeek).
"""

from typing import Dict, List, Any, Tuple
from app.utils.database import db_manager
from app.utils.schema_discovery import schema_discovery
import json
from pathlib import Path
import re


class AutoTableDiscovery:
    """Automatically discover new tables and generate descriptions"""

    DESCRIPTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "metadata" / "table_descriptions.json"

    @staticmethod
    def get_new_tables() -> List[str]:
        """
        Find tables in database that don't have descriptions yet.
        
        Returns:
            List of table names without descriptions
        """
        try:
            # Get all tables from database
            all_tables = db_manager.get_available_tables(schema="vector")
            
            # Get existing descriptions
            existing_descriptions = schema_discovery.get_all_descriptions()
            
            # Find new tables (in database but not in descriptions)
            new_tables = [t for t in all_tables if t not in existing_descriptions]
            
            return new_tables
        except Exception as e:
            print(f"Error getting new tables: {e}")
            return []

    @staticmethod
    def get_table_structure(table_name: str) -> Dict[str, Any]:
        """
        Get table structure information for description generation.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with table structure info
        """
        try:
            info = db_manager.get_table_info(table_name, schema="vector")
            return {
                "table_name": table_name,
                "row_count": info.get("row_count", 0),
                "geometry_type": info.get("geometry_type", "UNKNOWN"),
                "columns": [col["name"] for col in info.get("columns", [])],
                "column_types": {col["name"]: col["type"] for col in info.get("columns", [])}
            }
        except Exception as e:
            print(f"Error getting table structure for {table_name}: {e}")
            return {}

    @staticmethod
    def generate_description_from_structure(table_name: str, structure: Dict[str, Any]) -> str:
        """
        Generate a description based on table structure.
        This is a smart fallback that doesn't require the LLM.
        
        Args:
            table_name: Name of the table
            structure: Table structure information
            
        Returns:
            Generated description string
        """
        # Parse the table name for keywords
        # osm_hospitals → Hospital locations
        # berlin_districts → Berlin district boundaries
        # vegetation_ndvi → Vegetation index data
        
        name = table_name.replace("osm_", "").replace("berlin_", "").replace("_", " ")
        name = name.title()
        
        geom_type = structure.get("geometry_type", "UNKNOWN")
        row_count = structure.get("row_count", 0)
        columns = structure.get("columns", [])
        
        # Smart description based on geometry type and column names
        if geom_type == "POINT":
            desc = f"{name} point locations"
        elif geom_type in ["POLYGON", "MULTIPOLYGON"]:
            desc = f"{name} area boundaries"
        elif geom_type in ["LINESTRING", "MULTILINESTRING"]:
            desc = f"{name} linear features"
        else:
            desc = f"{name} geospatial data"
        
        # Add row count info
        if row_count > 0:
            desc += f" ({row_count:,} features)"
        
        return desc

    @staticmethod
    def generate_description_with_llm(table_name: str, structure: Dict[str, Any]) -> str:
        """
        Generate a description using DeepSeek LLM.
        Analyzes table structure to create intelligent descriptions.
        
        Args:
            table_name: Name of the table
            structure: Table structure information
            
        Returns:
            LLM-generated description string
        """
        try:
            import requests
            import os
            from dotenv import load_dotenv
            
            load_dotenv()
            DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
            DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
            
            if not DEEPSEEK_API_KEY:
                print("Warning: DEEPSEEK_API_KEY not found, using structural generation")
                return AutoTableDiscovery.generate_description_from_structure(table_name, structure)
            
            # Build prompt for description generation
            columns = structure.get("columns", [])
            geom_type = structure.get("geometry_type", "UNKNOWN")
            row_count = structure.get("row_count", 0)
            
            prompt = f"""Analyze this database table and generate a SHORT (1-2 sentences), 
human-readable description for a geospatial data system:

Table name: {table_name}
Geometry type: {geom_type}
Row count: {row_count:,}
Sample columns: {', '.join(columns[:10])}

Generate a concise description (max 150 chars) that describes what this table contains.
Do NOT include the row count in the description.
Do NOT say 'table' or 'data' - be specific about the content.
Example: "Medical facilities providing hospital services and emergency care"

Description:"""

            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3,  # Low temperature for consistent descriptions
                "max_tokens": 100
            }
            
            response = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=15
            )
            
            if response.status_code == 200:
                result = response.json()
                description = result["choices"][0]["message"]["content"].strip()
                # Clean up the description (remove quotes if LLM added them)
                description = description.strip('"\'')
                return description
            else:
                print(f"Warning: LLM request failed ({response.status_code}), using structural generation")
                return AutoTableDiscovery.generate_description_from_structure(table_name, structure)
                
        except Exception as e:
            print(f"Warning: LLM description generation failed: {e}, using structural generation")
            return AutoTableDiscovery.generate_description_from_structure(table_name, structure)

    @staticmethod
    def auto_discover_and_update() -> Dict[str, Any]:
        """
        Automatically discover new tables and update descriptions.json.
        
        Returns:
            Dictionary with discovery results
        """
        print("\n" + "=" * 70)
        print("AUTO TABLE DISCOVERY - Searching for new tables...")
        print("=" * 70)
        
        # Get new tables
        new_tables = AutoTableDiscovery.get_new_tables()
        
        if not new_tables:
            print("✅ No new tables found. System is up to date!")
            return {
                "status": "success",
                "new_tables_found": 0,
                "tables_added": [],
                "message": "No new tables to discover"
            }
        
        print(f"\n🔍 Found {len(new_tables)} new table(s):")
        for table in new_tables:
            print(f"  - {table}")
        
        # Load existing descriptions
        try:
            with open(AutoTableDiscovery.DESCRIPTIONS_FILE, 'r') as f:
                descriptions = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load existing descriptions: {e}")
            descriptions = {}
        
        # Generate descriptions for new tables
        added_tables = []
        for table_name in new_tables:
            print(f"\n📊 Processing: {table_name}")
            
            # Get table structure
            structure = AutoTableDiscovery.get_table_structure(table_name)
            
            if not structure:
                print(f"  ⚠️  Could not get table structure, skipping")
                continue
            
            # Generate description using LLM
            print(f"  🧠 Generating description with AI...")
            description = AutoTableDiscovery.generate_description_with_llm(table_name, structure)
            
            # Add to descriptions
            descriptions[table_name] = description
            added_tables.append({
                "table_name": table_name,
                "description": description,
                "row_count": structure.get("row_count"),
                "geometry_type": structure.get("geometry_type")
            })
            
            print(f"  ✅ Description: {description}")
        
        # Save updated descriptions
        if added_tables:
            try:
                # Sort descriptions by key for consistency
                descriptions = dict(sorted(descriptions.items()))
                
                with open(AutoTableDiscovery.DESCRIPTIONS_FILE, 'w') as f:
                    json.dump(descriptions, f, indent=2)
                
                print(f"\n✅ Updated {AutoTableDiscovery.DESCRIPTIONS_FILE}")
                
                # Refresh schema discovery cache
                schema_discovery.refresh_cache()
                print("✅ Schema cache refreshed")
                
                return {
                    "status": "success",
                    "new_tables_found": len(new_tables),
                    "tables_added": added_tables,
                    "message": f"Successfully discovered and added descriptions for {len(added_tables)} table(s)"
                }
            except Exception as e:
                print(f"❌ Error saving descriptions: {e}")
                return {
                    "status": "error",
                    "message": f"Failed to save descriptions: {e}",
                    "tables_found": len(new_tables)
                }
        else:
            return {
                "status": "success",
                "new_tables_found": len(new_tables),
                "tables_added": [],
                "message": "Found new tables but could not generate descriptions"
            }


# Global instance
auto_discovery = AutoTableDiscovery()
