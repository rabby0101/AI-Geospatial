"""
Density Scorer - Calculate normalized scores and composite suitability index
Implements min-max scaling and weighted aggregation for multi-criteria analysis
"""

from typing import Dict, List, Any, Tuple
import statistics


class DensityScorer:
    """Calculate and normalize density scores for multi-criteria analysis"""

    @staticmethod
    def calculate_composite_scores(
        features: List[Dict[str, Any]],
        weights: Dict[str, float],
        criteria_tables: List[str]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Calculate normalized scores and composite suitability index.

        Args:
            features: List of district features with density data
            weights: {table_name: weight} mapping
            criteria_tables: List of available table names

        Returns:
            Tuple of:
            - Updated features with scores added
            - Scoring statistics and ranges
        """
        if not features or not criteria_tables:
            return features, {}

        # Extract density values for each criterion
        criterion_densities = {}
        for table in criteria_tables:
            # Find corresponding density field name
            field_name = f"{table.replace('osm_', '')}_density"

            densities = []
            for feature in features:
                props = feature.get('properties', {})
                density = props.get(field_name, 0)
                if isinstance(density, (int, float)) and density >= 0:
                    densities.append(density)

            criterion_densities[table] = {
                'densities': densities,
                'field_name': field_name,
                'min': min(densities) if densities else 0,
                'max': max(densities) if densities else 0,
                'avg': statistics.mean(densities) if densities else 0,
            }

        # Normalize and calculate composite scores
        updated_features = []
        composite_scores = []

        for feature in features:
            props = feature.get('properties', {})

            # Calculate normalized scores for each criterion
            criterion_scores = {}
            weighted_sum = 0
            weights_sum = 0

            for table, weight in weights.items():
                if table not in criterion_densities:
                    continue

                field_name = criterion_densities[table]['field_name']
                density = props.get(field_name, 0)

                # Normalize using min-max scaling: (x - min) / (max - min)
                criterion_range = criterion_densities[table]
                density_min = criterion_range['min']
                density_max = criterion_range['max']

                if density_max == density_min:
                    # All values are the same, normalize to 0.5
                    normalized = 0.5
                else:
                    normalized = (density - density_min) / (density_max - density_min)

                # Clamp to [0, 1]
                normalized = max(0, min(1, normalized))

                criterion_scores[table] = {
                    'field_name': field_name,
                    'density': round(density, 4),
                    'normalized_score': round(normalized, 4),
                    'weighted_contribution': round(normalized * weight, 4)
                }

                weighted_sum += normalized * weight
                weights_sum += weight

            # Calculate composite score
            if weights_sum > 0:
                composite_score = weighted_sum / weights_sum
            else:
                composite_score = 0

            composite_score = round(composite_score, 4)
            composite_scores.append(composite_score)

            # Add scores to feature properties
            props['composite_score'] = composite_score
            props['criterion_scores'] = criterion_scores
            props['weights_used'] = {table: round(w, 4) for table, w in weights.items()}
            props['included_criteria'] = list(weights.keys())
            props['excluded_criteria'] = []  # Will be filled by caller if needed

            # Create score breakdown for visualization
            score_breakdown = {}
            for table, scores in criterion_scores.items():
                criterion_name = table.replace('osm_', '').replace('_', ' ')
                score_breakdown[criterion_name] = {
                    'density': scores['density'],
                    'normalized': scores['normalized_score'],
                    'weight': round(weights.get(table, 0), 4),
                    'contribution': scores['weighted_contribution']
                }

            props['score_breakdown'] = score_breakdown

            feature['properties'] = props
            updated_features.append(feature)

        # Sort by composite score descending
        updated_features.sort(
            key=lambda f: f.get('properties', {}).get('composite_score', 0),
            reverse=True
        )

        # Calculate statistics
        stats = DensityScorer._calculate_statistics(
            composite_scores,
            criterion_densities,
            weights
        )

        return updated_features, stats

    @staticmethod
    def _calculate_statistics(
        composite_scores: List[float],
        criterion_densities: Dict[str, Dict[str, Any]],
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Generate statistics about the scoring"""
        if not composite_scores:
            return {}

        return {
            'composite_score_range': {
                'min': round(min(composite_scores), 4),
                'max': round(max(composite_scores), 4),
                'mean': round(statistics.mean(composite_scores), 4),
                'median': round(statistics.median(composite_scores), 4),
                'stdev': round(statistics.stdev(composite_scores), 4) if len(composite_scores) > 1 else 0,
            },
            'criterion_ranges': {
                table: {
                    'density_range': {
                        'min': round(data['min'], 4),
                        'max': round(data['max'], 4),
                        'mean': round(data['avg'], 4),
                    },
                    'weight': round(weights.get(table, 0), 4),
                    'field_name': data['field_name']
                }
                for table, data in criterion_densities.items()
            },
            'total_districts_analyzed': len(composite_scores)
        }

    @staticmethod
    def get_ranking_tier(composite_score: float) -> str:
        """
        Get human-readable ranking tier for a composite score.

        Args:
            composite_score: Score between 0 and 1

        Returns:
            Ranking tier string
        """
        if composite_score >= 0.8:
            return "🟢 Excellent"
        elif composite_score >= 0.6:
            return "🟡 Good"
        elif composite_score >= 0.4:
            return "🟠 Fair"
        elif composite_score >= 0.2:
            return "🔴 Poor"
        else:
            return "⚫ Very Poor"

    @staticmethod
    def format_score_breakdown_for_display(
        score_breakdown: Dict[str, Any]
    ) -> str:
        """
        Format score breakdown as human-readable text.

        Args:
            score_breakdown: Score breakdown from properties

        Returns:
            Formatted string for display
        """
        lines = []

        for criterion, scores in score_breakdown.items():
            density = scores.get('density', 'N/A')
            normalized = scores.get('normalized', 'N/A')
            weight = scores.get('weight', 'N/A')
            contribution = scores.get('contribution', 'N/A')

            lines.append(
                f"  • {criterion.title()}: "
                f"density={density}, normalized={normalized}, "
                f"weight={weight}, contribution={contribution}"
            )

        return "\n".join(lines)
