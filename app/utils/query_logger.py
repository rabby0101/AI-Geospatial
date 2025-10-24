"""
Query Logging and Analytics Module

Provides logging of geospatial queries for:
- Analytics and usage tracking
- Performance monitoring
- Model improvement feedback
- Debugging and error analysis
"""

import json
import logging
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)

# Configuration
LOG_DIR = Path(os.getenv("QUERY_LOG_DIR", "logs/queries"))
LOG_DB = LOG_DIR / "query_log.db"
MAX_LOG_FILES = int(os.getenv("MAX_LOG_FILES", 100))


class QueryLogger:
    """
    Comprehensive query logging system with SQLite backend for analytics.

    Tracks:
    - Query text and parameters
    - Execution time and performance
    - Success/failure status
    - Data returned
    - User feedback for model improvement
    """

    def __init__(self):
        """Initialize query logger"""
        self.log_dir = LOG_DIR
        self.log_db = LOG_DB
        self._initialize_db()
        logger.info(f"✅ Query logger initialized at {self.log_db}")

    def _initialize_db(self):
        """Initialize SQLite database for query logging"""
        try:
            # Create log directory if it doesn't exist
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # Connect and create tables
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            # Query logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS query_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    question TEXT NOT NULL,
                    context TEXT,
                    user_location TEXT,
                    query_type TEXT,
                    execution_time REAL,
                    success BOOLEAN,
                    result_type TEXT,
                    result_count INTEGER,
                    error_message TEXT,
                    datasets_used TEXT,
                    reasoning TEXT,
                    from_cache BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # User feedback table (for model improvement)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS query_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id INTEGER NOT NULL,
                    rating INTEGER,  -- 1-5 stars
                    comment TEXT,
                    feedback_type TEXT,  -- 'helpful', 'incorrect', 'slow', 'incomplete'
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(query_id) REFERENCES query_logs(id)
                )
            """)

            # Query statistics table (aggregated)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS query_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hour DATETIME,
                    total_queries INTEGER,
                    successful_queries INTEGER,
                    failed_queries INTEGER,
                    avg_execution_time REAL,
                    cache_hits INTEGER,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for better query performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON query_logs(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_success ON query_logs(success)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_type ON query_logs(query_type)
            """)

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Failed to initialize query log database: {e}")
            raise

    def log_query(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        user_location: Optional[Dict[str, float]] = None,
        query_type: Optional[str] = None,
        execution_time: float = 0.0,
        success: bool = True,
        result_type: Optional[str] = None,
        result_count: int = 0,
        error_message: Optional[str] = None,
        datasets_used: Optional[List[str]] = None,
        reasoning: Optional[str] = None,
        from_cache: bool = False
    ) -> int:
        """
        Log a geospatial query.

        Args:
            question: User's natural language question
            context: Optional context information
            user_location: Optional user GPS coordinates
            query_type: Type of query (spatial, stats, raster, etc.)
            execution_time: Query execution time in seconds
            success: Whether query executed successfully
            result_type: Type of result (geojson, table, raster, etc.)
            result_count: Number of results returned
            error_message: Error message if execution failed
            datasets_used: List of datasets used in query
            reasoning: LLM reasoning for the query
            from_cache: Whether result came from cache

        Returns:
            Query log ID
        """
        try:
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            # Serialize complex fields
            context_str = json.dumps(context) if context else None
            location_str = json.dumps(user_location) if user_location else None
            datasets_str = json.dumps(datasets_used) if datasets_used else None

            cursor.execute("""
                INSERT INTO query_logs (
                    question, context, user_location, query_type,
                    execution_time, success, result_type, result_count,
                    error_message, datasets_used, reasoning, from_cache
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                question, context_str, location_str, query_type,
                execution_time, success, result_type, result_count,
                error_message, datasets_str, reasoning, from_cache
            ))

            query_id = cursor.lastrowid
            conn.commit()
            conn.close()

            logger.debug(f"Logged query {query_id}: {question[:50]}...")
            return query_id

        except Exception as e:
            logger.error(f"Failed to log query: {e}")
            return -1

    def add_feedback(
        self,
        query_id: int,
        rating: Optional[int] = None,
        comment: Optional[str] = None,
        feedback_type: Optional[str] = None
    ) -> bool:
        """
        Add user feedback for a logged query.

        Args:
            query_id: ID of the query to add feedback for
            rating: 1-5 star rating
            comment: User comment
            feedback_type: Type of feedback (helpful, incorrect, slow, incomplete)

        Returns:
            True if feedback was recorded
        """
        try:
            # Validate query exists
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM query_logs WHERE id = ?", (query_id,))
            if not cursor.fetchone():
                logger.warning(f"Query ID {query_id} not found")
                conn.close()
                return False

            # Insert feedback
            cursor.execute("""
                INSERT INTO query_feedback (query_id, rating, comment, feedback_type)
                VALUES (?, ?, ?, ?)
            """, (query_id, rating, comment, feedback_type))

            conn.commit()
            conn.close()

            logger.info(f"Recorded feedback for query {query_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
            return False

    def get_query_stats(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent query statistics.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of query statistics
        """
        try:
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    id, timestamp, question, query_type,
                    execution_time, success, result_count, from_cache, error_message
                FROM query_logs
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    "id": row[0],
                    "timestamp": row[1],
                    "question": row[2],
                    "query_type": row[3],
                    "execution_time": row[4],
                    "success": bool(row[5]),
                    "result_count": row[6],
                    "from_cache": bool(row[7]),
                    "error_message": row[8]
                })

            conn.close()
            return results

        except Exception as e:
            logger.error(f"Failed to get query stats: {e}")
            return []

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get overall performance metrics across all queries.

        Returns:
            Dictionary with performance metrics
        """
        try:
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            # Total queries
            cursor.execute("SELECT COUNT(*) FROM query_logs")
            total_queries = cursor.fetchone()[0]

            # Successful queries
            cursor.execute("SELECT COUNT(*) FROM query_logs WHERE success = 1")
            successful_queries = cursor.fetchone()[0]

            # Average execution time
            cursor.execute("SELECT AVG(execution_time) FROM query_logs WHERE success = 1")
            avg_time = cursor.fetchone()[0] or 0

            # Cache hits
            cursor.execute("SELECT COUNT(*) FROM query_logs WHERE from_cache = 1")
            cache_hits = cursor.fetchone()[0]

            # Success rate
            success_rate = (successful_queries / total_queries * 100) if total_queries > 0 else 0

            # Queries by type
            cursor.execute("""
                SELECT query_type, COUNT(*) as count
                FROM query_logs
                WHERE query_type IS NOT NULL
                GROUP BY query_type
                ORDER BY count DESC
            """)
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            # Top 5 slowest queries
            cursor.execute("""
                SELECT question, execution_time FROM query_logs
                WHERE success = 1
                ORDER BY execution_time DESC
                LIMIT 5
            """)
            slowest_queries = [{"question": row[0], "time": row[1]} for row in cursor.fetchall()]

            # Top 5 most common errors
            cursor.execute("""
                SELECT error_message, COUNT(*) as count
                FROM query_logs
                WHERE success = 0 AND error_message IS NOT NULL
                GROUP BY error_message
                ORDER BY count DESC
                LIMIT 5
            """)
            top_errors = [{"error": row[0], "count": row[1]} for row in cursor.fetchall()]

            conn.close()

            return {
                "total_queries": total_queries,
                "successful_queries": successful_queries,
                "failed_queries": total_queries - successful_queries,
                "success_rate": round(success_rate, 2),
                "avg_execution_time": round(avg_time, 2),
                "cache_hits": cache_hits,
                "cache_hit_rate": round(cache_hits / total_queries * 100, 2) if total_queries > 0 else 0,
                "queries_by_type": by_type,
                "slowest_queries": slowest_queries,
                "top_errors": top_errors
            }

        except Exception as e:
            logger.error(f"Failed to get performance metrics: {e}")
            return {}

    def get_model_improvement_feedback(self) -> List[Dict[str, Any]]:
        """
        Get user feedback data for model improvement.

        Returns:
            List of feedback entries with associated queries
        """
        try:
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    qf.id, ql.question, qf.rating, qf.comment, qf.feedback_type, qf.created_at
                FROM query_feedback qf
                JOIN query_logs ql ON qf.query_id = ql.id
                ORDER BY qf.created_at DESC
                LIMIT 100
            """)

            results = []
            for row in cursor.fetchall():
                results.append({
                    "feedback_id": row[0],
                    "question": row[1],
                    "rating": row[2],
                    "comment": row[3],
                    "feedback_type": row[4],
                    "created_at": row[5]
                })

            conn.close()
            return results

        except Exception as e:
            logger.error(f"Failed to get feedback data: {e}")
            return []

    def export_logs_csv(self, output_path: str) -> bool:
        """
        Export query logs to CSV for external analysis.

        Args:
            output_path: Path to save CSV file

        Returns:
            True if export successful
        """
        try:
            import csv

            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    id, timestamp, question, query_type, execution_time,
                    success, result_count, from_cache, error_message
                FROM query_logs
                ORDER BY timestamp DESC
            """)

            rows = cursor.fetchall()
            conn.close()

            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'ID', 'Timestamp', 'Question', 'Query Type', 'Execution Time (s)',
                    'Success', 'Result Count', 'From Cache', 'Error Message'
                ])
                writer.writerows(rows)

            logger.info(f"Exported {len(rows)} query logs to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to export logs: {e}")
            return False

    def clear_old_logs(self, days: int = 30) -> int:
        """
        Delete query logs older than specified number of days.

        Args:
            days: Number of days to keep

        Returns:
            Number of logs deleted
        """
        try:
            conn = sqlite3.connect(str(self.log_db))
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM query_logs
                WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
            """, (days,))

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            logger.info(f"Deleted {deleted_count} query logs older than {days} days")
            return deleted_count

        except Exception as e:
            logger.error(f"Failed to clear old logs: {e}")
            return 0


# Global logger instance
query_logger = QueryLogger()
