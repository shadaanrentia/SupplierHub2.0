# Quick Start Guide

## Local Development (Fastest)

### Prerequisites
- Python 3.11+
- Node.js 18+
- MongoDB running locally (or use Docker: `docker run -d -p 27017:27017 mongo:6.0`)

### Steps

1. **Start Backend**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

2. **Start Frontend** (new terminal)
```bash
cd frontend
yarn install
cp .env.example .env
yarn start
```

3. **Open Browser**
- Frontend: http://localhost:3000
- API Docs: http://localhost:8001/docs

4. **Login**
- Username: `admin`
- Password: `admin`

---

## Docker Deployment (Production)

### Prerequisites
- Docker & Docker Compose installed

### Steps

1. **Configure Environment**
```bash
# Create .env file in project root
cat > .env << EOF
JWT_SECRET=$(openssl rand -hex 32)
CORS_ORIGINS=http://localhost:3000
REACT_APP_BACKEND_URL=http://localhost:8001
EOF
```

2. **Build & Start**
```bash
docker-compose up -d --build
```

3. **Access Application**
- Frontend: http://localhost:3000
- API: http://localhost:8001

4. **View Logs**
```bash
docker-compose logs -f
```

5. **Stop**
```bash
docker-compose down
```

---

## First Steps After Deployment

1. **Login** with admin/admin
2. **Change Password** (Settings or via database)
3. **Add Supplier** (Suppliers page)
4. **Test Connection** (verify supplier credentials)
5. **Sync Products** (Sync Jobs → Sync All)
6. **Configure Odoo** (Settings page, when ready)

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `MONGO_URL` | MongoDB connection string | Yes |
| `DB_NAME` | Database name | Yes |
| `JWT_SECRET` | Secret for JWT tokens | Yes (production) |
| `CORS_ORIGINS` | Allowed origins | Yes |
| `REACT_APP_BACKEND_URL` | Backend URL for frontend | Yes |

---

## Common Issues

**MongoDB connection failed**
- Ensure MongoDB is running
- Check MONGO_URL in .env

**CORS errors**
- Add your frontend URL to CORS_ORIGINS

**Supplier connection 403**
- Supplier WAF is blocking your IP
- Contact supplier to whitelist

**Images not loading**
- Run Media sync
- Check CDN accessibility
