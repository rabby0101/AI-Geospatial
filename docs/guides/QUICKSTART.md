# Quick Start Guide

Get up and running with the Cognitive Geospatial Assistant API in 5 minutes!

## Prerequisites

- Python 3.11+
- Docker Desktop (for PostGIS database)
- DeepSeek API Key ([Get one here](https://platform.deepseek.com/))

## Installation Steps

### Option 1: Automated Setup (Recommended)

```bash
# Run the setup script
./setup.sh

# Edit .env file and add your DeepSeek API key
nano .env  # or use your favorite editor

# Start the API
conda activate geoassist
python -m uvicorn app.main:app --reload
```

### Option 2: Manual Setup

```bash
# 1. Create virtual environment
conda create -n geoassist python=3.11
conda activate geoassist

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up environment variables
cp .env.example .env
# Edit .env and add: DEEPSEEK_API_KEY=your_key_here

# 4. Start PostGIS
docker-compose up -d postgis

# 5. Run the API
python -m uvicorn app.main:app --reload
```

## Verify Installation

1. Open http://localhost:8000 in your browser
2. You should see the web interface
3. Try an example query: "Find all hospitals in Berlin"

## API Endpoints

Once running, access:
- **Web Interface**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

## Testing the API with cURL

```bash
# Health check
curl http://localhost:8000/api/health

# List available datasets
curl http://localhost:8000/api/datasets

# Run a query
curl -X POST "http://localhost:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Find hospitals within 2 km of flood zones"}'
```

## Example Queries to Try

1. "Find all hospitals within 2 km of flood zones in Berlin"
2. "Show high-risk flood zones"
3. "Find urban areas with population over 90,000"
4. "Show hospitals in Mitte District"

## Troubleshooting

### Database Connection Failed

```bash
# Check if PostGIS is running
docker-compose ps

# Restart PostGIS
docker-compose restart postgis

# View logs
docker-compose logs postgis
```

### DeepSeek API Not Working

1. Verify your API key in `.env`
2. Check if the key has the format: `sk-...`
3. Ensure you have API credits

### Port Already in Use

```bash
# Change port in .env file
API_PORT=8001

# Or specify port when running
uvicorn app.main:app --port 8001
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_api.py
```

## Stopping the Application

```bash
# Stop the API: Press Ctrl+C in the terminal

# Stop PostGIS
docker-compose down

# Or stop without removing volumes
docker-compose stop
```

## Next Steps

1. **Explore the API**: Check out http://localhost:8000/docs
2. **Add Your Own Data**: Place GeoJSON files in `data/vector/`
3. **Customize Queries**: Modify the system prompt in `app/utils/deepseek.py`
4. **Read the Full README**: See `README.md` for detailed documentation

## Getting Help

- Check the full documentation: `README.md`
- Review example code in `tests/`
- Open an issue on GitHub

## Common Issues

**Issue**: `ModuleNotFoundError: No module named 'app'`
**Solution**: Make sure you're running from the project root directory

**Issue**: PostGIS connection fails
**Solution**: Wait 30 seconds after `docker-compose up` for initialization

**Issue**: Slow query processing
**Solution**: DeepSeek API can take 5-10 seconds for complex queries

## Development Mode

For development with auto-reload:

```bash
# API with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests in watch mode
pytest-watch
```

## Production Deployment

For production deployment:

```bash
# Build and run with Docker
docker-compose up -d

# The API will be available at http://localhost:8000
```

---

That's it! You're ready to query geospatial data with natural language.

For detailed information, see the full [README.md](README.md).
