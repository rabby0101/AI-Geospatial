from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
import os

from app.routes import query_router
from app.routes.raster import router as raster_router
from app.utils.database import db_manager
from app.utils.auto_discovery import auto_discovery

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
    """Initialize database connection and auto-discover new tables on startup"""
    print("🚀 Starting Cognitive Geospatial Assistant API...")
    print("📊 Initializing database connection...")

    try:
        db_manager.initialize()
        if db_manager.test_connection():
            print("✅ Database connection successful")
            
            # Auto-discover new tables and generate descriptions
            print("🔍 Auto-discovering tables...")
            result = auto_discovery.auto_discover_and_update()
            if result.get("new_tables_found", 0) > 0:
                print(f"✅ Found and added {result['new_tables_found']} new table(s)")
            else:
                print("✅ All tables are already documented")
        else:
            print("⚠️  Database connection failed - some features may not work")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("👋 Shutting down Cognitive Geospatial Assistant API...")


# Include routers
app.include_router(query_router)
app.include_router(raster_router)  # NDVI, terrain, land cover endpoints


# Serve static files (dashboards, assets)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    print(f"✅ Static files mounted from {static_dir}")

# Serve frontend if it exists
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    @app.get("/", response_class=HTMLResponse)
    async def read_root():
        """Serve the frontend HTML"""
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return index_path.read_text()
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
else:
    @app.get("/", response_class=HTMLResponse)
    async def read_root():
        """Root endpoint"""
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True
    )
