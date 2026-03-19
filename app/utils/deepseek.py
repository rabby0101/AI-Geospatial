import os
import json
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from app.models.query_model import OperationPlan, GeospatialOperation
from app.utils.prompts import SYSTEM_PROMPT

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Use deepseek-chat for cleaner JSON responses (faster and more reliable parsing)
# DO NOT use deepseek-reasoner as it produces verbose thinking output that breaks JSON parsing
DEEPSEEK_MODEL = "deepseek-chat"  # Force chat model for reliable JSON output
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Simple in-memory cache (max 100 entries)
_query_cache: Dict[str, str] = {}
_MAX_CACHE_SIZE = 100


# System prompt is imported from prompts.py (single source of truth)


def _get_location_filter_column(location_name: str) -> str:
    """
    Determine if a location is a main district (Bezirk) or subdivision (Ortsteil).
    Returns the appropriate column name to use in SQL WHERE clause.

    Args:
        location_name: Name of the location (e.g., 'Mitte', 'Kladow', 'Spandau')

    Returns:
        'bezirk' if it's a main district, 'name' if it's a subdivision
    """
    # Main districts (Bezirke) - 12 total
    main_districts = {
        'mitte', 'friedrichshain-kreuzberg', 'pankow', 'charlottenburg-wilmersdorf',
        'spandau', 'steglitz-zehlendorf', 'tempelhof-schöneberg', 'neukölln',
        'treptow-köpenick', 'marzahn-hellersdorf', 'lichtenberg', 'reinickendorf'
    }

    location_lower = location_name.lower().strip()
    if location_lower in main_districts:
        return 'bezirk'
    else:
        # It's likely a subdivision (Ortsteil)
        return 'name'


