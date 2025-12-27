"""
Semantic Layer for Cognitive Geospatial Assistant

This module provides RDF/OWL knowledge graph capabilities for geodata management.
It enables:
- Semantic modeling of geodata sources
- SPARQL queries over the knowledge graph
- SHACL validation for data quality
- Conversion of JSON catalogs to RDF

Aligned with GeoTrAnsQData research goals for geographic question answering.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass

import rdflib
from rdflib import Graph, Namespace, Literal, URIRef, BNode
from rdflib.namespace import RDF, RDFS, OWL, XSD, DCTERMS

logger = logging.getLogger(__name__)

# Define namespaces
GEO = Namespace("http://geoassist.ai/ontology#")
GEOSPARQL = Namespace("http://www.opengis.net/ont/geosparql#")
DCAT = Namespace("http://www.w3.org/ns/dcat#")
PROV = Namespace("http://www.w3.org/ns/prov#")
SCHEMA = Namespace("http://schema.org/")


@dataclass
class ValidationResult:
    """Result of SHACL validation."""
    conforms: bool
    violations: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    info: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "conforms": self.conforms,
            "violations": self.violations,
            "warnings": self.warnings,
            "info": self.info,
            "total_issues": len(self.violations) + len(self.warnings) + len(self.info)
        }


class SemanticLayer:
    """
    Manages the RDF knowledge graph for geodata.
    
    Provides methods for:
    - Loading and managing the ontology
    - Converting JSON catalogs to RDF
    - Executing SPARQL queries
    - Validating data with SHACL
    """
    
    def __init__(self, ontology_dir: Optional[str] = None):
        """
        Initialize the semantic layer.
        
        Args:
            ontology_dir: Path to directory containing ontology files.
                         Defaults to app/ontology.
        """
        self.graph = Graph()
        self.shapes_graph = Graph()
        
        # Set up namespaces
        self.graph.bind("geo", GEO)
        self.graph.bind("geosparql", GEOSPARQL)
        self.graph.bind("dcat", DCAT)
        self.graph.bind("dct", DCTERMS)
        self.graph.bind("prov", PROV)
        self.graph.bind("schema", SCHEMA)
        self.graph.bind("owl", OWL)
        
        # Determine ontology directory
        if ontology_dir:
            self.ontology_dir = Path(ontology_dir)
        else:
            # Default to app/ontology relative to this file
            self.ontology_dir = Path(__file__).parent.parent / "ontology"
        
        self._load_ontology()
        self._load_shapes()
        
        logger.info(f"Semantic layer initialized with {len(self.graph)} triples")
    
    def _load_ontology(self) -> None:
        """Load the OWL ontology from file."""
        ontology_file = self.ontology_dir / "geo_ontology.ttl"
        if ontology_file.exists():
            self.graph.parse(ontology_file, format="turtle")
            logger.info(f"Loaded ontology from {ontology_file}")
        else:
            logger.warning(f"Ontology file not found: {ontology_file}")
    
    def _load_shapes(self) -> None:
        """Load SHACL shapes from file."""
        shapes_file = self.ontology_dir / "shacl_shapes.ttl"
        if shapes_file.exists():
            self.shapes_graph.parse(shapes_file, format="turtle")
            logger.info(f"Loaded SHACL shapes from {shapes_file}")
        else:
            logger.warning(f"SHACL shapes file not found: {shapes_file}")
    
    def catalog_to_rdf(self, catalog_path: str) -> int:
        """
        Convert a JSON catalog to RDF triples.
        
        Args:
            catalog_path: Path to the JSON catalog file.
            
        Returns:
            Number of triples added.
        """
        initial_count = len(self.graph)
        
        with open(catalog_path, 'r') as f:
            catalog = json.load(f)
        
        # Handle different catalog formats
        if "datasets" in catalog:
            datasets = catalog["datasets"]
            
            # Handle nested format (catalog.json)
            if isinstance(datasets, dict):
                for category, items in datasets.items():
                    for item in items:
                        self._add_dataset_triples(item, category)
            # Handle flat format (berlin_osm_catalog.json)
            elif isinstance(datasets, list):
                for item in datasets:
                    category = item.get("category", "vector")
                    self._add_dataset_triples(item, category)
        
        added = len(self.graph) - initial_count
        logger.info(f"Added {added} triples from {catalog_path}")
        return added
    
    def _add_dataset_triples(self, dataset: Dict[str, Any], category: str) -> None:
        """Add triples for a single dataset."""
        dataset_id = dataset.get("id", dataset.get("name", "unknown"))
        dataset_uri = GEO[dataset_id.replace(" ", "_").replace("-", "_")]
        
        # Determine dataset type
        if category == "raster":
            self.graph.add((dataset_uri, RDF.type, GEO.RasterDataset))
        else:
            # Map category to specific class
            category_map = {
                "healthcare": GEO.HealthcareFacilityDataset,
                "emergency": GEO.EmergencyServiceDataset,
                "recreation": GEO.RecreationFacilityDataset,
                "transport": GEO.TransportDataset,
                "education": GEO.InfrastructureDataset,
                "infrastructure": GEO.InfrastructureDataset,
                "amenity": GEO.InfrastructureDataset,
                "food": GEO.InfrastructureDataset,
            }
            dataset_class = category_map.get(category, GEO.VectorDataset)
            self.graph.add((dataset_uri, RDF.type, dataset_class))
        
        # Add basic metadata
        if "name" in dataset:
            self.graph.add((dataset_uri, DCTERMS.title, Literal(dataset["name"], lang="en")))
        
        if "description" in dataset:
            self.graph.add((dataset_uri, DCTERMS.description, Literal(dataset["description"], lang="en")))
        
        if "source" in dataset:
            self.graph.add((dataset_uri, DCTERMS.source, Literal(dataset["source"])))
        
        # Add spatial properties
        if "crs" in dataset:
            self.graph.add((dataset_uri, GEO.hasCRS, Literal(dataset["crs"])))
        
        if "table" in dataset:
            self.graph.add((dataset_uri, GEO.hasTableName, Literal(dataset["table"])))
        elif "table_name" in dataset:
            self.graph.add((dataset_uri, GEO.hasTableName, Literal(dataset["table_name"])))
        
        if "file" in dataset:
            self.graph.add((dataset_uri, GEO.hasFilePath, Literal(dataset["file"])))
        elif "path" in dataset:
            self.graph.add((dataset_uri, GEO.hasFilePath, Literal(dataset["path"])))
        
        if "geometry_type" in dataset:
            self.graph.add((dataset_uri, GEO.hasGeometryType, Literal(dataset["geometry_type"])))
        elif "feature_type" in dataset:
            self.graph.add((dataset_uri, GEO.hasGeometryType, Literal(dataset["feature_type"])))
        
        # Add raster-specific properties
        if "resolution" in dataset:
            self.graph.add((dataset_uri, GEO.hasResolution, Literal(dataset["resolution"])))
        
        if "bands" in dataset:
            self.graph.add((dataset_uri, GEO.hasBandCount, Literal(dataset["bands"], datatype=XSD.integer)))
        
        # Add analytical purposes from use_cases
        if "use_cases" in dataset:
            for use_case in dataset["use_cases"]:
                purpose_uri = self._map_use_case_to_purpose(use_case)
                if purpose_uri:
                    self.graph.add((dataset_uri, GEO.hasAnalyticalPurpose, purpose_uri))
        
        # Add tags as keywords
        if "tags" in dataset:
            for tag in dataset["tags"]:
                self.graph.add((dataset_uri, DCAT.keyword, Literal(tag)))
    
    def _map_use_case_to_purpose(self, use_case: str) -> Optional[URIRef]:
        """Map a use case string to an analytical purpose URI."""
        use_case_lower = use_case.lower()
        
        mappings = {
            "accessibility": GEO.AccessibilityAnalysis,
            "emergency": GEO.EmergencyPlanning,
            "urban planning": GEO.UrbanPlanning,
            "environmental": GEO.EnvironmentalMonitoring,
            "change detection": GEO.ChangeDetection,
            "vegetation": GEO.EnvironmentalMonitoring,
            "proximity": GEO.ProximityAnalysis,
            "coverage": GEO.CoverageAnalysis,
            "distance": GEO.ProximityAnalysis,
        }
        
        for keyword, purpose in mappings.items():
            if keyword in use_case_lower:
                return purpose
        
        return None
    
    def query_sparql(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute a SPARQL query against the knowledge graph.
        
        Args:
            query: SPARQL query string.
            
        Returns:
            List of result dictionaries.
        """
        try:
            results = self.graph.query(query)
            
            # Convert results to list of dicts
            output = []
            for row in results:
                row_dict = {}
                for var in results.vars:
                    value = row[var]
                    if value is not None:
                        if isinstance(value, URIRef):
                            row_dict[str(var)] = str(value)
                        elif isinstance(value, Literal):
                            row_dict[str(var)] = value.toPython()
                        else:
                            row_dict[str(var)] = str(value)
                output.append(row_dict)
            
            return output
            
        except Exception as e:
            logger.error(f"SPARQL query error: {e}")
            raise ValueError(f"Invalid SPARQL query: {e}")
    
    def validate_data(self, data_graph: Optional[Graph] = None) -> ValidationResult:
        """
        Validate data against SHACL shapes.
        
        Args:
            data_graph: Graph to validate. If None, validates the main graph.
            
        Returns:
            ValidationResult with conformance status and issues.
        """
        try:
            from pyshacl import validate
        except ImportError:
            logger.error("pyshacl not installed")
            return ValidationResult(
                conforms=True,
                violations=[],
                warnings=[{"message": "pyshacl not installed, validation skipped"}],
                info=[]
            )
        
        if data_graph is None:
            data_graph = self.graph
        
        conforms, results_graph, results_text = validate(
            data_graph,
            shacl_graph=self.shapes_graph,
            inference='rdfs',
            abort_on_first=False,
            meta_shacl=False,
            advanced=True,
            debug=False
        )
        
        # Parse results
        violations = []
        warnings = []
        info = []
        
        # Query the results graph for validation results
        SH = Namespace("http://www.w3.org/ns/shacl#")
        
        for result in results_graph.subjects(RDF.type, SH.ValidationResult):
            severity = results_graph.value(result, SH.resultSeverity)
            message = results_graph.value(result, SH.resultMessage)
            focus = results_graph.value(result, SH.focusNode)
            path = results_graph.value(result, SH.resultPath)
            
            issue = {
                "focus": str(focus) if focus else None,
                "path": str(path) if path else None,
                "message": str(message) if message else "Validation issue"
            }
            
            if severity == SH.Violation:
                violations.append(issue)
            elif severity == SH.Warning:
                warnings.append(issue)
            else:
                info.append(issue)
        
        return ValidationResult(
            conforms=conforms,
            violations=violations,
            warnings=warnings,
            info=info
        )
    
    def get_datasets_by_purpose(self, purpose: str) -> List[Dict[str, str]]:
        """
        Find datasets that support a specific analytical purpose.
        
        Args:
            purpose: Name of the analytical purpose (e.g., "AccessibilityAnalysis")
            
        Returns:
            List of datasets with their titles.
        """
        purpose_uri = GEO[purpose]
        
        query = f"""
        PREFIX geo: <{GEO}>
        PREFIX dct: <{DCTERMS}>
        
        SELECT ?dataset ?title ?description
        WHERE {{
            ?dataset geo:hasAnalyticalPurpose <{purpose_uri}> .
            OPTIONAL {{ ?dataset dct:title ?title }}
            OPTIONAL {{ ?dataset dct:description ?description }}
        }}
        """
        
        return self.query_sparql(query)
    
    def get_related_datasets(self, dataset_id: str) -> List[Dict[str, str]]:
        """
        Find datasets related to a given dataset (same class or purpose).
        
        Args:
            dataset_id: ID of the dataset to find relations for.
            
        Returns:
            List of related datasets.
        """
        dataset_uri = GEO[dataset_id]
        
        query = f"""
        PREFIX geo: <{GEO}>
        PREFIX dct: <{DCTERMS}>
        PREFIX rdf: <{RDF}>
        
        SELECT DISTINCT ?related ?title ?relationship
        WHERE {{
            # Find datasets of the same type
            {{
                <{dataset_uri}> rdf:type ?type .
                ?related rdf:type ?type .
                ?related dct:title ?title .
                FILTER(?related != <{dataset_uri}>)
                BIND("same_type" AS ?relationship)
            }}
            UNION
            # Find datasets with same analytical purpose
            {{
                <{dataset_uri}> geo:hasAnalyticalPurpose ?purpose .
                ?related geo:hasAnalyticalPurpose ?purpose .
                ?related dct:title ?title .
                FILTER(?related != <{dataset_uri}>)
                BIND("same_purpose" AS ?relationship)
            }}
        }}
        """
        
        return self.query_sparql(query)
    
    def get_all_datasets(self) -> List[Dict[str, Any]]:
        """
        Get all datasets in the knowledge graph with their metadata.
        
        Returns:
            List of dataset dictionaries.
        """
        query = f"""
        PREFIX geo: <{GEO}>
        PREFIX dct: <{DCTERMS}>
        PREFIX rdf: <{RDF}>
        
        SELECT ?dataset ?title ?description ?type ?table ?crs
        WHERE {{
            ?dataset rdf:type ?type .
            FILTER(STRSTARTS(STR(?type), STR(geo:)))
            OPTIONAL {{ ?dataset dct:title ?title }}
            OPTIONAL {{ ?dataset dct:description ?description }}
            OPTIONAL {{ ?dataset geo:hasTableName ?table }}
            OPTIONAL {{ ?dataset geo:hasCRS ?crs }}
        }}
        ORDER BY ?title
        """
        
        return self.query_sparql(query)
    
    def export_graph(self, format: str = "turtle") -> str:
        """
        Export the knowledge graph in a specified format.
        
        Args:
            format: Output format (turtle, xml, json-ld, n3)
            
        Returns:
            Serialized graph as string.
        """
        return self.graph.serialize(format=format)
    
    def get_statistics(self) -> Dict[str, int]:
        """
        Get statistics about the knowledge graph.
        
        Returns:
            Dictionary with counts of various elements.
        """
        stats = {
            "total_triples": len(self.graph),
            "datasets": 0,
            "vector_datasets": 0,
            "raster_datasets": 0,
            "analytical_purposes": 0,
            "spatial_capabilities": 0,
        }
        
        # Count datasets
        for _ in self.graph.subjects(RDF.type, GEO.GeoDataset):
            stats["datasets"] += 1
        for _ in self.graph.subjects(RDF.type, GEO.VectorDataset):
            stats["vector_datasets"] += 1
        for _ in self.graph.subjects(RDF.type, GEO.RasterDataset):
            stats["raster_datasets"] += 1
        
        # Also count subclasses
        for subclass in [GEO.HealthcareFacilityDataset, GEO.RecreationFacilityDataset, 
                         GEO.InfrastructureDataset, GEO.TransportDataset,
                         GEO.EmergencyServiceDataset, GEO.AdministrativeDataset,
                         GEO.EnvironmentalDataset, GEO.VegetationIndexDataset]:
            for _ in self.graph.subjects(RDF.type, subclass):
                stats["datasets"] += 1
                if subclass == GEO.VegetationIndexDataset:
                    stats["raster_datasets"] += 1
                else:
                    stats["vector_datasets"] += 1
        
        return stats


# Convenience function for quick access
def create_semantic_layer(ontology_dir: Optional[str] = None) -> SemanticLayer:
    """Create and return a SemanticLayer instance."""
    return SemanticLayer(ontology_dir)
