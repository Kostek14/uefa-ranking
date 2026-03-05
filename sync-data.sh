#!/bin/bash
# This script copies data JSON to public/data/ so Netlify serves them correctly
# Run this if you deploy to a host that doesn't serve from the root
mkdir -p public/data
cp data/*.json public/data/ 2>/dev/null || true
echo "Data files synced to public/data/"