def _hash_selected_feature(selected_feature: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Create a hash of selected feature (excluding the large WKT geometry).
    This prevents cache keys from becoming too large.
    """
    if not selected_feature:
        return None

    import hashlib
    # Only hash the feature name and type, not the massive geometry
    feature_summary = {
        'name': selected_feature.get('name'),
        'geometry_type': selected_feature.get('geometry_type')
    }
    feature_str = json.dumps(feature_summary, sort_keys=True)
    return hashlib.md5(feature_str.encode()).hexdigest()


def _generate_cache_key(prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Generate a unique cache key for a query."""
    cache_str = prompt.lower().strip()
    if context:
        cache_str += json.dumps(context, sort_keys=True)
    return cache_str


def _get_database_schema_for_llm() -> str:
    """
    Get the LIVE database schema from PostGIS.

    Fetches descriptions, row counts, and column info directly from the database.
    Also checks for temporary layers created from selected features.

    Returns:
        Formatted string with all available tables and descriptions for LLM
    """
    try:
        from app.utils.database import db_manager
        from sqlalchemy import text

        # Fetch live schema from database (vector schema)
        tables_data = db_manager.get_schema_with_descriptions()

        if not tables_data:
            tables_data = []

        # Format for LLM
        schema_text = "**Available Tables in Database:**\n\n"

        # Add vector schema tables
        schema_text += "**SCHEMA: vector (main spatial data)**\n"
        schema_text += "-" * 60 + "\n"

        for table_info in sorted(tables_data, key=lambda x: x["table"]):
            table_name = table_info["table"]
            description = table_info["description"]
            row_count = table_info.get("row_count", 0)
            geometry = table_info.get("geometry", "NONE")
            columns = table_info.get("columns", [])

            # Format table entry
            schema_text += f"**{table_name}**\n"
            schema_text += f"  Description: {description}\n"
            schema_text += f"  Records: {row_count} | Geometry: {geometry}\n"
            schema_text += "  Columns:\n"
            
            # Format each column with its metadata
            for col in columns:
                if isinstance(col, dict):
                    col_name = col.get("name", "")
                    col_type = col.get("type", "")
                    col_desc = col.get("description", "")
                    col_examples = col.get("example_values", "")
                    
                    line = f"    - {col_name} ({col_type})"
                    if col_desc:
                        line += f": {col_desc}"
                    if col_examples:
                        line += f" e.g., {col_examples}"
                    schema_text += line + "\n"
                else:
                    # Fallback if somehow just a string
                    schema_text += f"    - {col}\n"

            schema_text += "\n"

        # Check for temporary selected feature layers
        try:
            temp_tables = []
            with db_manager.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'temp' AND table_name LIKE 'temp_selected_%'
                    ORDER BY table_name
                """))
                temp_tables = [row[0] for row in result]

            if temp_tables:
                schema_text += "\n**SCHEMA: temp (selected feature layers)**\n"
                schema_text += "-" * 60 + "\n"

                for temp_table in temp_tables:
                    # Get info about temp table using a fresh connection
                    try:
                        with db_manager.engine.connect() as conn2:
                            result = conn2.execute(text(f"""
                                SELECT COUNT(*) as count,
                                       ST_GeometryType((array_agg(geometry))[1]) as geom_type
                                FROM temp.{temp_table}
                            """))
                            row = result.first()
                            count = row[0] if row else 0
                            geom_type = row[1] if row else "Unknown"

                            schema_text += f"**{temp_table}**\n"
                            schema_text += f"  Description: Temporary layer from selected feature\n"
                            schema_text += f"  Records: {count} | Geometry: {geom_type}\n"
                            schema_text += f"  Columns: id, geometry\n\n"
                    except Exception as table_error:
                        print(f"⚠️ Could not get info for temp table {temp_table}: {table_error}")
                        # Still list the temp table even if we can't get info
                        schema_text += f"**{temp_table}**\n"
                        schema_text += f"  Description: Temporary layer from selected feature\n"
                        schema_text += f"  Columns: id, geometry\n\n"
        except Exception as e:
            print(f"⚠️ Note: Could not query temp schema: {e}")

        return schema_text

    except Exception as e:
        print(f"⚠️ Error getting database schema: {e}")
        # Fallback to static version
        return "Unable to fetch live schema from database"


def _build_dynamic_system_prompt(user_query: str) -> str:
    """
    Build a system prompt with LIVE table descriptions from the database.
    Enhanced with ontology awareness for semantic query understanding.

    Single source of truth: descriptions are stored in vector.table_metadata
    Ontology provides analytical purposes and dataset relationships.

    Args:
        user_query: The user's natural language question

    Returns:
        Complete system prompt with live database schema information
    """
    try:
        # Get the base prompt (core instructions, rules, examples)
        base_prompt = SYSTEM_PROMPT

        # Get LIVE schema from database (descriptions, row counts, columns)
        schema_section = _get_database_schema_for_llm()

        # Get ONTOLOGY context for semantic enhancement
        ontology_section = _get_ontology_context_for_llm(user_query)

        # Combine into final prompt
        final_prompt = base_prompt + "\n\n" + schema_section
        
        # Add ontology section if relevant
        if ontology_section:
            final_prompt += "\n" + ontology_section

        return final_prompt

    except Exception as e:
        print(f"⚠️ Error building dynamic prompt: {e}")
        # Gracefully fall back to static prompt on any error
        return SYSTEM_PROMPT


def _get_ontology_context_for_llm(user_query: str) -> str:
    """
    Get relevant ontology context based on user query for enhanced semantic understanding.
    
    Detects analytical intent from keywords and returns relevant dataset recommendations
    from the knowledge graph.
    
    Args:
        user_query: The user's natural language question
        
    Returns:
        Formatted ontology context string, or empty string if not relevant
    """
    try:
        from app.utils.semantic_layer import create_semantic_layer
        
        query_lower = user_query.lower()
        
        # Define keyword-to-purpose mappings for semantic enhancement
        purpose_keywords = {
            'AccessibilityAnalysis': [
                'accessibility', 'accessible', 'wheelchair', 'disability', 'disabled',
                'mobility', 'barrier-free', 'reachable', 'reach', 'access to',
                'healthcare access', 'service access', 'public transport access',
                'walking distance', 'how far', 'nearest', 'closest'
            ],
            'EmergencyPlanning': [
                'emergency', 'evacuation', 'disaster', 'fire station', 'fire fighting',
                'police', 'ambulance', 'hospital', 'emergency services', 'safety',
                'response time', 'crisis', 'rescue', 'first responder'
            ],
            'UrbanPlanning': [
                'urban planning', 'city planning', 'zoning', 'land use', 'landuse', 'development',
                'infrastructure', 'housing', 'residential', 'commercial', 'mixed use',
                'density', 'urban growth', 'smart city', 'sustainable', 'best area',
                'best district', 'ideal location', 'suitable for', 'open a', 'build a'
            ],
            'EnvironmentalMonitoring': [
                'environment', 'environmental', 'pollution', 'air quality', 'water quality',
                'vegetation', 'ndvi', 'green', 'greenery', 'trees', 'forest',
                'climate', 'carbon', 'sustainability', 'ecological', 'biodiversity',
                'nature', 'natural', 'green space', 'parks'
            ],
            'ChangeDetection': [
                'change', 'changes', 'temporal', 'time series', 'over time',
                'comparison', 'difference', 'evolution', 'growth', 'decline',
                'before and after', 'trend', 'historical'
            ],
            'ProximityAnalysis': [
                'near', 'nearby', 'close to', 'within', 'distance', 'proximity',
                'around', 'surrounding', 'neighborhood', 'radius', 'buffer',
                'walking distance', 'km from', 'meters from', 'minutes from'
            ]
        }
        
        # Detect which purposes are relevant for this query
        detected_purposes = []
        for purpose, keywords in purpose_keywords.items():
            if any(kw in query_lower for kw in keywords):
                detected_purposes.append(purpose)
        
        if not detected_purposes:
            return ""  # No semantic enhancement needed
        
        # Get the semantic layer
        semantic_layer = create_semantic_layer()
        
        # Build ontology context section
        context_lines = [
            "\n**🧠 SEMANTIC CONTEXT (from Knowledge Graph):**",
            "Based on the query intent, these datasets are semantically relevant:\n"
        ]
        
        all_relevant_datasets = set()
        
        for purpose in detected_purposes:
            datasets = semantic_layer.get_datasets_by_purpose(purpose)
            if datasets:
                # Format purpose name nicely
                purpose_name = purpose.replace('Analysis', ' Analysis').replace('Planning', ' Planning').replace('Monitoring', ' Monitoring').replace('Detection', ' Detection')
                context_lines.append(f"**For {purpose_name}:**")
                
                for ds in datasets[:5]:  # Limit to top 5 per purpose
                    title = ds.get('title', 'Unknown')
                    table = ds.get('table', '')
                    
                    # Extract table name from URI if present
                    if not table and 'dataset' in ds:
                        dataset_uri = ds.get('dataset', '')
                        if '#' in dataset_uri:
                            table = dataset_uri.split('#')[-1]
                    
                    if table:
                        # Convert ontology ID to actual table name
                        table_name = _ontology_id_to_table_name(table)
                        if table_name:
                            all_relevant_datasets.add(table_name)
                            context_lines.append(f"  - {title} → table: `vector.{table_name}`")
                        else:
                            context_lines.append(f"  - {title}")
                    else:
                        context_lines.append(f"  - {title}")
                
                context_lines.append("")
        
        # Add semantic recommendation
        if all_relevant_datasets:
            tables_list = ', '.join([f"vector.{t}" for t in sorted(all_relevant_datasets)])
            context_lines.append(f"**Recommended tables for this query:** {tables_list}")
            context_lines.append("\nConsider using these tables in your SQL query based on their semantic relevance.")
        
        return '\n'.join(context_lines)
        
    except ImportError:
        print("⚠️ Semantic layer not available for ontology context")
        return ""
    except Exception as e:
        print(f"⚠️ Error getting ontology context: {e}")
        return ""


def _ontology_id_to_table_name(ontology_id: str) -> str:
    """
    Convert an ontology dataset ID to the actual PostGIS table name.
    
    Args:
        ontology_id: The ID from the ontology (e.g., 'osm_hospitals', 'berlin_ndvi_2024')
        
    Returns:
        The actual table name without schema prefix, or empty string if unknown
    """
    # Direct mapping for known ontology IDs to table names
    # These match the instances defined in geo_ontology.ttl
    id_to_table = {
        'osm_hospitals': 'osm_hospitals',
        'osm_pharmacies': 'osm_pharmacies',
        'osm_doctors': 'osm_doctors',
        'osm_parks': 'osm_parks',
        'osm_fire_stations': 'osm_fire_stations',
        'osm_police_stations': 'osm_police_stations',
        'osm_transport_stops': 'osm_transport_stops',
        'osm_kindergartens': 'osm_kindergartens',
        'osm_forests': 'osm_forests',
        'osm_water_bodies': 'osm_water_bodies',
        'berlin_districts': 'berlin_districts',
        'berlin_ndvi_2018': None,  # Raster - no table
        'berlin_ndvi_2024': None,  # Raster - no table
        'berlin_ndvi_change': None,  # Raster - no table
    }
    
    return id_to_table.get(ontology_id, ontology_id if ontology_id.startswith('osm_') else '')


def query_deepseek(prompt: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, drawn_geometry: Dict[str, Any] = None) -> Dict[str, str]:
    """
    Query DeepSeek API with a prompt, using simple in-memory cache.
    Dynamically builds prompts with only relevant tables for the query.

    Args:
        prompt: The user's natural language query
        context: Optional context information
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster') to guide LLM response format
        selected_feature: Optional selected feature from map for context-aware queries
        drawn_geometry: Optional geometry drawn by user (GeoJSON format) - used as spatial context

    Returns:
        Dict with 'content' (API response), 'system_prompt', and 'user_prompt'
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not found in environment variables")

    # Check cache first (include user_location, query_type, drawn_geometry, and session_id in cache key)
    # session_id is included because queries depend on temp.temp_selected_{session_id} tables
    session_id = context.get("session_id") if context else None
    cache_context = {
        **(context or {}), 
        **({"user_location": user_location} if user_location else {}), 
        **({"query_type": query_type} if query_type else {}), 
        **({"drawn_geometry": drawn_geometry} if drawn_geometry else {})
    }
    cache_key = _generate_cache_key(prompt, cache_context if cache_context else None)
    if cache_key in _query_cache:
        print(f"💨 Cache hit! Returning cached response")
        return _query_cache[cache_key]  # Returns dict with content, system_prompt, user_prompt

    # Build dynamic system prompt with relevant tables
    system_prompt = _build_dynamic_system_prompt(prompt)

    # Build the full prompt with context and user_location if provided
    full_prompt = prompt

    # Add query type hint to prompt if specified
    if query_type:
        full_prompt = f"{prompt}\n\nQuery type: {query_type}"

    # Add user location to prompt if available
    if user_location:
        full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

    # Add drawn geometry to prompt if available - provides spatial context for queries
    if drawn_geometry:
        geometry_type = drawn_geometry.get('type', 'Unknown')
        coordinates_str = json.dumps(drawn_geometry.get('coordinates', []))[:200]  # Truncate long coordinate lists
        full_prompt = f"{full_prompt}\n\ndrawn_geometry: User has drawn a {geometry_type} on the map. Use this as spatial context for queries mentioning 'here', 'this area', 'drawn area', or location references. Geometry: {coordinates_str}..."

    # Add additional context if provided
    if context:
        full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

    # Note: selected_feature is now handled via temp database layers
    # The schema automatically includes temp_selected_* tables that the LLM can query

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0,  # Zero temperature for deterministic SQL generation
        "max_tokens": 1500  # Increased for complex queries (grid-based density, multi-step operations)
    }

    try:
        print(f"🧠 Querying DeepSeek API ({DEEPSEEK_MODEL})...")
        print("\n" + "="*80)
        print("📤 DEEPSEEK SYSTEM PROMPT:")
        print("="*80)
        print(system_prompt[:2000] + ("...[TRUNCATED]" if len(system_prompt) > 2000 else ""))
        print("\n" + "="*80)
        print("📤 DEEPSEEK USER PROMPT:")
        print("="*80)
        print(full_prompt)
        print("="*80 + "\n")
        response = requests.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60  # Increased for selected features with large geometries
        )
        response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Create response dict with all three components
        response_dict = {
            "content": content,
            "system_prompt": system_prompt,
            "user_prompt": full_prompt
        }

        # Cache the response (limit cache size)
        if len(_query_cache) >= _MAX_CACHE_SIZE:
            _query_cache.clear()  # Simple cache eviction
        _query_cache[cache_key] = response_dict

        print(f"✅ DeepSeek response received ({len(content)} chars)")
        return response_dict

    except requests.exceptions.Timeout:
        raise Exception("DeepSeek API timeout. Please try a simpler query.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"DeepSeek API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected response format from DeepSeek: {str(e)}")


def query_gemini(prompt: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, drawn_geometry: Dict[str, Any] = None) -> Dict[str, str]:
    """
    Query Google Gemini API with a prompt, using simple in-memory cache.
    Uses the same dynamic prompt building as DeepSeek for consistency.

    Args:
        prompt: The user's natural language query
        context: Optional context information
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster')
        selected_feature: Optional selected feature from map
        drawn_geometry: Optional geometry drawn by user (GeoJSON format)

    Returns:
        Dict with 'content' (API response), 'system_prompt', and 'user_prompt'
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not found in environment variables. Get a free key at https://aistudio.google.com/apikey")

    # Check cache first
    session_id = context.get("session_id") if context else None
    cache_context = {
        **(context or {}),
        **({  "user_location": user_location} if user_location else {}),
        **({"query_type": query_type} if query_type else {}),
        **({"drawn_geometry": drawn_geometry} if drawn_geometry else {}),
        "provider": "gemini"  # Separate cache namespace from DeepSeek
    }
    cache_key = _generate_cache_key(prompt, cache_context if cache_context else None)
    if cache_key in _query_cache:
        print(f"💨 Cache hit! Returning cached Gemini response")
        return _query_cache[cache_key]

    # Build dynamic system prompt (same as DeepSeek)
    system_prompt = _build_dynamic_system_prompt(prompt)

    # Build the full prompt with context and user_location
    full_prompt = prompt

    if query_type:
        full_prompt = f"{prompt}\n\nQuery type: {query_type}"

    if user_location:
        full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

    if drawn_geometry:
        geometry_type = drawn_geometry.get('type', 'Unknown')
        coordinates_str = json.dumps(drawn_geometry.get('coordinates', []))[:200]
        full_prompt = f"{full_prompt}\n\ndrawn_geometry: User has drawn a {geometry_type} on the map. Use this as spatial context for queries mentioning 'here', 'this area', 'drawn area', or location references. Geometry: {coordinates_str}..."

    if context:
        full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

    # Gemini API payload format
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": full_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 65536,
            "thinkingConfig": {
                "thinkingBudget": 2048
            }
        }
    }

    try:
        print(f"✨ Querying Gemini API ({GEMINI_MODEL})...")
        print("\n" + "="*80)
        print("📤 GEMINI SYSTEM PROMPT:")
        print("="*80)
        print(system_prompt[:2000] + ("...[TRUNCATED]" if len(system_prompt) > 2000 else ""))
        print("\n" + "="*80)
        print("📤 GEMINI USER PROMPT:")
        print("="*80)
        print(full_prompt)
        print("="*80 + "\n")

        response = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        response.raise_for_status()

        result = response.json()

        # Gemini 2.5 Flash returns multiple parts: a "thought" part (reasoning) + the actual text
        # We need to find the actual text part, not the thinking
        parts = result["candidates"][0]["content"]["parts"]
        content = None
        for part in reversed(parts):  # Last text part is the actual response
            if "text" in part and "thought" not in part:
                content = part["text"]
                break
        if content is None:
            # Fallback: just get any text part
            for part in parts:
                if "text" in part:
                    content = part["text"]
                    break
        if content is None:
            raise Exception("No text content found in Gemini response")

        print(f"✅ Gemini response received ({len(content)} chars)")
        print(f"📝 Gemini raw response (first 500 chars): {content[:500]}")

        response_dict = {
            "content": content,
            "system_prompt": system_prompt,
            "user_prompt": full_prompt
        }

        # Cache the response
        if len(_query_cache) >= _MAX_CACHE_SIZE:
            _query_cache.clear()
        _query_cache[cache_key] = response_dict

        print(f"✅ Gemini response cached")
        return response_dict

    except requests.exceptions.Timeout:
        raise Exception("Gemini API timeout. Please try a simpler query.")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Gemini API request failed: {str(e)}")
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected response format from Gemini: {str(e)}")


def parse_geospatial_query(question: str, context: Dict[str, Any] = None, user_location: Dict[str, float] = None, query_type: str = None, selected_feature: Dict[str, Any] = None, selected_features: List[Dict[str, Any]] = None, drawn_geometry: Dict[str, Any] = None, llm_provider: str = None) -> OperationPlan:
    """
    Parse a natural language geospatial query into structured operations.
    Uses DeepSeek API to convert natural language to SQL.

    Args:
        question: Natural language query
        context: Optional context (city, timeframe, etc.)
        user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
        query_type: Optional query type ('spatial', 'stats', 'raster', 'routing') to guide response format
        selected_feature: Optional selected feature from map for context-aware queries
        selected_features: Optional list of multiple selected features (for routing)
        drawn_geometry: Optional geometry drawn by user (GeoJSON format) - used as spatial context

    Returns:
        OperationPlan with structured operations
    """
    # Check for routing keywords when multiple features are selected
    routing_keywords = ['route', 'directions', 'navigate', 'routing', 'path', 'journey', 'tour', 'visit', 'loop', 'best route', 'find route']
    is_routing_query = any(keyword in question.lower() for keyword in routing_keywords)

    # If routing query with 2+ selected features, create routing operation directly
    if is_routing_query and selected_features and len(selected_features) >= 2:
        print(f"🛣️  Detected routing query with {len(selected_features)} selected features")

        # Extract geometries and names from selected features
        geometries = []
        feature_names = []

        for feature in selected_features:
            if isinstance(feature, dict):
                if 'geometry' in feature:
                    geometries.append(feature['geometry'])
                if 'properties' in feature and 'name' in feature['properties']:
                    feature_names.append(feature['properties']['name'])
                elif 'name' in feature:
                    feature_names.append(feature['name'])
                else:
                    feature_names.append(f"Point {len(feature_names) + 1}")

        if geometries and len(geometries) >= 2:
            return OperationPlan(
                operations=[
                    GeospatialOperation(
                        operation="routing",
                        parameters={
                            "geometries": geometries,
                            "feature_names": feature_names,
                            "mode": "optimal_tour"
                        },
                        description="Find optimal tour connecting selected features"
                    )
                ],
                reasoning="Computing optimal route through all selected locations using Nearest Neighbor TSP algorithm",
                datasets_required=["routing.ways", "routing.ways_vertices_pgr"],
                layer_name="optimal_route"
            )

    # Route to appropriate LLM provider
    effective_query_type = query_type if not is_routing_query else "routing"
    provider = (llm_provider or "gemini").lower()

    try:
        if provider == "gemini":
            print("✨ Using Gemini API")
            response_dict = query_gemini(question, context, user_location, effective_query_type, selected_feature, drawn_geometry)
        else:
            print("🧠 Using DeepSeek API")
            response_dict = query_deepseek(question, context, user_location, effective_query_type, selected_feature, drawn_geometry)
    except Exception as api_err:
        print(f"❌ API Error: {api_err}")
        import traceback
        traceback.print_exc()
        return OperationPlan(
            operations=[
                GeospatialOperation(
                    operation="return",
                    parameters={"error": str(api_err)},
                    description=f"AI Provider Error: {provider}"
                )
            ],
            reasoning=f"Error querying {provider}: {str(api_err)}",
            datasets_required=[],
            system_prompt="",
            user_prompt=question
        )

    # Extract the content, system_prompt, and user_prompt from the dict
    raw_content = response_dict.get("content", "")
    system_prompt = response_dict.get("system_prompt", "")
    user_prompt = response_dict.get("user_prompt", "")

    # Try to parse the JSON response
    try:
        # Clean the response - sometimes LLMs wrap JSON in markdown
        cleaned_response = raw_content.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()

        # Attempt to parse JSON - with retry logic for common escaping issues
        try:
            parsed = json.loads(cleaned_response)
        except json.JSONDecodeError as first_error:
            # Try fixing common JSON escaping issues (unescaped quotes in SQL strings)
            import re

            # Look for SQL strings with unescaped quotes and try to fix them
            # Pattern: "sql": "SELECT ... " where " inside should be \"
            fixed_response = cleaned_response

            # Fix unescaped quotes within SQL strings
            # This is a heuristic approach - look for "sql": "...SELECT..." patterns
            pattern = r'"sql"\s*:\s*"((?:[^"\\]|\\.)*?(?:SELECT|INSERT|UPDATE|DELETE|WITH)[^"]*?)"'

            def escape_sql_string(match):
                sql_content = match.group(1)
                # Escape any unescaped quotes in the SQL
                # Don't escape quotes that are already escaped
                escaped = sql_content.replace('"', '\\"').replace('\\"\\', '\\"')
                return f'"sql": "{escaped}"'

            fixed_response = re.sub(pattern, escape_sql_string, fixed_response, flags=re.IGNORECASE | re.DOTALL)

            # Try parsing again with fixed response
            try:
                parsed = json.loads(fixed_response)
                print("✅ JSON parsing fixed with escape handling")
            except json.JSONDecodeError as second_error:
                # If still failing, log and raise original error
                print(f"❌ JSON parsing still failed after escape fix: {second_error}")
                raise first_error

        # Convert to OperationPlan
        operations = [
            GeospatialOperation(**op) for op in parsed.get("operations", [])
        ]

        # Inject session_id from context into operations that need it
        # This ensures selected features work even if DeepSeek doesn't include session_id
        session_id = context.get("session_id") if context else None
        if session_id:
            ops_needing_session = ["walking_time", "nearest_by_road"]
            for op in operations:
                # Handle both string and enum operation types
                op_name = op.operation.value if hasattr(op.operation, 'value') else str(op.operation)
                if op_name in ops_needing_session:
                    if "session_id" not in op.parameters:
                        op.parameters["session_id"] = session_id
                        print(f"💉 Injected session_id '{session_id}' into {op_name} operation")

        return OperationPlan(
            operations=operations,
            layer_name=parsed.get("layer_name"),
            reasoning=parsed.get("reasoning"),
            datasets_required=parsed.get("datasets_required", []),
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )

    except json.JSONDecodeError as e:
        # If JSON parsing fails, create a simple fallback plan
        print(f"Failed to parse DeepSeek response as JSON: {e}")
        print(f"Raw response: {raw_content}")

        # Return a basic error plan
        return OperationPlan(
            operations=[
                GeospatialOperation(
                    operation="return",
                    parameters={"error": "Failed to parse query"},
                    description=f"Could not parse: {question}"
                )
            ],
            reasoning=f"Error parsing response: {raw_content}",
            datasets_required=[],
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )


def clear_query_cache() -> None:
    """
    Clear the in-memory query cache.
    Useful for testing or resetting the system.
    """
    global _query_cache
    _query_cache.clear()
    print("✅ Query cache cleared")


def get_available_datasets() -> List[Dict[str, Any]]:
    """
    Return list of available datasets from PostGIS.
    Queries actual database tables.
    """
    from app.utils.database import db_manager

    try:
        # Get tables from PostGIS
        tables = db_manager.get_available_tables(schema="vector")

        datasets = []
        for table in tables:
            try:
                info = db_manager.get_table_info(table, schema="vector")
                datasets.append({
                    "name": table,
                    "type": "vector",
                    "description": f"{info['geometry_type']} - {info['row_count']} features",
                    "schema": "vector",
                    "row_count": info['row_count'],
                    "geometry_type": info['geometry_type'],
                    "columns": [col['name'] for col in info['columns']]
                })
            except Exception as e:
                print(f"Could not get info for table {table}: {e}")
                datasets.append({
                    "name": table,
                    "type": "vector",
                    "description": "PostGIS table",
                    "schema": "vector"
                })

        return datasets

    except Exception as e:
        print(f"Could not query database for datasets: {e}")
        # Fallback to known Berlin OSM tables
        return [
            {"name": "osm_hospitals", "type": "vector", "description": "Hospital locations in Berlin (59 features)", "schema": "vector"},
            {"name": "osm_toilets", "type": "vector", "description": "Public toilets in Berlin (1,160 features)", "schema": "vector"},
            {"name": "osm_pharmacies", "type": "vector", "description": "Pharmacy locations in Berlin (768 features)", "schema": "vector"},
            {"name": "osm_fire_stations", "type": "vector", "description": "Fire stations in Berlin (179 features)", "schema": "vector"},
            {"name": "osm_police_stations", "type": "vector", "description": "Police stations in Berlin (81 features)", "schema": "vector"},
            {"name": "osm_parks", "type": "vector", "description": "Parks in Berlin (2,785 features)", "schema": "vector"},
            {"name": "osm_schools", "type": "vector", "description": "Schools in Berlin (1,195 features)", "schema": "vector"},
            {"name": "osm_restaurants", "type": "vector", "description": "Restaurants in Berlin (5,013 features)", "schema": "vector"},
            {"name": "osm_transport_stops", "type": "vector", "description": "Transport stops in Berlin (14,899 features)", "schema": "vector"},
        ]
