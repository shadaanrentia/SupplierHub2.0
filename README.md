# SupplierHub - PromoStandards Middleware

A middleware application that integrates supplier product data using PromoStandards SOAP APIs and synchronizes selected products into Odoo ERP.

## Features

- **Multi-Supplier Integration**: Connect to multiple PromoStandards-compliant suppliers (ATC/SanMar, S&S Activewear, alphabroder, custom)
- **Product Data Sync**: Fetch products, variants, inventory, pricing, and media from suppliers
- **Staging Database**: PostgreSQL-based staging layer for product curation
- **Admin Dashboard**: React-based UI for managing suppliers, products, and sync jobs
- **User Management**: JWT authentication with admin approval workflow
- **Odoo Integration**: Push curated products to Odoo ERP (configurable)
- **Background Sync Jobs**: Async sync operations with progress tracking and cancellation
- **Warehouse-Specific Inventory**: Filter inventory display by preferred warehouse location

## Tech Stack

- **Backend**: Python FastAPI
- **Frontend**: React 18, Tailwind CSS, shadcn/ui
- **Database**: PostgreSQL 15
- **API Integration**: PromoStandards SOAP (raw XML), Odoo XML-RPC

## Project Structure

```
/app
├── backend/
│   ├── server.py           # Main FastAPI application
│   ├── promostandards.py   # PromoStandards SOAP connector
│   ├── odoo_service.py     # Odoo integration service
│   ├── requirements.txt    # Python dependencies
│   └── .env               # Environment variables
├── frontend/
│   ├── src/
│   │   ├── App.js         # Main React app with routing
│   │   ├── components/    # Reusable UI components
│   │   └── pages/         # Page components
│   ├── package.json       # Node dependencies
│   └── .env              # Frontend environment variables
└── memory/
    └── PRD.md            # Product requirements document
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+
- Yarn package manager

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd supplierhub
```

### 2. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your configuration
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
yarn install

# Create .env file
cp .env.example .env
# Edit .env with your configuration
```

## Configuration

### Backend Environment Variables (`backend/.env`)

```env
# PostgreSQL Connection
DATABASE_URL=postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db

# JWT Configuration (change in production!)
JWT_SECRET=your-secret-key-change-in-production

# CORS Origins (comma-separated)
CORS_ORIGINS=http://localhost:3000,https://yourdomain.com
```

### Frontend Environment Variables (`frontend/.env`)

```env
# Backend API URL
REACT_APP_BACKEND_URL=http://localhost:8001
```

## Running the Application

### Development Mode

**Backend:**
```bash
cd backend
source venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

**Frontend:**
```bash
cd frontend
yarn start
```

### Production Deployment

#### Using Docker (Recommended)

```bash
# Build and run with Docker Compose
docker-compose up -d
```

#### Manual Deployment

**Backend:**
```bash
cd backend
pip install gunicorn
gunicorn server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8001
```

**Frontend:**
```bash
cd frontend
yarn build
# Serve the build folder with nginx or any static file server
```

## Default Credentials

After first startup, a default admin user is created:

- **Username**: `admin`
- **Password**: `admin`

**Important**: Change the default password immediately after first login!

## API Endpoints

### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/register` - User registration (requires admin approval)
- `POST /api/auth/reset-password` - Request password reset
- `GET /api/auth/me` - Get current user info

### User Management (Admin only)
- `GET /api/users` - List all users
- `GET /api/users/pending` - List pending approvals
- `POST /api/users/{id}/approve` - Approve/reject user
- `DELETE /api/users/{id}` - Delete user

### Suppliers
- `GET /api/suppliers` - List suppliers
- `POST /api/suppliers` - Create supplier
- `PUT /api/suppliers/{id}` - Update supplier
- `DELETE /api/suppliers/{id}` - Delete supplier
- `POST /api/suppliers/{id}/test-connection` - Test supplier API connection

### Products
- `GET /api/products` - List products (with filtering)
- `GET /api/products/{id}` - Get product details with variants
- `POST /api/products/{id}/select-for-odoo` - Toggle Odoo selection
- `POST /api/products/bulk-select` - Bulk select products

### Sync Operations
- `POST /api/sync/products/{supplier_id}` - Sync products
- `POST /api/sync/inventory/{supplier_id}` - Sync inventory
- `POST /api/sync/pricing/{supplier_id}` - Sync pricing
- `POST /api/sync/media/{supplier_id}` - Sync media/images
- `POST /api/sync/all/{supplier_id}` - Full sync (all types in sequence)
- `POST /api/sync/stop/{log_id}` - Stop running sync
- `GET /api/sync/logs` - Get sync history

### Odoo Integration
- `POST /api/odoo/push-products` - Push selected products to Odoo
- `POST /api/odoo/test-connection` - Test Odoo connection

## Adding a New Supplier

1. Navigate to **Suppliers** page
2. Click **Add Supplier**
3. Fill in the details:
   - **Supplier Name**: Display name
   - **Supplier Type**: Select from dropdown (determines API endpoint structure)
   - **API Base URL**: Base URL for the supplier's API
   - **Account Number**: Your supplier account ID
   - **Password**: API password
   - **Media Password**: (Optional) Separate password for media API
4. Click **Create**
5. Click **Test** to verify connection
6. Use **Sync Jobs** to start syncing products

## Supported Supplier Types

| Type | Example Suppliers | Endpoint Pattern |
|------|-------------------|------------------|
| `atc` | ATC, SanMar Canada | `/pstd/productdata2.0/...` |
| `ss` | S&S Activewear | `/ProductData/v2/...` |
| `alphabroder` | alphabroder | `/promostandards/ProductDataService/...` |
| `custom` | Any PromoStandards | Manual URL configuration |

## Sync Order (Best Practice)

When syncing a new supplier, run syncs in this order:

1. **Products** - Fetches product catalog (required first)
2. **Inventory** - Updates stock levels
3. **Pricing** - Updates prices
4. **Media** - Fetches product images

Or use the **"Sync All"** button which runs all syncs in the correct order.

## Troubleshooting

### Supplier Connection Fails with 403

The supplier's firewall (WAF) is blocking requests from your server IP. Contact the supplier to whitelist your server IP address.

### Products Show "NA" Category or "Array" Name

This usually means the product sync used incorrect SKU format. Use the **Reset & Sync** option to clear and re-sync products.

### Prices Not Showing

Run a **Pricing Sync** after the product sync. Prices are fetched separately from product data.

### Images Not Loading

1. Run a **Media Sync**
2. If media API fails, the system falls back to CDN URLs
3. Some suppliers require separate media API credentials

## License

Proprietary - All rights reserved

## Support

For support, contact: support@supplierhub.com
