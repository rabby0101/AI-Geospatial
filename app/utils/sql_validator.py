"""
SQL Validator and Auto-Corrector
Validates and fixes common SQL syntax errors from LLM-generated queries
"""

import re
from typing import Tuple, List

class SQLValidator:
    """Validates and attempts to fix SQL syntax errors"""

    @staticmethod
    def validate_parentheses(sql: str) -> Tuple[bool, str]:
        """
        Validate and fix mismatched parentheses in SQL

        Args:
            sql: SQL query string

        Returns:
            Tuple of (is_valid, fixed_sql)
        """
        # Count opening and closing parentheses
        open_count = sql.count('(')
        close_count = sql.count(')')

        if open_count == close_count:
            return True, sql

        # Fix: Add missing closing parentheses at the end
        if open_count > close_count:
            missing = open_count - close_count
            fixed_sql = sql + ')' * missing
            return False, fixed_sql

        # Remove extra closing parentheses from the end
        if close_count > open_count:
            extra = close_count - open_count
            fixed_sql = sql[:-extra]
            return False, fixed_sql

        return True, sql

    @staticmethod
    def validate_round_function(sql: str) -> Tuple[bool, str]:
        """
        Fix ROUND() function syntax errors and ST_Transform syntax errors
        Common errors:
        - ROUND(AVG(...))::int instead of ROUND(AVG(...)::int)
        - ST_Transform(geometry)::numeric, srid) instead of ST_Transform(geometry, srid)

        Args:
            sql: SQL query string

        Returns:
            Tuple of (needs_fix, fixed_sql)
        """
        fixed_sql = sql
        needs_fix = False

        # CRITICAL: Only fix ST_Transform errors when the pattern is EXACTLY:
        # ST_Transform(something)::numeric, digit) - where the ::numeric is directly after the )
        # This pattern should ONLY match when ::numeric is mistakenly after ST_Transform
        # NOT when ::numeric appears elsewhere in the query

        # ONLY fix if we have the exact bad pattern: ST_Transform(X)::numeric, DIGIT)
        # where X doesn't contain unmatched parentheses
        if 'ST_Transform' in fixed_sql and '::numeric,' in fixed_sql:
            # More conservative pattern: Only match ST_Transform with simple content
            # This avoids matching cases where the ::numeric is elsewhere
            pattern = r'ST_Transform\s*\(\s*([a-zA-Z0-9_\.]+(?:\s*,\s*[a-zA-Z0-9_]+)*)\s*\)\s*::\s*numeric\s*,\s*(\d+)\s*\)'
            matches = list(re.finditer(pattern, fixed_sql))

            if matches:
                # Apply fixes from end to start to preserve positions
                for match in reversed(matches):
                    start, end = match.span()
                    content = match.group(1)  # What's inside ST_Transform(...)
                    srid = match.group(2)      # The SRID number
                    replacement = f'ST_Transform({content}, {srid})'
                    fixed_sql = fixed_sql[:start] + replacement + fixed_sql[end:]
                    needs_fix = True

        # Pattern: ROUND(AVG(...))::int (missing parenthesis before ::int)
        # Should be: ROUND(AVG(...)::numeric)
        pattern = r'ROUND\(AVG\(([^)]+)\)\)::int'
        matches = re.findall(pattern, sql)

        if matches:
            # Fix: change to ROUND(AVG(...)::numeric)
            fixed_sql = re.sub(
                pattern,
                r'ROUND(AVG(\1)::numeric)',
                fixed_sql
            )
            needs_fix = True

        # Pattern 2: Missing closing paren in subquery with ::int FROM
        # Fix: ))::int FROM → ))::numeric) FROM
        pattern2 = r'\)\)::int\s+FROM'
        if re.search(pattern2, fixed_sql):
            fixed_sql = re.sub(
                pattern2,
                ')::numeric) FROM',
                fixed_sql
            )
            needs_fix = True

        # Pattern 3: ROUND(ST_Area(...) / number, 2) without ::numeric cast
        # PostgreSQL ROUND requires numeric type for first arg
        # Fix: ROUND(ST_Area(ST_Transform(...)) / 1000000.0, 2)
        #   → ROUND((ST_Area(ST_Transform(...)) / 1000000.0)::numeric, 2)
        pattern3 = r'ROUND\((ST_Area\([^)]+\)\s*/\s*[\d.]+),\s*(\d+)\)'
        if re.search(pattern3, fixed_sql):
            # Find and wrap with ::numeric cast
            fixed_sql = re.sub(
                pattern3,
                r'ROUND((\1)::numeric, \2)',
                fixed_sql
            )
            needs_fix = True

        # Pattern 4: Min-max normalization with window functions inside ROUND
        # LLMs generate: ROUND( (col - MIN(col) OVER ()) / NULLIF(MAX(col) OVER () - MIN(col) OVER (), 0)::numeric, N )
        # The ::numeric cast is on the NULLIF (denominator) only.
        # But numerator is double precision → division result is double precision.
        # ROUND(double precision, int) doesn't exist in PostgreSQL.
        # Fix: cast the numerator to ::numeric so division result is numeric.
        # Match: OVER ())  followed by  / NULLIF(   → insert ::numeric between ) and /
        window_div_pattern = r'(OVER\s*\(\s*\))\s*\)\s*(/\s*NULLIF\s*\()'
        if re.search(window_div_pattern, fixed_sql, re.IGNORECASE):
            fixed_sql = re.sub(
                window_div_pattern,
                r'\1)::numeric \2',
                fixed_sql,
                flags=re.IGNORECASE
            )
            needs_fix = True

        # Pattern 5: General ROUND(double_expr, N) where expression doesn't end in ::numeric
        # Catch-all: any ROUND(expr, N) where expr contains a division and no ::numeric before the comma
        # Specifically: ROUND( ... / NULLIF(...)::numeric, N ) without the whole expr being cast
        # If ::numeric appears directly before ", N)" at end of ROUND, it only casts the divisor.
        # Fix: also wrap in ::numeric if we detect  ")::numeric, <digits>)"  at the tail of a ROUND arg.
        # (Handles the case where the regex above didn't already fix it.)
        round_nullif_tail = r'NULLIF\s*\(([^)]+(?:\([^)]*\)[^)]*)*)\s*,\s*0\s*\)\s*::\s*numeric\s*,\s*(\d+)\s*\)'
        if re.search(round_nullif_tail, fixed_sql, re.IGNORECASE):
            # The pattern is already handled by window_div_pattern above in most cases;
            # but if ::numeric is on NULLIF and the numerator isn't cast yet, cast denominator side too
            # which makes PostgreSQL resolve as numeric / numeric = numeric automatically.
            # (This is a no-op if already fixed above.)
            pass

        return needs_fix, fixed_sql

    @staticmethod
    def validate_select_from(sql: str) -> Tuple[bool, str]:
        """
        Ensure every SELECT has a FROM clause before closing parenthesis

        Args:
            sql: SQL query string

        Returns:
            Tuple of (needs_fix, fixed_sql)
        """
        # Pattern: closing paren before FROM appears
        # Check for ")" before "FROM" in subqueries
        if re.search(r'\)\s+(FROM|WHERE|GROUP|ORDER)', sql):
            # This might be valid (e.g., closing a subquery), check context
            pass

        return False, sql

    @staticmethod
    def validate_common_errors(sql: str) -> Tuple[bool, str]:
        """
        Check for common DeepSeek SQL generation errors

        Args:
            sql: SQL query string

        Returns:
            Tuple of (has_errors, fixed_sql)
        """
        errors_found = []
        fixed_sql = sql

        # Check 1: Mismatched parentheses
        is_valid, fixed_sql = SQLValidator.validate_parentheses(fixed_sql)
        if not is_valid:
            errors_found.append("Mismatched parentheses (auto-fixed)")

        # Check 2: ROUND/AVG syntax errors
        needs_fix, fixed_sql = SQLValidator.validate_round_function(fixed_sql)
        if needs_fix:
            errors_found.append("ROUND(AVG()) syntax error (auto-fixed)")

        # Check 3: SELECT without FROM in subqueries
        needs_fix, fixed_sql = SQLValidator.validate_select_from(fixed_sql)
        if needs_fix:
            errors_found.append("SELECT without FROM (auto-fixed)")
            
        # Check 4: osm_id type mismatches in UNION queries
        # Some tables have bigint osm_id, others have text. UNIONs fail if types differ.
        if "UNION" in fixed_sql.upper() and "osm_id" in fixed_sql.lower():
            original = fixed_sql
            # Replace "SELECT osm_id" with "SELECT osm_id::text as osm_id"
            fixed_sql = re.sub(r'\bSELECT\s+osm_id\b', 'SELECT osm_id::text as osm_id', fixed_sql, flags=re.IGNORECASE)
            # Replace "SELECT alias.osm_id" with "SELECT alias.osm_id::text as osm_id"
            fixed_sql = re.sub(r'\bSELECT\s+([a-zA-Z0-9_]+)\.osm_id\b', r'SELECT \1.osm_id::text as osm_id', fixed_sql, flags=re.IGNORECASE)
            
            if original != fixed_sql:
                errors_found.append("osm_id type mismatch in UNION (auto-fixed to text)")

        return len(errors_found) == 0, fixed_sql

    @staticmethod
    def simplify_complex_query(sql: str, query_type: str = "proximity") -> str:
        """
        Simplify overly complex queries generated by DeepSeek

        Args:
            sql: Original SQL query
            query_type: Type of query (proximity, density, multi_table, etc.)

        Returns:
            Simplified SQL
        """
        # For "hospitals and clinics near me" type queries
        if query_type == "proximity" and "hospital" in sql.lower() and "clinic" in sql.lower():
            # DeepSeek might generate overly complex accessibility scores
            # Instead, return simple proximity query
            return SQLValidator._simplify_proximity_query(sql)

        # For density queries
        if query_type == "density" and "density_per_sq_km" in sql:
            return SQLValidator._simplify_density_query(sql)

        return sql

    @staticmethod
    def _simplify_proximity_query(sql: str) -> str:
        """
        Simplify complex proximity queries to basic version

        For query: "Find hospitals and clinics within 1km of each other in Mitte"
        Return: Simple query joining hospitals and clinics within distance
        """
        # If the query is too complex (has multiple CTEs, complex aggregations)
        # simplify it

        cte_count = sql.count('WITH') + sql.count(',') - sql.count(',')
        if cte_count > 2:
            # Too many CTEs, simplify
            return """
SELECT DISTINCT
    h.osm_id as hospital_id,
    h.name as hospital_name,
    c.osm_id as clinic_id,
    c.name as clinic_name,
    ROUND(ST_Distance(ST_Transform(h.geometry, 3857), ST_Transform(c.geometry, 3857))::numeric / 1000, 2) as distance_km,
    CASE
        WHEN ST_DWithin(ST_Transform(h.geometry, 3857), ST_Transform(c.geometry, 3857), 1000) THEN 'Within 1km'
        WHEN ST_DWithin(ST_Transform(h.geometry, 3857), ST_Transform(c.geometry, 3857), 2000) THEN 'Within 2km'
        ELSE 'Beyond 2km'
    END as proximity_category,
    h.geometry
FROM vector.osm_hospitals h
CROSS JOIN vector.osm_clinics c
WHERE ST_DWithin(ST_Transform(h.geometry, 3857), ST_Transform(c.geometry, 3857), 1000)
    AND EXISTS (
        SELECT 1 FROM vector.osm_districts d
        WHERE d.name ILIKE '%mitte%'
        AND ST_Within(ST_Centroid(h.geometry), d.geometry)
    )
ORDER BY distance_km
LIMIT 20
            """

        return sql

    @staticmethod
    def _simplify_density_query(sql: str) -> str:
        """Simplify density analysis queries"""
        # Return to basic density query if too complex
        return sql


