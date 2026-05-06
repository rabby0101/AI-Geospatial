from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
import os

from app.routes.database import router as database_router
from app.routes.routing import router as routing_router

from app.routes.semantic import router as semantic_router
from app.routes.gdi_berlin import router as gdi_berlin_router
from app.routes.walking_distance import router as walking_distance_router
from app.routes.geocoding import router as geocoding_router
from app.routes.satellite import router as satellite_router
from app.routes.skills import router as skills_router
from app.routes.agent import router as agent_router
from app.routes.agent_trace import router as agent_trace_router
from app.routes.temp_layers import router as temp_layers_router
from app.routes.attachments import router as attachments_router
from app.utils.database import db_manager
from app.utils.auto_discovery import auto_discovery
from app.utils.skills_manager import load_skills

# Create FastAPI app
app = FastAPI(
    title="Cognitive Geospatial Assistant API",
    description="An LLM-Integrated API for Interactive Geospatial Reasoning and Querying",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database connection, auto-discover tables, and start SchemaWatcher"""
    load_skills()
    print("🚀 Starting Cognitive Geospatial Assistant API...")
    print("📊 Initializing database connection...")

    # Clean up stale per-session tmp dirs (older than 24h)
    import glob, time as _time
    for pattern in ("/tmp/satellite_*", "/tmp/attachments_*"):
        for d in glob.glob(pattern):
            try:
                from pathlib import Path as _Path
                if _time.time() - _Path(d).stat().st_mtime > 86400:
                    import shutil as _shutil
                    _shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    try:
        db_manager.initialize()
        if db_manager.test_connection():
            print("✅ Database connection successful")

            from app.utils.agent_trace_store import init_trace_table
            try:
                init_trace_table()
                print("✅ Agent trace table ready")
            except Exception as e:
                print(f"⚠️  Agent trace table init failed: {e}")

            # Auto-discover new tables and generate rich descriptions
            print("🔍 Auto-discovering tables...")
            result = auto_discovery.auto_discover_and_update()
            if result.get("new_tables_found", 0) > 0:
                print(f"✅ Found and added {result['new_tables_found']} new table(s)")
            else:
                print("✅ All tables are already documented")

            # Load knowledge graph (table concept index)
            print("🧠 Loading knowledge graph...")
            try:
                from app.utils.semantic_layer import get_semantic_layer
                from pathlib import Path
                sl = get_semantic_layer()
                graph_path = Path(__file__).parent / "ontology" / "table_graph.ttl"
                triples = sl.load_graph(str(graph_path))
                print(f"✅ Knowledge graph loaded ({triples} table triples)")
            except Exception as e:
                print(f"⚠️  Knowledge graph load failed (run scripts/migrate_db_to_graph.py): {e}")

            # Start background schema watcher
            from app.utils.schema_watcher import SchemaWatcher
            schema_watcher = SchemaWatcher()
            await schema_watcher.start()
            app.state.schema_watcher = schema_watcher
        else:
            print("⚠️  Database connection failed - some features may not work")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("👋 Shutting down Cognitive Geospatial Assistant API...")
    if hasattr(app.state, "schema_watcher"):
        await app.state.schema_watcher.stop()


# Include routers
app.include_router(database_router)    # Database metadata and schema endpoints
app.include_router(routing_router)     # Road routing and connectivity endpoints

app.include_router(semantic_router)    # Semantic/Knowledge Graph endpoints
app.include_router(gdi_berlin_router)  # GDI Berlin WFS import endpoints
app.include_router(walking_distance_router)  # Walking distance analysis endpoints
app.include_router(geocoding_router)         # Geocoding endpoints (Nominatim)
app.include_router(satellite_router)         # Satellite image analysis endpoints
app.include_router(skills_router)            # Skills system endpoints
app.include_router(agent_router)             # Agentic ReAct query endpoint
app.include_router(agent_trace_router)       # Agent trace retrieval endpoint
app.include_router(temp_layers_router)       # Temp layer creation for selected features
app.include_router(attachments_router)       # Chat bar multi-file attachments (PDF/Excel/satellite)


# Serve static files (dashboards, assets)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    print(f"✅ Static files mounted from {static_dir}")

# Serve main interface (Frontend Map)
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the frontend map interface as main application"""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return frontend_path.read_text()
    # Fallback to dashboard if frontend not found
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    if dashboard_path.exists():
        return dashboard_path.read_text()
    return """
    <html>
        <head>
            <title>Cognitive Geospatial Assistant API</title>
        </head>
        <body>
            <h1>Cognitive Geospatial Assistant API</h1>
            <p>API is running! Visit <a href="/docs">/docs</a> for API documentation.</p>
            <p><a href="/static/dashboard.html">📊 Analytics Dashboard</a></p>
        </body>
    </html>
    """

# Serve frontend if it exists (legacy support)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    @app.get("/frontend", response_class=HTMLResponse)
    async def read_frontend():
        """Serve the frontend HTML"""
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return index_path.read_text()
        return "Frontend not found"


@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the analytics dashboard"""
    dashboard_path = Path(__file__).parent / "static" / "dashboard.html"
    if dashboard_path.exists():
        return dashboard_path.read_text()
    return """
    <html>
        <head><title>Dashboard Not Found</title></head>
        <body>
            <h1>Dashboard Not Found</h1>
            <p>The analytics dashboard file is missing.</p>
            <p><a href="/docs">Go to API docs</a></p>
        </body>
    </html>
    """


@app.get("/database-inspector", response_class=HTMLResponse)
async def get_database_inspector():
    """Serve the database inspector tool"""
    inspector_path = Path(__file__).parent.parent / "frontend" / "database-inspector.html"
    if inspector_path.exists():
        return inspector_path.read_text()
    return """
    <html>
        <head><title>Database Inspector Not Found</title></head>
        <body>
            <h1>Database Inspector Not Found</h1>
            <p>The database inspector file is missing.</p>
            <p><a href="/">Go home</a></p>
        </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True
    )
