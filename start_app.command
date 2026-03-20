#!/bin/bash

# Change to the project directory
cd "$(dirname "$0")"

# Activate conda environment
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate geoassist

# Start the application
python -m uvicorn app.main:app --reload