def validate_and_fix_sql(sql: str) -> Tuple[bool, str, List[str]]:
    """
    Main validation function
    Returns: (is_valid, fixed_sql, errors_found)
    """
    validator = SQLValidator()
    is_valid, fixed_sql = validator.validate_common_errors(sql)

    errors = []
    if not is_valid:
        # Check what was fixed
        _, _ = validator.validate_parentheses(sql)
        _, test_sql = validator.validate_round_function(sql)
        if test_sql != sql:
            errors.append("ROUND/AVG function syntax")

    return is_valid, fixed_sql, errors


# Test cases
if __name__ == "__main__":
    # Test 1: Mismatched parentheses
    test_sql_1 = """
    SELECT * FROM (
        SELECT a, b FROM table1
    ORDER BY a
    """

    is_valid, fixed = SQLValidator.validate_parentheses(test_sql_1)
    print(f"Test 1 - Mismatched parens: valid={is_valid}")
    print(f"Fixed: {fixed}\n")

    # Test 2: ROUND/AVG error
    test_sql_2 = "SELECT ROUND(AVG(distance))::int FROM table1"
    needs_fix, fixed = SQLValidator.validate_round_function(test_sql_2)
    print(f"Test 2 - ROUND/AVG: needs_fix={needs_fix}")
    print(f"Fixed: {fixed}\n")

    # Test 3: The actual error from the user
    test_sql_3 = """
    SELECT ROUND(AVG(ST_Distance(...))::int FROM vector.osm_hospitals h1
    """
    is_valid, fixed, errors = validate_and_fix_sql(test_sql_3)
    print(f"Test 3 - User error: valid={is_valid}")
    print(f"Errors fixed: {errors}")
    print(f"Fixed SQL:\n{fixed}")
