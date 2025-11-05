"""
Criteria Extractor - Parse queries and extract amenity criteria
Converts natural language queries into structured criteria for multi-criteria scoring
"""

import re
from typing import List, Dict, Any, Tuple
from app.utils.database import db_manager

# Mapping of amenity names (various aliases) to actual database tables
AMENITY_MAPPING = {
    # Schools & Education
    'schools': 'osm_schools',
    'school': 'osm_schools',
    'schulen': 'osm_schools',
    'grundschulen': 'osm_schools',
    'universitäten': 'osm_universities',
    'universities': 'osm_universities',
    'uni': 'osm_universities',
    'bibliotheken': 'osm_libraries',
    'libraries': 'osm_libraries',
    'bücherei': 'osm_libraries',

    # Healthcare
    'hospitals': 'osm_hospitals',
    'krankenhäuser': 'osm_hospitals',
    'kliniken': 'osm_clinics',
    'clinics': 'osm_clinics',
    'pharmacies': 'osm_pharmacies',
    'apotheken': 'osm_pharmacies',
    'ärzte': 'osm_doctors',
    'doctors': 'osm_doctors',
    'zahnarzt': 'osm_dentists',
    'zahnärzte': 'osm_dentists',
    'dentists': 'osm_dentists',
    'tierarzt': 'osm_veterinary',
    'tierärzte': 'osm_veterinary',
    'veterinary': 'osm_veterinary',

    # Parks & Nature
    'parks': 'osm_parks',
    'park': 'osm_parks',
    'parks': 'osm_parks',
    'grünflächen': 'osm_parks',
    'wälder': 'osm_forests',
    'forests': 'osm_forests',
    'wald': 'osm_forests',

    # Recreation & Culture
    'restaurants': 'osm_restaurants',
    'restaurant': 'osm_restaurants',
    'cafés': 'osm_restaurants',
    'cafes': 'osm_restaurants',
    'café': 'osm_restaurants',
    'cafeteria': 'osm_restaurants',
    'museums': 'osm_museums',
    'museen': 'osm_museums',
    'theatre': 'osm_theatres',
    'theater': 'osm_theatres',
    'theatre': 'osm_theatres',
    'théâtre': 'osm_theatres',

    # Shopping & Commerce
    'supermarkets': 'osm_supermarkets',
    'supermärkte': 'osm_supermarkets',
    'supermarkt': 'osm_supermarkets',
    'shops': 'osm_supermarkets',
    'läden': 'osm_supermarkets',
    'banks': 'osm_banks',
    'banken': 'osm_banks',
    'atm': 'osm_atm',
    'geldautomaten': 'osm_atm',
    'post offices': 'osm_post_offices',
    'postfilialen': 'osm_post_offices',
    'postamt': 'osm_post_offices',
    'parking': 'osm_parking',
    'parkplätze': 'osm_parking',
    'parkplatz': 'osm_parking',

    # Services & Other
    'fire stations': 'osm_fire_stations',
    'feuerwehr': 'osm_fire_stations',
    'police stations': 'osm_police_stations',
    'polizeistationen': 'osm_police_stations',
    'polizei': 'osm_police_stations',
    'sicherheitsdienste': 'osm_police_stations',  # German: security services
    'sicherheit': 'osm_police_stations',  # German: security
    'security': 'osm_police_stations',
    'security services': 'osm_police_stations',
    'transport stops': 'osm_transport_stops',
    'verkehrshaltestellen': 'osm_transport_stops',
    'haltestellen': 'osm_transport_stops',
    'öffentliche verkehrsmittel': 'osm_transport_stops',
    'water bodies': 'osm_water_bodies',
    'wasserflächen': 'osm_water_bodies',
    'seen': 'osm_water_bodies',
    'allotment gardens': 'osm_allotment_gardens',
    'kleingärten': 'osm_allotment_gardens',
    'schrebergärten': 'osm_allotment_gardens',

    # UNAVAILABLE (but might be requested)
    'kindergartens': None,
    'kindergärten': None,
    'kita': None,
    'playgrounds': None,
    'spielplätze': None,
    'spielplatz': None,
    'gyms': None,
    'fitnessstudios': None,
    'fitnessstudio': None,
    'bars': None,
    'clubs': None,
    'nachtclubs': None,
}

# List of all available tables in the database
AVAILABLE_TABLES = {
    'osm_hospitals', 'osm_clinics', 'osm_pharmacies', 'osm_doctors', 'osm_dentists',
    'osm_veterinary', 'osm_schools', 'osm_universities', 'osm_libraries',
    'osm_parks', 'osm_forests', 'osm_water_bodies',
    'osm_restaurants', 'osm_museums', 'osm_theatres',
    'osm_supermarkets', 'osm_banks', 'osm_atm', 'osm_post_offices', 'osm_parking',
    'osm_fire_stations', 'osm_police_stations', 'osm_transport_stops',
    'osm_allotment_gardens'
}


