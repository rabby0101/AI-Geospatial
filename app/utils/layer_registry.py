"""
Layer Registry - Manages active layers in a session for multistep queries.
Maintains in-memory cache of generated layers that can be referenced in follow-up queries.
"""

import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from geopandas import GeoDataFrame
import logging

logger = logging.getLogger(__name__)


class Layer:
    """Represents a generated query result layer"""

    def __init__(
        self,
        name: str,
        geojson: Dict[str, Any],
        feature_count: int,
        geometry_type: Optional[str] = None,
        parent_layer_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.id = f"{name.lower().replace(' ', '_')}_{str(uuid.uuid4())[:8]}"
        self.name = name
        self.geojson = geojson
        self.feature_count = feature_count
        self.geometry_type = geometry_type
        self.parent_layer_ids = parent_layer_ids or []
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "layer_id": self.id,
            "layer_name": self.name,
            "feature_count": self.feature_count,
            "geometry_type": self.geometry_type,
            "created_at": self.created_at,
            "parent_layer_ids": self.parent_layer_ids,
            "metadata": self.metadata
        }


class LayerRegistry:
    """
    Session-based registry for managing multiple layers.
    Enables multistep queries where results from one step feed into another.
    """

    def __init__(self, max_layers: int = 50):
        self.layers: Dict[str, Layer] = {}  # layer_id -> Layer
        self.max_layers = max_layers

    def add_layer(
        self,
        name: str,
        geojson: Dict[str, Any],
        feature_count: int,
        geometry_type: Optional[str] = None,
        parent_layer_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Layer:
        """
        Add a new layer to the registry.

        Args:
            name: Human-readable layer name
            geojson: GeoJSON FeatureCollection
            feature_count: Number of features in the layer
            geometry_type: Type of geometry (Point, Polygon, etc.)
            parent_layer_ids: IDs of layers this one depends on
            metadata: Additional metadata (area, count, etc.)

        Returns:
            Layer object with generated ID
        """
        # Evict oldest layer if at capacity
        if len(self.layers) >= self.max_layers:
            oldest_id = min(self.layers.keys(),
                          key=lambda k: self.layers[k].created_at)
            logger.info(f"Evicting oldest layer {oldest_id} to stay under max capacity")
            del self.layers[oldest_id]

        layer = Layer(
            name=name,
            geojson=geojson,
            feature_count=feature_count,
            geometry_type=geometry_type,
            parent_layer_ids=parent_layer_ids,
            metadata=metadata
        )

        self.layers[layer.id] = layer
        logger.info(f"Added layer '{name}' with ID {layer.id} ({feature_count} features)")
        return layer

    def get_layer(self, layer_id: str) -> Optional[Layer]:
        """Get a specific layer by ID"""
        return self.layers.get(layer_id)

    def get_layer_by_name(self, name: str) -> Optional[Layer]:
        """Get a layer by name (returns first match)"""
        for layer in self.layers.values():
            if layer.name.lower() == name.lower():
                return layer
        return None

    def list_layers(self) -> List[Dict[str, Any]]:
        """List all active layers with metadata"""
        return [layer.to_dict() for layer in self.layers.values()]

    def get_layers_for_prompt(self) -> str:
        """
        Generate a text summary of available layers for inclusion in LLM prompt.
        Used to help the LLM understand what previous results can be referenced.

        Returns:
            Formatted string listing available layers
        """
        if not self.layers:
            return ""

        lines = ["**Available Reference Layers:**", ""]
        for layer in self.layers.values():
            lines.append(f"- @{layer.name}: {layer.feature_count} features")
            if layer.parent_layer_ids:
                parent_names = ", ".join(
                    [self.layers[pid].name for pid in layer.parent_layer_ids
                     if pid in self.layers]
                )
                lines.append(f"  (Derived from: {parent_names})")

        return "\n".join(lines)

    def remove_layer(self, layer_id: str) -> bool:
        """Remove a layer from the registry"""
        if layer_id in self.layers:
            del self.layers[layer_id]
            logger.info(f"Removed layer {layer_id}")
            return True
        return False

    def clear(self):
        """Clear all layers from the registry"""
        self.layers.clear()
        logger.info("Cleared all layers from registry")

    def get_layer_geojson(self, layer_id: str) -> Optional[Dict[str, Any]]:
        """Get the GeoJSON for a specific layer"""
        layer = self.layers.get(layer_id)
        if layer:
            return layer.geojson
        return None

    def resolve_layer_reference(self, reference: str) -> Optional[Layer]:
        """
        Resolve a layer reference (e.g., "@hospitals") to actual layer.

        Args:
            reference: Layer reference string (with or without @ prefix)

        Returns:
            Layer object if found, None otherwise
        """
        # Remove @ prefix if present
        name = reference.lstrip("@").strip()
        return self.get_layer_by_name(name)


# Global session-based registry
_global_registry = LayerRegistry()


def get_layer_registry() -> LayerRegistry:
    """Get the global layer registry for the session"""
    return _global_registry


def reset_layer_registry():
    """Clear the global registry (for testing or session reset)"""
    _global_registry.clear()
