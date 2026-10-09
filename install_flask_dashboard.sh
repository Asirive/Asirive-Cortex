#!/bin/bash
# Flask Dashboard Quick Install Script

set -e

echo "🧠 Installing Flask Dashboard Dependencies..."

# Install Flask and Gunicorn
pip3 install Flask==3.0.0 Werkzeug==3.0.1 gunicorn==21.2.0

echo "✅ Flask Dashboard dependencies installed"
echo ""
echo "🚀 Quick Start:"
echo "  Development: cd src && python3 run_flask_dashboard.py"
echo "  Production:  cd src && gunicorn -c gunicorn_config.py run_flask_dashboard:app"
echo ""
echo "📡 Dashboard: http://localhost:5000"
echo "🎥 Video Stream: http://localhost:5000/stream/video"
echo "📊 Metrics Stream: http://localhost:5000/stream/metrics"
echo "🔍 Health Check: http://localhost:5000/health"
