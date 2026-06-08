#!/usr/bin/env bash
# AbsorbAI one-shot infrastructure setup
# Run: bash setup.sh
# Requires sudo. Run as the jeyadev user.
set -e

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_NAME="absorbai"
DB_USER="absorbai"
DB_PASS="nTCRpG-qV-446ZOIsaEPFrlGDb4C-qfypzLT8WyhiKk"
VENV="$PROJ_DIR/venv"
SERVICE_USER="jeyadev"

echo "=== 1. Install Postgres + Redis ==="
sudo apt-get update -qq
sudo apt-get install -y postgresql postgresql-contrib redis-server

echo "=== 2. Start + enable services ==="
sudo systemctl enable postgresql redis-server
sudo systemctl start  postgresql redis-server

echo "=== 3. Create Postgres DB + user ==="
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

echo "=== 4. Verify Redis ==="
redis-cli ping

echo "=== 5. Write .env ==="
cat > "$PROJ_DIR/.env" <<EOF
SECRET_KEY=5RFiDl6JWWJIPp5TEsuiGC7XzZQ8NnMsq-0gwlMofkpnLt-3s-_LRJltPrU68HMgBZs
DEBUG=false
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
ENGINE_VERSION=1.0.0
DRUG_DB_VERSION=1.0.0
EOF
echo ".env written."

echo "=== 6. Install python-dotenv ==="
"$VENV/bin/pip" install python-dotenv --quiet

echo "=== 7. Migrate + seed ==="
cd "$PROJ_DIR"
"$VENV/bin/python" manage.py migrate
"$VENV/bin/python" manage.py seed_demo_users

echo "=== 8. Install systemd service for Celery ==="
sudo tee /etc/systemd/system/absorbai-celery.service > /dev/null <<UNIT
[Unit]
Description=AbsorbAI Celery Worker
After=network.target redis.service postgresql.service
Requires=redis.service

[Service]
Type=forking
User=$SERVICE_USER
WorkingDirectory=$PROJ_DIR
EnvironmentFile=$PROJ_DIR/.env
ExecStart=$VENV/bin/celery -A absorbai_project worker \
    --loglevel=info \
    --concurrency=2 \
    --pidfile=/tmp/absorbai-celery.pid \
    --logfile=/var/log/absorbai-celery.log \
    --detach
ExecStop=$VENV/bin/celery -A absorbai_project control shutdown
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
UNIT

sudo touch /var/log/absorbai-celery.log
sudo chown "$SERVICE_USER" /var/log/absorbai-celery.log
sudo systemctl daemon-reload
sudo systemctl enable absorbai-celery
sudo systemctl start  absorbai-celery

echo ""
echo "=== Done ==="
echo "Django dev server:  cd '$PROJ_DIR' && source venv/bin/activate && python manage.py runserver"
echo "Celery logs:        sudo journalctl -u absorbai-celery -f"
echo "Postgres:           psql postgresql://absorbai:$DB_PASS@localhost:5432/absorbai"
