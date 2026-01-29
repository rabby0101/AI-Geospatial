"""
Weight Calculator - Dynamically assign weights to criteria
Implements smart weight distribution based on query context and availability
"""

from typing import Dict, List, Any
from app.utils.criteria_extractor import CriteriaExtractor


class WeightCalculator:
    """Calculate dynamic weights for multi-criteria scoring"""

    # Context-specific weight distributions
    CONTEXT_WEIGHTS = {
        'family': {
            'osm_schools': 0.25,
            'osm_parks': 0.25,
            'osm_supermarkets': 0.15,
            'osm_hospitals': 0.15,
            'osm_police_stations': 0.10,
            'osm_fire_stations': 0.10,
        },
        'student': {
            'osm_universities': 0.30,
            'osm_libraries': 0.20,
            'osm_restaurants': 0.15,
            'osm_supermarkets': 0.15,
            'osm_transport_stops': 0.10,
            'osm_banks': 0.10,
        },
        'senior': {
            'osm_hospitals': 0.25,
            'osm_pharmacies': 0.20,
            'osm_parks': 0.20,
            'osm_supermarkets': 0.15,
            'osm_transport_stops': 0.10,
            'osm_doctors': 0.10,
        },
        'shopping': {
            'osm_supermarkets': 0.30,
            'osm_banks': 0.20,
            'osm_atm': 0.15,
            'osm_post_offices': 0.15,
            'osm_parking': 0.10,
            'osm_restaurants': 0.10,
        },
        'culture': {
            'osm_museums': 0.30,
            'osm_theatres': 0.25,
            'osm_libraries': 0.15,
            'osm_restaurants': 0.15,
            'osm_transport_stops': 0.10,
            'osm_parks': 0.05,
        },
        'health': {
            'osm_hospitals': 0.25,
            'osm_pharmacies': 0.20,
            'osm_doctors': 0.15,
            'osm_parks': 0.15,
            'osm_dentists': 0.10,
            'osm_veterinary': 0.05,
        },
        'walkable': {
            'osm_parks': 0.25,
            'osm_restaurants': 0.20,
            'osm_supermarkets': 0.15,
            'osm_transport_stops': 0.15,
            'osm_cafes': 0.10,
            'osm_libraries': 0.10,
        },
        'green': {
            'osm_parks': 0.40,
            'osm_forests': 0.30,
            'osm_water_bodies': 0.15,
            'osm_transport_stops': 0.10,
            'osm_restaurants': 0.05,
        },
        # ========== BUSINESS SITE SELECTION CONTEXTS ==========
        'restaurant': {
            'osm_transport_stops': 0.25,  # Foot traffic - positive
            'osm_buildings': 0.20,         # Residential density - positive (use filter)
            'osm_universities': 0.15,      # Young demographics - positive
            'osm_restaurants': -0.30,      # Competition - NEGATIVE
            'osm_parks': 0.10,             # Visibility/synergy - positive
        },
        'cafe': {
            'osm_transport_stops': 0.30,   # Foot traffic - critical for cafes
            'osm_buildings': 0.25,         # Office workers (COMMERCIAL filter)
            'osm_universities': 0.20,      # Students
            'osm_libraries': 0.10,         # Study spots synergy
            'osm_restaurants': -0.25,      # Competition (filter by coffee/cafe)
        },
        'pharmacy': {
            'osm_hospitals': 0.25,         # Healthcare proximity
            'osm_clinics': 0.15,           # Healthcare proximity
            'osm_doctors': 0.10,           # Healthcare proximity
            'osm_buildings': 0.25,         # Residential density
            'osm_pharmacies': -0.35,       # Competition - NEGATIVE
        },
        'library': {
            'osm_schools': 0.25,           # Educational synergy
            'osm_universities': 0.20,      # Academic users
            'osm_buildings': 0.20,         # Residential base
            'osm_parks': 0.05,             # Recreation synergy
            'osm_libraries': -0.30,        # Competition - NEGATIVE
        },
        'supermarket': {
            'osm_buildings': 0.40,         # Residential density - primary driver
            'osm_transport_stops': 0.15,   # Accessibility
            'osm_parking': 0.10,           # Car accessibility
            'osm_supermarkets': -0.40,     # Competition - NEGATIVE
        },
        'gym': {
            'osm_buildings': 0.30,         # Residential + commercial
            'osm_universities': 0.15,      # Young population
            'osm_transport_stops': 0.15,   # Accessibility
            'osm_parks': 0.10,             # Fitness culture synergy
            'osm_restaurants': -0.20,      # Competition (filter by gym/fitness)
        },
        'general': None,  # Use equal weights
    }

    @staticmethod
    def calculate_weights(
        criteria_data: Dict[str, Any],
        context: str = None
    ) -> Dict[str, Any]:
        """
        Calculate weights for available criteria.

        Args:
            criteria_data: Output from CriteriaExtractor.extract_criteria()
            context: Optional context override (e.g., 'family', 'student')

        Returns:
            Dictionary with:
            - weights: {table_name: weight} for available criteria
            - context: Profile used for weighting
            - weight_metadata: Info about weight calculation
            - redistribution_applied: Whether weights were redistributed
        """
        context = context or criteria_data.get('query_context', 'general')

        # Get criteria
        available_criteria = [
            c for c in criteria_data['criteria'] if c['available']
        ]

        if not available_criteria:
            return {
                'weights': {},
                'context': context,
                'error': 'No available criteria found',
                'weight_metadata': {}
            }

        # Get base weights for this context
        base_weights = WeightCalculator.CONTEXT_WEIGHTS.get(context)

        if base_weights is None:
            # Use equal weights if context not found or is 'general'
            weights = WeightCalculator._equal_weights(available_criteria)
            redistribution_applied = False
            weight_method = 'equal'
        else:
            # Use context-specific weights
            weights, redistribution_applied = WeightCalculator._apply_context_weights(
                available_criteria, base_weights
            )
            weight_method = 'context-specific'

        # Normalize weights to sum to 1.0
        total_weight = sum(weights.values())
        if total_weight > 0:
            normalized_weights = {
                table: weight / total_weight
                for table, weight in weights.items()
            }
        else:
            normalized_weights = weights

        # Generate metadata
        weight_metadata = WeightCalculator._generate_metadata(
            available_criteria,
            criteria_data['criteria'],
            normalized_weights,
            context,
            weight_method,
            redistribution_applied
        )

        return {
            'weights': normalized_weights,
            'context': context,
            'weight_metadata': weight_metadata,
            'redistribution_applied': redistribution_applied,
            'weight_method': weight_method,
            'available_criteria': [c['name'] for c in available_criteria],
            'excluded_criteria': [c['name'] for c in criteria_data['criteria'] if not c['available']]
        }

    @staticmethod
    def _equal_weights(criteria: List[Dict[str, Any]]) -> Dict[str, float]:
        """Assign equal weights to all criteria"""
        weight = 1.0 / len(criteria) if criteria else 0
        return {c['table']: weight for c in criteria}

    @staticmethod
    def _apply_context_weights(
        available_criteria: List[Dict[str, Any]],
        base_weights: Dict[str, float]
    ) -> tuple:
        """
        Apply context-specific weights to available criteria.
        Redistribute weights if some criteria are unavailable.
        """
        weights = {}
        redistribution_applied = False

        # Assign weights from base_weights
        for criterion in available_criteria:
            table = criterion['table']
            weight = base_weights.get(table, 0)
            weights[table] = weight

        # If weights sum to less than 1.0, redistribute proportionally
        total_weight = sum(weights.values())

        if total_weight == 0:
            # No matching weights in base_weights, use equal
            return WeightCalculator._equal_weights(available_criteria), True

        if total_weight < 1.0:
            # Some criteria weren't in the base weights - redistribute
            redistribution_applied = True
            scale_factor = 1.0 / total_weight
            weights = {table: weight * scale_factor for table, weight in weights.items()}

        return weights, redistribution_applied

    @staticmethod
    def _generate_metadata(
        available_criteria: List[Dict[str, Any]],
        all_criteria: List[Dict[str, Any]],
        weights: Dict[str, float],
        context: str,
        weight_method: str,
        redistribution_applied: bool
    ) -> Dict[str, Any]:
        """Generate detailed metadata about weight calculation"""
        excluded = [c for c in all_criteria if not c['available']]

        metadata = {
            'total_criteria_requested': len(all_criteria),
            'criteria_used': len(available_criteria),
            'criteria_excluded': len(excluded),
            'context': context,
            'weight_method': weight_method,
            'redistribution_applied': redistribution_applied,
            'weights_by_criterion': {}
        }

        # Add per-criterion weight info
        for criterion in available_criteria:
            table = criterion['table']
            weight = weights.get(table, 0)
            metadata['weights_by_criterion'][criterion['name']] = {
                'table': table,
                'weight': round(weight, 4),
                'percentage': round(weight * 100, 1)
            }

        # Add exclusion info
        if excluded:
            metadata['excluded_criteria'] = []
            for criterion in excluded:
                metadata['excluded_criteria'].append({
                    'name': criterion['name'],
                    'reason': criterion.get('reason', 'Unknown')
                })

        # Add reasoning
        if redistribution_applied:
            excluded_names = [c['name'] for c in excluded]
            metadata['redistribution_note'] = (
                f"Weights redistributed due to unavailable criteria: {', '.join(excluded_names)}"
            )

        return metadata
