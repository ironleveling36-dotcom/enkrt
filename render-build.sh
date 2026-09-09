#!/usr/bin/env bash
# render-build.sh

echo "🚀 Building Lenskart Bot..."

# Install system dependencies
apt-get update -qq && apt-get install -y -qq sqlite3

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create data directory
mkdir -p /data

echo "✅ Build complete!"
