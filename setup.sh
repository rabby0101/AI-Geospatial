#!/bin/bash

echo "🌍 Cognitive Geospatial Assistant API - Setup Script"
echo "=================================================="
echo ""

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo "❌ Conda not found. Please install Anaconda or Miniconda first."
    exit 1
fi

# Create conda environment
echo "📦 Creating conda environment 'geoassist'..."
conda create -n geoassist python=3.11 -y

# Activate environment
echo "🔄 Activating environment..."
eval "$(conda shell.bash hook)"
conda activate geoassist

# Install dependencies
echo "📥 Installing Python dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your DEEPSEEK_API_KEY"
else
    echo "✓ .env file already exists"
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "⚠️  Docker is not running. Please start Docker to use PostGIS."
else
    echo "🐳 Starting PostGIS with Docker Compose..."
    docker-compose up -d postgis

    # Wait for PostGIS to be ready
    echo "⏳ Waiting for PostGIS to be ready..."
    sleep 10
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add your DeepSeek API key to .env file"
echo "2. Activate the environment: conda activate geoassist"
echo "3. Start the API: python -m uvicorn app.main:app --reload"
echo "4. Open http://localhost:8000 in your browser"
echo ""
echo "To run tests: pytest"
echo "To view API docs: http://localhost:8000/docs"
