# SupplierHub Deployment Guide - Ubuntu Server

## Prerequisites
- Ubuntu 20.04/22.04/24.04 LTS
- Root or sudo access
- Domain name (optional, for SSL)

---

## Step 1: System Update & Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install essential packages
sudo apt install -y curl wget git build-essential software-properties-common
```

---

## Step 2: Install PostgreSQL

```bash
# Install PostgreSQL 15
sudo apt install -y postgresql postgresql-contrib

# Start and enable PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
sudo -u postgres psql << EOF
CREATE USER supplierhub WITH PASSWORD 'your_secure_password_here';
CREATE DATABASE supplierhub_db OWNER supplierhub;
GRANT ALL PRIVILEGES ON DATABASE supplierhub_db TO supplierhub;
\q
EOF

# Verify connection
psql -U supplierhub -d supplierhub_db -h localhost -c "SELECT 1;"
```

---

## Step 3: Install Python 3.11+

```bash
# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Verify installation
python3.11 --version
```

---

## Step 4: Install Node.js 20.x

```bash
# Install Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install Yarn
npm install -g yarn

# Verify installation
node --version
yarn --version
```

---

## Step 5: Clone/Upload Application

```bash
# Create application directory
sudo mkdir -p /opt/supplierhub
sudo chown $USER:$USER /opt/supplierhub
cd /opt/supplierhub

# Option A: Clone from Git (if you pushed to GitHub)
# git clone https://github.com/your-repo/supplierhub.git .

# Option B: Upload files via SCP/SFTP
# scp -r /path/to/local/app/* user@server:/opt/supplierhub/
```

---

## Step 6: Setup Backend

```bash
cd /opt/supplierhub/backend

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
DATABASE_URL=postgresql://supplierhub:your_secure_password_here@localhost:5432/supplierhub_db
JWT_SECRET=$(openssl rand -hex 32)
CORS_ORIGINS=https://yourdomain.com,http://localhost:3000
EOF

# Test backend starts
python -c "from server import app; print('Backend OK')"
```

---

## Step 7: Setup Frontend

```bash
cd /opt/supplierhub/frontend

# Install dependencies
yarn install

# Create .env file (use your domain or server IP)
cat > .env << EOF
REACT_APP_BACKEND_URL=https://yourdomain.com
EOF

# Build production bundle
yarn build
```

---

## Step 8: Install & Configure Nginx

```bash
# Install Nginx
sudo apt install -y nginx

# Create Nginx config
sudo tee /etc/nginx/sites-available/supplierhub << 'EOF'
server {
    listen 80;
    server_name yourdomain.com;  # Replace with your domain or IP

    # Frontend - serve static files
    location / {
        root /opt/supplierhub/frontend/build;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Backend API proxy
    location /api {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/supplierhub /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload Nginx
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable nginx
```

---

## Step 9: Create Systemd Service for Backend

```bash
# Create systemd service file
sudo tee /etc/systemd/system/supplierhub-backend.service << EOF
[Unit]
Description=SupplierHub Backend API
After=network.target postgresql.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/supplierhub/backend
Environment=PATH=/opt/supplierhub/backend/venv/bin
ExecStart=/opt/supplierhub/backend/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable supplierhub-backend
sudo systemctl start supplierhub-backend

# Check status
sudo systemctl status supplierhub-backend
```

---

## Step 10: Setup SSL with Let's Encrypt (Optional but Recommended)

```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Get SSL certificate (replace with your domain)
sudo certbot --nginx -d yourdomain.com

# Auto-renewal is configured automatically
sudo systemctl enable certbot.timer
```

---

## Step 11: Configure Firewall

```bash
# Allow HTTP, HTTPS, and SSH
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable

# Verify
sudo ufw status
```

---

## Step 12: Verify Deployment

```bash
# Check backend is running
curl http://localhost:8001/api/health

# Check via Nginx
curl http://yourdomain.com/api/health

# Check logs if issues
sudo journalctl -u supplierhub-backend -f
sudo tail -f /var/log/nginx/error.log
```

---

## Default Credentials

- **Admin Username**: `admin`
- **Admin Password**: `admin`

**⚠️ IMPORTANT**: Change the admin password after first login!

---

## Useful Commands

```bash
# Restart backend
sudo systemctl restart supplierhub-backend

# View backend logs
sudo journalctl -u supplierhub-backend -f

# Rebuild frontend after changes
cd /opt/supplierhub/frontend && yarn build

# Check PostgreSQL
sudo -u postgres psql -d supplierhub_db -c "SELECT COUNT(*) FROM products;"

# Backup database
pg_dump -U supplierhub -d supplierhub_db > backup_$(date +%Y%m%d).sql
```

---

## Troubleshooting

### Backend won't start
```bash
# Check logs
sudo journalctl -u supplierhub-backend -n 50

# Test manually
cd /opt/supplierhub/backend
source venv/bin/activate
python -m uvicorn server:app --host 127.0.0.1 --port 8001
```

### Database connection issues
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
psql -U supplierhub -d supplierhub_db -h localhost
```

### Nginx 502 Bad Gateway
```bash
# Backend not running - start it
sudo systemctl start supplierhub-backend

# Check if port 8001 is listening
sudo netstat -tlnp | grep 8001
```

### Permission issues
```bash
# Fix ownership
sudo chown -R $USER:$USER /opt/supplierhub
```

---

## Environment Variables Reference

### Backend (.env)
| Variable | Description | Example |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection string | postgresql://user:pass@localhost:5432/db |
| JWT_SECRET | Secret for JWT tokens | (random 64 char hex string) |
| CORS_ORIGINS | Allowed origins | https://yourdomain.com |

### Frontend (.env)
| Variable | Description | Example |
|----------|-------------|---------|
| REACT_APP_BACKEND_URL | Backend API URL | https://yourdomain.com |

---

## Quick Start Script

Save this as `deploy.sh` and run with `sudo bash deploy.sh`:

```bash
#!/bin/bash
set -e

DOMAIN="yourdomain.com"  # Change this
DB_PASS="your_secure_password"  # Change this

echo "=== Installing dependencies ==="
apt update && apt upgrade -y
apt install -y curl wget git build-essential postgresql postgresql-contrib nginx python3.11 python3.11-venv python3-pip

curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs
npm install -g yarn

echo "=== Setting up PostgreSQL ==="
systemctl start postgresql
systemctl enable postgresql
sudo -u postgres psql -c "CREATE USER supplierhub WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -c "CREATE DATABASE supplierhub_db OWNER supplierhub;"

echo "=== Setting up backend ==="
cd /opt/supplierhub/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cat > .env << EOF
DATABASE_URL=postgresql://supplierhub:$DB_PASS@localhost:5432/supplierhub_db
JWT_SECRET=$(openssl rand -hex 32)
CORS_ORIGINS=https://$DOMAIN,http://localhost:3000
EOF

echo "=== Setting up frontend ==="
cd /opt/supplierhub/frontend
yarn install
echo "REACT_APP_BACKEND_URL=https://$DOMAIN" > .env
yarn build

echo "=== Deployment complete ==="
echo "Access your app at: https://$DOMAIN"
```
