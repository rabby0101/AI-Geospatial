"""
Operation Chain Management for Multi-Step Geospatial Reasoning

Handles dependency tracking, topological sorting, and intermediate result caching
for complex multi-step geospatial operations.
"""

from typing import Dict, List, Any, Optional, Set
from app.models.query_model import OperationPlan, GeospatialOperation
import geopandas as gpd
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class OperationChain:
    """Manages execution of chained geospatial operations with dependencies"""

    def __init__(self):
        """Initialize operation chain manager"""
        self.intermediate_results: Dict[str, Any] = {}
        self.execution_log: List[Dict[str, Any]] = []

    def validate_plan(self, plan: OperationPlan) -> tuple[bool, str]:
        """
        Validate operation plan for circular dependencies and missing references.

        Args:
            plan: OperationPlan to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check for circular dependencies
        if not self._check_circular_dependencies(plan.operations):
            return False, "Circular dependency detected in operation plan"

        # Check all dependencies reference existing result_keys
        available_keys = set()
        for op in plan.operations:
            if op.result_key:
                available_keys.add(op.result_key)

            # Check that all dependencies reference available keys
            for dep in op.dependencies:
                if dep not in available_keys:
                    return False, f"Operation depends on undefined result: {dep}"

        return True, ""

    def _check_circular_dependencies(self, operations: List[GeospatialOperation]) -> bool:
        """
        Check for circular dependencies using DFS.

        Args:
            operations: List of operations to check

        Returns:
            True if no circular dependencies found
        """
        # Build adjacency graph
        graph: Dict[str, List[str]] = {}
        op_by_key: Dict[str, GeospatialOperation] = {}

        for op in operations:
            if op.result_key:
                graph[op.result_key] = op.dependencies
                op_by_key[op.result_key] = op

        # DFS to detect cycles
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            if node in graph:
                for neighbor in graph[node]:
                    if neighbor not in visited:
                        if has_cycle(neighbor):
                            return True
                    elif neighbor in rec_stack:
                        return True

            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                if has_cycle(node):
                    return False

        return True

    def get_execution_order(self, operations: List[GeospatialOperation]) -> List[GeospatialOperation]:
        """
        Get topologically sorted execution order of operations.

        Args:
            operations: List of operations to sort

        Returns:
            Topologically sorted list of operations
        """
        # Build graph of dependencies
        op_by_key: Dict[str, GeospatialOperation] = {}
        for op in operations:
            if op.result_key:
                op_by_key[op.result_key] = op

        # Topological sort using Kahn's algorithm
        in_degree: Dict[str, int] = {}
        graph: Dict[str, List[str]] = {}

        # Initialize
        for op in operations:
            key = op.result_key or f"op_{id(op)}"
            in_degree[key] = len(op.dependencies)
            graph[key] = []

        # Build graph
        for op in operations:
            key = op.result_key or f"op_{id(op)}"
            for dep in op.dependencies:
                if dep in op_by_key:
                    graph[dep].append(key)

        # Find nodes with no incoming edges
        queue = [k for k, v in in_degree.items() if v == 0]
        result = []

        while queue:
            node = queue.pop(0)
            # Find operation for this node
            for op in operations:
                op_key = op.result_key or f"op_{id(op)}"
                if op_key == node:
                    result.append(op)
                    break

            # Reduce in-degree for neighbors
            for neighbor in graph.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result if len(result) == len(operations) else operations

    def substitute_parameters(
        self,
        operation: GeospatialOperation,
        intermediate_results: Dict[str, Any]
    ) -> GeospatialOperation:
        """
        Substitute parameter placeholders with actual intermediate results.

        Supports referencing previous results:
        - In SQL: "SELECT * FROM $parks_result" becomes subquery with actual geometry
        - In geometry: {"geometry": "$parks_buffer"} becomes actual geometry

        Args:
            operation: Operation with parameter placeholders
            intermediate_results: Dictionary of available intermediate results

        Returns:
            Operation with substituted parameters
        """
        import copy
        op_copy = copy.deepcopy(operation)

        for param_name, param_value in op_copy.parameters.items():
            if isinstance(param_value, str):
                # Check if parameter contains reference to intermediate result
                for result_key, result_value in intermediate_results.items():
                    # Support multiple reference syntaxes
                    placeholders = [
                        f"${result_key}",
                        f"{{{result_key}}}",
                        f":{result_key}",
                    ]

                    for placeholder in placeholders:
                        if placeholder in param_value:
                            # If referencing a GeoDataFrame/DataFrame, convert to SQL representation
                            if isinstance(result_value, (gpd.GeoDataFrame, pd.DataFrame)):
                                if "sql" in param_name.lower() or ".sql" in param_value.lower():
                                    # For SQL parameters, use CTE or subquery approach
                                    # Store as special marker that spatial_engine will handle
                                    op_copy.parameters[param_name] = param_value.replace(
                                        placeholder,
                                        f"(SELECT * FROM {result_key})"  # Placeholder CTE name
                                    )
                                    # Also store dataframe reference
                                    op_copy.parameters[f"__{result_key}_df__"] = result_value
                                else:
                                    # For non-SQL parameters, store dataframe reference
                                    op_copy.parameters[param_name] = {
                                        "__dataframe_ref__": result_key,
                                        "original_param": param_value
                                    }
                            else:
                                # Replace text reference
                                op_copy.parameters[param_name] = param_value.replace(
                                    placeholder,
                                    str(result_value)
                                )

        return op_copy

    def store_result(self, result_key: str, result: Any) -> None:
        """
        Store an intermediate result for use by downstream operations.

        Args:
            result_key: Key to store result under
            result: The result to store (GeoDataFrame, DataFrame, etc.)
        """
        self.intermediate_results[result_key] = result
        logger.info(f"Stored intermediate result: {result_key}")

    def get_result(self, result_key: str) -> Optional[Any]:
        """
        Retrieve a stored intermediate result.

        Args:
            result_key: Key to retrieve

        Returns:
            The stored result or None if not found
        """
        return self.intermediate_results.get(result_key)

    def log_execution(self, operation: GeospatialOperation, result: Any, duration: float) -> None:
        """
        Log operation execution details.

        Args:
            operation: The operation that was executed
            result: The result produced
            duration: Execution time in seconds
        """
        log_entry = {
            "operation": operation.operation.value,
            "result_key": operation.result_key,
            "description": operation.description,
            "duration_seconds": duration,
            "result_type": type(result).__name__,
        }

        # Add result size info if available
        if isinstance(result, (gpd.GeoDataFrame, pd.DataFrame)):
            log_entry["result_rows"] = len(result)
            log_entry["result_columns"] = list(result.columns)

        self.execution_log.append(log_entry)
        logger.debug(f"Execution log entry: {log_entry}")

    def get_execution_log(self) -> List[Dict[str, Any]]:
        """
        Get the complete execution log for this chain.

        Returns:
            List of execution log entries
        """
        return self.execution_log

    def clear(self) -> None:
        """Clear intermediate results and execution log."""
        self.intermediate_results.clear()
        self.execution_log.clear()
        logger.info("Cleared operation chain")


# Global instance
operation_chain = OperationChain()