class CriteriaExtractor:
    """Extract and map amenity criteria from natural language queries"""

    @staticmethod
    def extract_criteria(query: str) -> Dict[str, Any]:
        """
        Extract criteria from a natural language query.

        Args:
            query: Natural language query (e.g., "Best areas for families (schools + parks)")

        Returns:
            Dictionary with:
            - criteria: List of criterion dicts with name, table, available, order
            - available_count: Number of available criteria
            - missing_count: Number of unavailable criteria
            - query_context: Inferred profile (family, student, senior, etc.)
            - has_scoring: Whether this is a multi-criteria scoring query
        """
        query_lower = query.lower()

        # Extract context from query
        context = CriteriaExtractor._extract_context(query_lower)

        # Find all mentioned amenities (case-insensitive, with order)
        mentioned_amenities = CriteriaExtractor._extract_amenities(query_lower)

        # Map to database tables and check availability
        criteria = []
        available_count = 0
        missing_count = 0

        for order, amenity_name in enumerate(mentioned_amenities):
            # Get table name
            table_name = AMENITY_MAPPING.get(amenity_name.lower())

            if table_name is None:
                # Amenity mentioned but not in mapping (unavailable)
                criteria.append({
                    'name': amenity_name,
                    'table': None,
                    'available': False,
                    'order': order,
                    'reason': 'Data not available in database'
                })
                missing_count += 1
            elif table_name not in AVAILABLE_TABLES:
                # Table in mapping but not in available list
                criteria.append({
                    'name': amenity_name,
                    'table': table_name,
                    'available': False,
                    'order': order,
                    'reason': 'Table not found in database'
                })
                missing_count += 1
            else:
                # Criterion is available
                criteria.append({
                    'name': amenity_name,
                    'table': table_name,
                    'available': True,
                    'order': order,
                    'reason': None
                })
                available_count += 1

        # Determine if this is a multi-criteria scoring query
        has_scoring = available_count >= 2 and (
            'best' in query_lower or 'suitable' in query_lower or 'eignen sich' in query_lower
        )

        return {
            'criteria': criteria,
            'available_count': available_count,
            'missing_count': missing_count,
            'total_count': len(mentioned_amenities),
            'query_context': context,
            'has_scoring': has_scoring,
            'available_tables': [c['table'] for c in criteria if c['available']],
            'missing_tables': [c['name'] for c in criteria if not c['available']]
        }

    @staticmethod
    def _extract_context(query_lower: str) -> str:
        """Extract context/profile from query keywords"""
        if any(word in query_lower for word in ['family', 'familien', 'kinder', 'children']):
            return 'family'
        elif any(word in query_lower for word in ['student', 'studieren', 'uni', 'university']):
            return 'student'
        elif any(word in query_lower for word in ['senior', 'elderly', 'alt']):
            return 'senior'
        elif any(word in query_lower for word in ['shop', 'shopping', 'einkaufen', 'commerce']):
            return 'shopping'
        elif any(word in query_lower for word in ['culture', 'kultur', 'art', 'kunst']):
            return 'culture'
        elif any(word in query_lower for word in ['health', 'health', 'gesundheit', 'wellness']):
            return 'health'
        elif any(word in query_lower for word in ['walkable', 'walk', 'spazieren', 'walk']):
            return 'walkable'
        elif any(word in query_lower for word in ['nature', 'green', 'natur', 'grün']):
            return 'green'
        else:
            return 'general'

    @staticmethod
    def _extract_amenities(query_lower: str) -> List[str]:
        """
        Extract amenity names from query.
        Looks for patterns like: "schools + parks" or "schools, parks, hospitals"
        """
        # Extract content within parentheses if exists (do this first)
        paren_match = re.search(r'\((.*?)\)', query_lower)
        if paren_match:
            query_clean = paren_match.group(1)
        else:
            query_clean = query_lower

        # Remove common words using word boundaries to avoid breaking amenity names
        # Use regex with word boundaries for cleaner removal
        stopwords = ['which', 'areas', 'are', 'best', 'for', 'with', 'the', 'in', 'district', 'districts',
                     'welche', 'gegenden', 'eignen', 'sich', 'geeignet', 'beste', 'für', 'familien']
        for word in stopwords:
            query_clean = re.sub(r'\b' + word + r'\b', ' ', query_clean, flags=re.IGNORECASE)

        # Split by common delimiters and clean
        amenities = re.split(r'[+&/,;]|and|oder|sowie', query_clean)
        amenities = [a.strip() for a in amenities if a.strip()]

        # Map to canonical names and deduplicate while preserving order
        mapped_amenities = []
        seen = set()

        for amenity in amenities:
            # Try exact match first, then partial match
            for key in AMENITY_MAPPING.keys():
                if key in amenity.lower():
                    if key not in seen:
                        mapped_amenities.append(key)
                        seen.add(key)
                    break

        return mapped_amenities

    @staticmethod
    def get_excluded_criteria_info(extracted: Dict[str, Any]) -> str:
        """
        Generate human-readable string about excluded criteria
        """
        excluded = [c for c in extracted['criteria'] if not c['available']]

        if not excluded:
            return ""

        messages = []
        for criterion in excluded:
            reason = criterion.get('reason', 'Not available')
            messages.append(f"{criterion['name']} ({reason})")

        return "Unavailable criteria (excluded from analysis): " + ", ".join(messages)
