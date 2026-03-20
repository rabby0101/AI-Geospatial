"""
Business Scorer - Sophisticated scoring for business site selection
Implements distance decay, normalization, and business-specific weight profiles
"""

import math
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DecayFunction(Enum):
    """Distance decay function types"""
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    GAUSSIAN = "gaussian"
    INVERSE = "inverse"
    STEP = "step"  # Binary within threshold


class FactorType(Enum):
    """Type of scoring factor"""
    POSITIVE = "positive"      # Higher count = better (foot traffic, customers)
    NEGATIVE = "negative"      # Higher count = worse (competition)
    SYNERGY = "synergy"        # Complementary businesses (bars near restaurants)
    THRESHOLD = "threshold"    # Must meet minimum (e.g., at least 1 bus stop)


class BusinessScorer:
    """
    Sophisticated business site selection scoring.
    
    Features:
    - Distance decay functions (exponential, linear, gaussian)
    - Min-max normalization for fair comparison
    - Business-specific weight profiles
    - Competition differentiation (direct vs indirect)
    - Residential density as demand proxy
    """
    
    # Business-specific scoring profiles
    # Each profile defines criteria with weights, radii, decay functions, and factor types
    BUSINESS_PROFILES = {
        'restaurant': {
            'description': 'General restaurant/dining establishment',
            'criteria': {
                'foot_traffic': {
                    'tables': ['osm_transport_stops'],
                    'weight': 0.25,
                    'radius': 300,
                    'decay': DecayFunction.EXPONENTIAL,
                    'decay_constant': 150,
                    'factor_type': FactorType.POSITIVE,
                },
                'target_customers': {
                    'tables': ['osm_universities', 'osm_schools'],
                    'weight': 0.15,
                    'radius': 800,
                    'decay': DecayFunction.GAUSSIAN,
                    'decay_constant': 400,
                    'factor_type': FactorType.POSITIVE,
                },
                'residential_base': {
                    'tables': ['alkis_buildings'],
                    'filter': "RESIDENTIAL",
                    'weight': 0.20,
                    'radius': 500,
                    'decay': DecayFunction.LINEAR,
                    'factor_type': FactorType.POSITIVE,
                },
                'complementary': {
                    'tables': ['osm_restaurants'],
                    'weight': 0.10,
                    'radius': 150,
                    'decay': DecayFunction.STEP,
                    'threshold': 50,  # Very close restaurants create dining district
                    'factor_type': FactorType.SYNERGY,
                },
                'competition': {
                    'tables': ['osm_restaurants'],
                    'weight': 0.30,
                    'radius': 500,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 200,
                    'factor_type': FactorType.NEGATIVE,
                },
            }
        },
        'mexican_restaurant': {
            'description': 'Mexican cuisine restaurant',
            'parent': 'restaurant',  # Inherits base restaurant profile
            'criteria': {
                'competition_direct': {
                    'tables': ['osm_restaurants'],
                    'cuisine_filter': '%mexican%',
                    'weight': 0.35,
                    'radius': 800,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 300,
                    'factor_type': FactorType.NEGATIVE,
                },
                'competition_indirect': {
                    'tables': ['osm_restaurants'],
                    'cuisine_filter': '%tex%|%taco%|%burrito%|%latin%',
                    'weight': 0.15,
                    'radius': 500,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 250,
                    'factor_type': FactorType.NEGATIVE,
                },
                'synergy_nightlife': {
                    'tables': ['osm_restaurants'],
                    'cuisine_filter': '%bar%|%pub%',
                    'weight': 0.10,
                    'radius': 200,
                    'decay': DecayFunction.EXPONENTIAL,
                    'decay_constant': 100,
                    'factor_type': FactorType.SYNERGY,
                },
            }
        },
        'cafe': {
            'description': 'Coffee shop / Cafe',
            'criteria': {
                'foot_traffic': {
                    'tables': ['osm_transport_stops'],
                    'weight': 0.30,
                    'radius': 250,
                    'decay': DecayFunction.EXPONENTIAL,
                    'decay_constant': 100,
                    'factor_type': FactorType.POSITIVE,
                },
                'office_workers': {
                    'tables': ['alkis_buildings'],
                    'filter': 'COMMERCIAL',
                    'weight': 0.25,
                    'radius': 400,
                    'decay': DecayFunction.LINEAR,
                    'factor_type': FactorType.POSITIVE,
                },
                'students': {
                    'tables': ['osm_universities', 'osm_libraries'],
                    'weight': 0.20,
                    'radius': 600,
                    'decay': DecayFunction.GAUSSIAN,
                    'decay_constant': 300,
                    'factor_type': FactorType.POSITIVE,
                },
                'competition': {
                    'tables': ['osm_restaurants'],
                    'cuisine_filter': '%coffee%|%cafe%|%kaffee%',
                    'weight': 0.25,
                    'radius': 400,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 150,
                    'factor_type': FactorType.NEGATIVE,
                },
            }
        },
        'pharmacy': {
            'description': 'Pharmacy / Drugstore',
            'criteria': {
                'healthcare_proximity': {
                    'tables': ['osm_hospitals', 'osm_clinics', 'osm_doctors'],
                    'weight': 0.35,
                    'radius': 800,
                    'decay': DecayFunction.EXPONENTIAL,
                    'decay_constant': 400,
                    'factor_type': FactorType.POSITIVE,
                },
                'residential_base': {
                    'tables': ['alkis_buildings'],
                    'filter': 'RESIDENTIAL',
                    'weight': 0.25,
                    'radius': 600,
                    'decay': DecayFunction.LINEAR,
                    'factor_type': FactorType.POSITIVE,
                },
                'senior_facilities': {
                    'tables': ['osm_hospitals'],  # Proxy for senior care
                    'weight': 0.10,
                    'radius': 1000,
                    'decay': DecayFunction.GAUSSIAN,
                    'decay_constant': 500,
                    'factor_type': FactorType.POSITIVE,
                },
                'competition': {
                    'tables': ['osm_pharmacies'],
                    'weight': 0.30,
                    'radius': 800,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 400,
                    'factor_type': FactorType.NEGATIVE,
                },
            }
        },
        'library': {
            'description': 'Public library',
            'criteria': {
                'educational_proximity': {
                    'tables': ['osm_schools', 'osm_universities'],
                    'weight': 0.35,
                    'radius': 1000,
                    'decay': DecayFunction.GAUSSIAN,
                    'decay_constant': 500,
                    'factor_type': FactorType.POSITIVE,
                },
                'residential_base': {
                    'tables': ['alkis_buildings'],
                    'filter': 'RESIDENTIAL',
                    'weight': 0.25,
                    'radius': 800,
                    'decay': DecayFunction.LINEAR,
                    'factor_type': FactorType.POSITIVE,
                },
                'parks_recreation': {
                    'tables': ['osm_parks'],
                    'weight': 0.10,
                    'radius': 500,
                    'decay': DecayFunction.STEP,
                    'threshold': 300,
                    'factor_type': FactorType.SYNERGY,
                },
                'competition': {
                    'tables': ['osm_libraries'],
                    'weight': 0.30,
                    'radius': 2000,  # Libraries serve larger areas
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 1000,
                    'factor_type': FactorType.NEGATIVE,
                },
            }
        },
        'supermarket': {
            'description': 'Grocery store / Supermarket',
            'criteria': {
                'residential_density': {
                    'tables': ['alkis_buildings'],
                    'filter': 'RESIDENTIAL',
                    'weight': 0.40,
                    'radius': 800,
                    'decay': DecayFunction.LINEAR,
                    'factor_type': FactorType.POSITIVE,
                },
                'accessibility': {
                    'tables': ['osm_transport_stops', 'osm_parking'],
                    'weight': 0.20,
                    'radius': 400,
                    'decay': DecayFunction.EXPONENTIAL,
                    'decay_constant': 200,
                    'factor_type': FactorType.POSITIVE,
                },
                'competition': {
                    'tables': ['osm_supermarkets'],
                    'weight': 0.40,
                    'radius': 1000,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 500,
                    'factor_type': FactorType.NEGATIVE,
                },
            }
        },
        'gym': {
            'description': 'Fitness center / Gym',
            'criteria': {
                'office_workers': {
                    'tables': ['alkis_buildings'],
                    'filter': 'COMMERCIAL',
                    'weight': 0.25,
                    'radius': 600,
                    'decay': DecayFunction.EXPONENTIAL,
                    'decay_constant': 300,
                    'factor_type': FactorType.POSITIVE,
                },
                'residential_base': {
                    'tables': ['alkis_buildings'],
                    'filter': 'RESIDENTIAL',
                    'weight': 0.30,
                    'radius': 1000,
                    'decay': DecayFunction.LINEAR,
                    'factor_type': FactorType.POSITIVE,
                },
                'young_population': {
                    'tables': ['osm_universities'],
                    'weight': 0.15,
                    'radius': 1500,
                    'decay': DecayFunction.GAUSSIAN,
                    'decay_constant': 800,
                    'factor_type': FactorType.POSITIVE,
                },
                'competition': {
                    'tables': ['osm_restaurants'],  # Proxy - no gym table
                    'cuisine_filter': '%fitness%|%gym%|%sport%',
                    'weight': 0.30,
                    'radius': 1500,
                    'decay': DecayFunction.INVERSE,
                    'decay_constant': 700,
                    'factor_type': FactorType.NEGATIVE,
                },
            }
        },
    }
    
    # Cuisine keywords for restaurant type detection
    CUISINE_KEYWORDS = {
        'mexican': ['mexican', 'tex-mex', 'taco', 'burrito', 'quesadilla', 'enchilada'],
        'italian': ['italian', 'pizza', 'pasta', 'trattoria', 'ristorante'],
        'asian': ['asian', 'chinese', 'japanese', 'thai', 'vietnamese', 'korean', 'sushi', 'ramen'],
        'indian': ['indian', 'curry', 'tandoori', 'masala'],
        'cafe': ['coffee', 'cafe', 'kaffee', 'espresso', 'latte'],
        'bar': ['bar', 'pub', 'tavern', 'brewery', 'bier'],
        'fast_food': ['burger', 'fast food', 'döner', 'kebab', 'imbiss'],
    }

    @staticmethod
    def detect_business_type(query: str) -> str:
        """
        Detect business type from natural language query.
        
        Args:
            query: User's natural language query
            
        Returns:
            Business type key matching BUSINESS_PROFILES
        """
        query_lower = query.lower()
        
        # Check for specific restaurant cuisines
        for cuisine, keywords in BusinessScorer.CUISINE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in query_lower:
                    if cuisine in ['cafe']:
                        return 'cafe'
                    elif cuisine == 'mexican':
                        return 'mexican_restaurant'
                    else:
                        return 'restaurant'
        
        # Check for other business types
        business_keywords = {
            'pharmacy': ['pharmacy', 'apotheke', 'drugstore', 'chemist'],
            'library': ['library', 'bibliothek', 'bücherei'],
            'supermarket': ['supermarket', 'grocery', 'lebensmittel', 'edeka', 'rewe', 'aldi', 'lidl'],
            'cafe': ['coffee shop', 'cafe', 'café', 'kaffee'],
            'gym': ['gym', 'fitness', 'fitnessstudio', 'sport'],
            'restaurant': ['restaurant', 'eatery', 'diner', 'bistro', 'gaststätte'],
        }
        
        for business_type, keywords in business_keywords.items():
            for keyword in keywords:
                if keyword in query_lower:
                    return business_type
        
        # Default to restaurant for food-related queries
        food_indicators = ['open', 'start', 'launch', 'food', 'eat', 'dining']
        if any(word in query_lower for word in food_indicators):
            return 'restaurant'
        
        return 'restaurant'  # Default fallback

    @staticmethod
    def get_profile(business_type: str) -> Dict[str, Any]:
        """
        Get scoring profile for a business type, with inheritance support.
        
        Args:
            business_type: Key from BUSINESS_PROFILES
            
        Returns:
            Complete scoring profile with inherited criteria
        """
        if business_type not in BusinessScorer.BUSINESS_PROFILES:
            business_type = 'restaurant'  # Fallback
        
        profile = BusinessScorer.BUSINESS_PROFILES[business_type].copy()
        
        # Handle inheritance
        if 'parent' in profile:
            parent_profile = BusinessScorer.BUSINESS_PROFILES.get(profile['parent'], {})
            parent_criteria = parent_profile.get('criteria', {}).copy()
            
            # Child criteria override parent
            child_criteria = profile.get('criteria', {})
            parent_criteria.update(child_criteria)
            profile['criteria'] = parent_criteria
        
        return profile

    @staticmethod
    def calculate_decay(distance: float, decay_type: DecayFunction, 
                        max_radius: float, decay_constant: float = None,
                        threshold: float = None) -> float:
        """
        Calculate distance decay score.
        
        Args:
            distance: Distance in meters
            decay_type: Type of decay function
            max_radius: Maximum radius for the factor
            decay_constant: Decay rate parameter (meaning varies by function)
            threshold: Threshold distance for step function
            
        Returns:
            Decay factor between 0 and 1
        """
        if distance > max_radius:
            return 0.0
        
        if distance <= 0:
            return 1.0
        
        decay_constant = decay_constant or (max_radius / 3)
        
        if decay_type == DecayFunction.LINEAR:
            # Linear decay: 1 at distance 0, 0 at max_radius
            return max(0, 1 - (distance / max_radius))
        
        elif decay_type == DecayFunction.EXPONENTIAL:
            # Exponential decay: fast drop-off
            return math.exp(-distance / decay_constant)
        
        elif decay_type == DecayFunction.GAUSSIAN:
            # Gaussian (bell curve): moderate at center, drops off
            sigma = decay_constant
            return math.exp(-(distance ** 2) / (2 * sigma ** 2))
        
        elif decay_type == DecayFunction.INVERSE:
            # Inverse: slower decay, good for penalties
            scale = decay_constant
            return 1 / (1 + distance / scale)
        
        elif decay_type == DecayFunction.STEP:
            # Binary step: 1 if within threshold, 0 otherwise
            threshold = threshold or (max_radius / 2)
            return 1.0 if distance <= threshold else 0.0
        
        return 1.0  # Default no decay

    @staticmethod
    def normalize_scores(scores: List[float]) -> List[float]:
        """
        Apply min-max normalization to scores.
        
        Args:
            scores: List of raw scores
            
        Returns:
            List of normalized scores (0-1 range)
        """
        if not scores:
            return []
        
        min_score = min(scores)
        max_score = max(scores)
        
        if max_score == min_score:
            # All scores are equal
            return [0.5] * len(scores)
        
        return [(s - min_score) / (max_score - min_score) for s in scores]

    @staticmethod
    def calculate_criterion_score(
        feature_data: Dict[str, Any],
        criterion_config: Dict[str, Any]
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate score for a single criterion with distance decay.
        
        Args:
            feature_data: Feature data including nearby counts and distances
            criterion_config: Configuration for this criterion
            
        Returns:
            Tuple of (score, breakdown_info)
        """
        weight = criterion_config.get('weight', 0.1)
        factor_type = criterion_config.get('factor_type', FactorType.POSITIVE)
        radius = criterion_config.get('radius', 500)
        decay = criterion_config.get('decay', DecayFunction.LINEAR)
        decay_constant = criterion_config.get('decay_constant', radius / 3)
        threshold = criterion_config.get('threshold')
        
        # Get count and distances from feature data
        # These should be populated by the SQL query
        count = feature_data.get('count', 0)
        avg_distance = feature_data.get('avg_distance', radius / 2)
        distances = feature_data.get('distances', [])
        
        if count == 0:
            return 0.0, {
                'count': 0,
                'raw_score': 0,
                'decay_factor': 0,
                'weighted_score': 0,
            }
        
        # Calculate decay-weighted score
        if distances:
            # Sum of individual decay-weighted contributions
            decay_scores = [
                BusinessScorer.calculate_decay(d, decay, radius, decay_constant, threshold)
                for d in distances
            ]
            raw_score = sum(decay_scores)
        else:
            # Fallback: use average distance with count
            decay_factor = BusinessScorer.calculate_decay(
                avg_distance, decay, radius, decay_constant, threshold
            )
            raw_score = count * decay_factor
        
        # Apply factor type
        if factor_type == FactorType.NEGATIVE:
            # Invert: high count = low score
            # Use inverse scoring for competition
            weighted_score = -raw_score * weight
        elif factor_type == FactorType.SYNERGY:
            # Synergy has diminishing returns
            weighted_score = math.log1p(raw_score) * weight
        else:
            weighted_score = raw_score * weight
        
        breakdown = {
            'count': count,
            'avg_distance': round(avg_distance, 1),
            'raw_score': round(raw_score, 4),
            'weight': weight,
            'factor_type': factor_type.value,
            'weighted_score': round(weighted_score, 4),
        }
        
        return weighted_score, breakdown

    @staticmethod
    def calculate_composite_score(
        feature: Dict[str, Any],
        business_type: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate composite suitability score for a feature.
        
        Args:
            feature: GeoJSON feature with properties
            business_type: Type of business being scored
            
        Returns:
            Tuple of (composite_score, score_breakdown)
        """
        profile = BusinessScorer.get_profile(business_type)
        criteria = profile.get('criteria', {})
        properties = feature.get('properties', {})
        
        total_score = 0.0
        positive_sum = 0.0
        negative_sum = 0.0
        breakdown = {}
        
        for criterion_name, config in criteria.items():
            # Extract criterion data from feature properties
            # Properties should contain: {criterion_name}_count, {criterion_name}_avg_distance
            criterion_data = {
                'count': properties.get(f'{criterion_name}_count', 0),
                'avg_distance': properties.get(f'{criterion_name}_avg_dist', config.get('radius', 500) / 2),
                'distances': properties.get(f'{criterion_name}_distances', []),
            }
            
            score, criterion_breakdown = BusinessScorer.calculate_criterion_score(
                criterion_data, config
            )
            
            total_score += score
            breakdown[criterion_name] = criterion_breakdown
            
            if config.get('factor_type') == FactorType.NEGATIVE:
                negative_sum += abs(score)
            else:
                positive_sum += score
        
        # Normalize composite score to 0-1 range
        # We use sigmoid-like normalization for interpretability
        normalized_score = 1 / (1 + math.exp(-total_score))
        
        return normalized_score, {
            'raw_total': round(total_score, 4),
            'positive_factors': round(positive_sum, 4),
            'negative_factors': round(negative_sum, 4),
            'normalized_score': round(normalized_score, 4),
            'business_type': business_type,
            'criteria_breakdown': breakdown,
        }

    @staticmethod
    def generate_scoring_sql(
        business_type: str,
        district_filter: str = None,
        limit: int = 20
    ) -> str:
        """
        Generate sophisticated scoring SQL for a business type.
        
        Args:
            business_type: Type of business
            district_filter: Optional district name filter
            limit: Max results to return
            
        Returns:
            SQL query string with scoring
        """
        profile = BusinessScorer.get_profile(business_type)
        criteria = profile.get('criteria', {})
        
        # Build subqueries for each criterion
        score_columns = []
        count_columns = []
        
        for criterion_name, config in criteria.items():
            tables = config.get('tables', [])
            radius = config.get('radius', 500)
            weight = config.get('weight', 0.1)
            factor_type = config.get('factor_type', FactorType.POSITIVE)
            decay = config.get('decay', DecayFunction.LINEAR)
            decay_constant = config.get('decay_constant', radius / 3)
            cuisine_filter = config.get('cuisine_filter')
            building_filter = config.get('filter')
            
            for table in tables:
                table_alias = table.replace('osm_', '')[:3]
                
                # Build WHERE clause for table filters
                where_conditions = [f"ST_DWithin(b.geom_25833, {table_alias}.geom_25833, {radius})"]
                
                if cuisine_filter and 'restaurant' in table:
                    # Handle OR patterns in cuisine filter
                    if '|' in cuisine_filter:
                        patterns = cuisine_filter.split('|')
                        cuisine_conds = [f"{table_alias}.cuisine ILIKE '{p}'" for p in patterns]
                        where_conditions.append(f"({' OR '.join(cuisine_conds)})")
                    else:
                        where_conditions.append(f"{table_alias}.cuisine ILIKE '{cuisine_filter}'")
                
                if building_filter and 'buildings' in table:
                    if building_filter == 'COMMERCIAL':
                        where_conditions.append(f"{table_alias}.building IN ('commercial', 'retail', 'office')")
                    elif building_filter == 'RESIDENTIAL':
                        where_conditions.append(f"{table_alias}.building IN ('residential')")
                    else:
                        where_conditions.append(f"'{building_filter}' = {table_alias}.building")
                
                where_clause = " AND ".join(where_conditions)
                
                # Generate decay function in SQL
                if decay == DecayFunction.EXPONENTIAL:
                    decay_sql = f"EXP(-ST_Distance(b.geom_25833, {table_alias}.geom_25833) / {decay_constant})"
                elif decay == DecayFunction.LINEAR:
                    decay_sql = f"GREATEST(0, 1 - ST_Distance(b.geom_25833, {table_alias}.geom_25833) / {radius})"
                elif decay == DecayFunction.INVERSE:
                    decay_sql = f"1.0 / (1 + ST_Distance(b.geom_25833, {table_alias}.geom_25833) / {decay_constant})"
                elif decay == DecayFunction.GAUSSIAN:
                    decay_sql = f"EXP(-POWER(ST_Distance(b.geom_25833, {table_alias}.geom_25833), 2) / (2 * POWER({decay_constant}, 2)))"
                else:
                    decay_sql = "1.0"
                
                # Score column with decay
                col_name = f"{criterion_name}_score"
                
                if factor_type == FactorType.NEGATIVE:
                    # Negative factor: subtract from score
                    score_columns.append(
                        f"-(SELECT COALESCE(SUM({decay_sql}), 0) * {weight} "
                        f"FROM vector.{table} {table_alias} WHERE {where_clause}) as {col_name}"
                    )
                else:
                    score_columns.append(
                        f"(SELECT COALESCE(SUM({decay_sql}), 0) * {weight} "
                        f"FROM vector.{table} {table_alias} WHERE {where_clause}) as {col_name}"
                    )
                
                # Also get raw count for display
                count_col_name = f"{criterion_name}_count"
                count_columns.append(
                    f"(SELECT COUNT(*) FROM vector.{table} {table_alias} "
                    f"WHERE {where_clause}) as {count_col_name}"
                )
        
        # Build final SQL
        all_columns = score_columns + count_columns
        score_names = [c.split(' as ')[-1] for c in score_columns]
        
        # District filter
        district_join = ""
        district_where = ""
        if district_filter:
            district_join = "JOIN vector.berlin_districts d ON ST_Intersects(b.geom_25833, d.geom_25833)"
            district_where = f"AND (d.bezirk ILIKE '%{district_filter}%' OR d.name ILIKE '%{district_filter}%')"
        
        sql = f"""
WITH scored AS (
    SELECT 
        b.uuid,
        b.nam as name,
        b.geometry,
        b.geom_25833,
        {', '.join(all_columns)}
    FROM vector.alkis_buildings b
    {district_join}
    WHERE b.building IN ('commercial', 'retail', 'office')
    {district_where}
)
SELECT
    uuid,
    name,
    geometry,
    {', '.join(score_names)},
    {', '.join([c.split(' as ')[-1] for c in count_columns])},
    ({' + '.join(score_names)}) as total_score,
    (1.0 / (1 + EXP(-({' + '.join(score_names)})))) as composite_score
FROM scored
WHERE ({' + '.join(score_names)}) IS NOT NULL
ORDER BY total_score DESC
LIMIT {limit}
        """.strip()
        
        return sql

    @staticmethod  
    def get_scoring_explanation(business_type: str) -> str:
        """
        Generate human-readable explanation of scoring criteria.
        
        Args:
            business_type: Type of business
            
        Returns:
            Explanation string
        """
        profile = BusinessScorer.get_profile(business_type)
        criteria = profile.get('criteria', {})
        
        lines = [f"**Scoring for {profile.get('description', business_type)}:**\n"]
        
        positive_factors = []
        negative_factors = []
        
        for name, config in criteria.items():
            weight = config.get('weight', 0)
            radius = config.get('radius', 500)
            factor_type = config.get('factor_type', FactorType.POSITIVE)
            tables = config.get('tables', [])
            
            description = f"- {name.replace('_', ' ').title()}: "
            description += f"weight={weight:.0%}, radius={radius}m, "
            description += f"tables={', '.join(tables)}"
            
            if factor_type == FactorType.NEGATIVE:
                negative_factors.append(description)
            else:
                positive_factors.append(description)
        
        if positive_factors:
            lines.append("**Positive Factors (higher = better):**")
            lines.extend(positive_factors)
            lines.append("")
        
        if negative_factors:
            lines.append("**Negative Factors (higher = worse):**")
            lines.extend(negative_factors)
        
        return "\n".join(lines)


# Convenience instance
business_scorer = BusinessScorer()
