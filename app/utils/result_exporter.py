"""
Result Export Module

Provides functionality to export query results to various formats:
- CSV (tabular data)
- Shapefile (vector geometries)
- GeoJSON (web-friendly format)
- Excel (tabular with formatting)
"""

import os
import tempfile
import logging
from typing import Dict, Any, Optional, BinaryIO, Tuple
from pathlib import Path
import geopandas as gpd
import pandas as pd
from io import BytesIO, StringIO

logger = logging.getLogger(__name__)


class ResultExporter:
    """Export query results to various formats"""

    # Maximum file sizes (bytes)
    MAX_CSV_SIZE = 50 * 1024 * 1024      # 50 MB
    MAX_SHAPEFILE_SIZE = 100 * 1024 * 1024  # 100 MB

    @staticmethod
    def geojson_to_geodataframe(geojson_data: Dict[str, Any]) -> gpd.GeoDataFrame:
        """
        Convert GeoJSON to GeoDataFrame.

        Args:
            geojson_data: GeoJSON FeatureCollection

        Returns:
            GeoDataFrame with geometries and properties
        """
        try:
            gdf = gpd.GeoDataFrame.from_features(geojson_data["features"])
            if "crs" in geojson_data:
                gdf.crs = geojson_data["crs"]
            return gdf
        except Exception as e:
            logger.error(f"Failed to convert GeoJSON to GeoDataFrame: {e}")
            raise

    @staticmethod
    def table_to_dataframe(table_data: list) -> pd.DataFrame:
        """
        Convert table data to DataFrame.

        Args:
            table_data: List of row dictionaries

        Returns:
            DataFrame
        """
        try:
            return pd.DataFrame(table_data)
        except Exception as e:
            logger.error(f"Failed to convert table to DataFrame: {e}")
            raise

    @staticmethod
    def export_to_csv(
        data: Dict[str, Any],
        result_type: str = "table"
    ) -> Tuple[BytesIO, str]:
        """
        Export query results to CSV format.

        Args:
            data: Query result data (GeoJSON or table)
            result_type: Type of result ('geojson' or 'table')

        Returns:
            Tuple of (BytesIO object, filename)
        """
        try:
            if result_type == "geojson":
                # Convert GeoJSON to DataFrame
                gdf = ResultExporter.geojson_to_geodataframe(data)
                # Drop geometry column for CSV (convert to WKT if needed)
                df = pd.DataFrame(gdf)
                if "geometry" in df.columns:
                    # Convert geometry to WKT string
                    df["geometry_wkt"] = df["geometry"].apply(lambda x: str(x))
                    df = df.drop("geometry", axis=1)
            elif result_type == "table":
                df = ResultExporter.table_to_dataframe(data)
            else:
                raise ValueError(f"Unsupported result type: {result_type}")

            # Check size limit
            csv_buffer = StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_content = csv_buffer.getvalue()

            if len(csv_content.encode()) > ResultExporter.MAX_CSV_SIZE:
                raise ValueError(f"CSV export exceeds maximum size of {ResultExporter.MAX_CSV_SIZE} bytes")

            # Create BytesIO object
            bytes_buffer = BytesIO(csv_content.encode())
            bytes_buffer.seek(0)

            return bytes_buffer, "result.csv"

        except Exception as e:
            logger.error(f"Failed to export to CSV: {e}")
            raise

    @staticmethod
    def export_to_shapefile(
        geojson_data: Dict[str, Any],
        output_path: Optional[str] = None
    ) -> Tuple[Path, str]:
        """
        Export GeoJSON to Shapefile format.

        Args:
            geojson_data: GeoJSON FeatureCollection
            output_path: Optional custom output path (without extension)

        Returns:
            Tuple of (Path to shapefile, filename with extension)

        Note:
            Returns path to the .shp file. Associated .shx, .dbf files are created automatically.
        """
        temp_dir = None
        try:
            # Convert to GeoDataFrame
            gdf = ResultExporter.geojson_to_geodataframe(geojson_data)

            # Check size limit
            if len(gdf) * 100 > ResultExporter.MAX_SHAPEFILE_SIZE:  # Rough estimate
                raise ValueError(f"Shapefile export exceeds maximum estimated size")

            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            shapefile_path = os.path.join(temp_dir, "result")

            # Save shapefile (creates .shp, .shx, .dbf, .prj files)
            gdf.to_file(shapefile_path, driver="ESRI Shapefile")

            shapefile_full_path = Path(f"{shapefile_path}.shp")

            logger.info(f"✅ Shapefile created: {shapefile_full_path}")

            return shapefile_full_path, "result.shp"

        except Exception as e:
            logger.error(f"Failed to export to Shapefile: {e}")
            raise
        finally:
            # Note: temp_dir is NOT deleted here - it's the caller's responsibility
            pass

    @staticmethod
    def export_to_geojson(
        data: Dict[str, Any],
        result_type: str = "geojson"
    ) -> Tuple[BytesIO, str]:
        """
        Export query results to GeoJSON format.

        Args:
            data: Query result data (must be GeoJSON)
            result_type: Type of result (must be 'geojson')

        Returns:
            Tuple of (BytesIO object, filename)
        """
        try:
            if result_type != "geojson":
                raise ValueError("Only GeoJSON result type can be exported as GeoJSON")

            import json
            geojson_str = json.dumps(data, default=str)

            bytes_buffer = BytesIO(geojson_str.encode())
            bytes_buffer.seek(0)

            return bytes_buffer, "result.geojson"

        except Exception as e:
            logger.error(f"Failed to export to GeoJSON: {e}")
            raise

    @staticmethod
    def export_to_excel(
        data: Dict[str, Any],
        result_type: str = "table"
    ) -> Tuple[BytesIO, str]:
        """
        Export query results to Excel format.

        Args:
            data: Query result data (GeoJSON or table)
            result_type: Type of result ('geojson' or 'table')

        Returns:
            Tuple of (BytesIO object, filename)
        """
        try:
            # Check if openpyxl is available
            try:
                import openpyxl
            except ImportError:
                raise ImportError("openpyxl is required for Excel export. Install with: pip install openpyxl")

            if result_type == "geojson":
                gdf = ResultExporter.geojson_to_geodataframe(data)
                df = pd.DataFrame(gdf)
                if "geometry" in df.columns:
                    df["geometry_wkt"] = df["geometry"].apply(lambda x: str(x))
                    df = df.drop("geometry", axis=1)
            elif result_type == "table":
                df = ResultExporter.table_to_dataframe(data)
            else:
                raise ValueError(f"Unsupported result type: {result_type}")

            # Export to Excel
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="Results", index=False)

            excel_buffer.seek(0)
            return excel_buffer, "result.xlsx"

        except ImportError as e:
            logger.error(f"Excel export requires openpyxl: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to export to Excel: {e}")
            raise

    @staticmethod
    def export_to_kml(
        geojson_data: Dict[str, Any],
        output_path: Optional[str] = None
    ) -> Tuple[Path, str]:
        """
        Export GeoJSON to KML format (Google Earth compatible).

        Args:
            geojson_data: GeoJSON FeatureCollection
            output_path: Optional custom output path (without extension)

        Returns:
            Tuple of (Path to KML file, filename)
        """
        temp_dir = None
        try:
            # Check if fiona supports KML
            try:
                gdf = ResultExporter.geojson_to_geodataframe(geojson_data)
                temp_dir = tempfile.mkdtemp()
                kml_path = os.path.join(temp_dir, "result.kml")

                # Save to KML
                gdf.to_file(kml_path, driver="KML")

                logger.info(f"✅ KML created: {kml_path}")
                return Path(kml_path), "result.kml"

            except Exception as e:
                raise ValueError(f"KML export failed: {e}")

        except Exception as e:
            logger.error(f"Failed to export to KML: {e}")
            raise

    @staticmethod
    def get_export_formats() -> Dict[str, Dict[str, Any]]:
        """
        Get available export formats with metadata.

        Returns:
            Dictionary of export formats with properties
        """
        return {
            "csv": {
                "name": "CSV",
                "description": "Comma-separated values (tabular format)",
                "mime_type": "text/csv",
                "extension": ".csv",
                "supported_types": ["table", "geojson"],
                "max_size_mb": 50
            },
            "geojson": {
                "name": "GeoJSON",
                "description": "Web-friendly geographic JSON format",
                "mime_type": "application/geo+json",
                "extension": ".geojson",
                "supported_types": ["geojson"],
                "max_size_mb": 100
            },
            "shapefile": {
                "name": "Shapefile",
                "description": "ESRI Shapefile format (vector geometries)",
                "mime_type": "application/zip",
                "extension": ".zip",
                "supported_types": ["geojson"],
                "max_size_mb": 100
            },
            "excel": {
                "name": "Excel",
                "description": "Microsoft Excel format with formatting",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "extension": ".xlsx",
                "supported_types": ["table", "geojson"],
                "max_size_mb": 50
            },
            "kml": {
                "name": "KML",
                "description": "Keyhole Markup Language (Google Earth format)",
                "mime_type": "application/vnd.google-earth.kml+xml",
                "extension": ".kml",
                "supported_types": ["geojson"],
                "max_size_mb": 50
            }
        }


# Global exporter instance
result_exporter = ResultExporter()
