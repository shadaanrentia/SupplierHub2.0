# SupplierHub - PromoStandards Middleware PRD

## Original Problem Statement
Build a middleware application that integrates supplier product data using PromoStandards SOAP APIs and synchronizes selected products into Odoo ERP. Central staging database, admin curation interface, automated sync jobs.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB
- **Frontend**: React with Shadcn UI, Tailwind CSS, dark theme
- **Database**: MongoDB (suppliers, products, product_variants, product_media, sync_logs, settings)
- **SOAP Client**: Raw XML over HTTP (no WSDL dependency - bypasses WAF blocking)
- **Flow**: PromoStandards SOAP APIs → Raw XML Connector → MongoDB Staging → Admin Curation → Odoo ERP (mock mode)

## User Personas
- **Admin**: Manages suppliers, curates products, triggers syncs, configures Odoo
- **System**: Automated background sync jobs for products/inventory/pricing/media

## Core Requirements (Static)
1. Multi-supplier Integration via PromoStandards (Product Data, Inventory, Pricing, Media Content)
2. Centralized staging database for all supplier product data
3. Data normalization layer (XML→JSON)
4. Admin product curation dashboard with filters
5. Odoo ERP integration layer (create/update products)
6. Background sync jobs (products 24h, inventory 30min, pricing 12h)
7. REST API layer for all operations
8. Logging and error handling

## What's Been Implemented

### December 2025 - Product Search & Individual Sync Features
- **Product Search Page**: New page at `/product-search` for searching products within a specific supplier
  - Supplier dropdown selector (required field)
  - Product name search input
  - Bulk sync buttons: "Sync All Pricing", "Sync All Inventory", "Sync All Media"
  - Grid/List view toggle
- **Individual Product Sync**: Added sync options for each product on the Products page
  - Dropdown menu (three dots icon) on each product card
  - Options: Sync Pricing, Sync Inventory, Sync Media for single products
  - Shows loading spinner during sync operations
  - Toast notifications for success/failure
- **View Toggle**: Grid/List view toggle on both Products and Product Search pages
- **Bulk Sync API**: New endpoint `POST /api/sync/products/bulk?sync_type={pricing|inventory|media}` with product_ids in body
- **Fixed Route Ordering Bug**: Moved bulk sync endpoint before supplier_id route to avoid route conflicts

### March 9, 2026 - Authentication & User Management
- **Login Page**: Username/password login with JWT tokens (24h expiration)
- **Registration**: New users can register, accounts require admin approval
- **Password Reset**: Email-based reset flow (sends reset token)
- **User Management (Admin)**: Approve/reject pending users, manage roles, delete users
- **Protected Routes**: All dashboard routes require authentication
- **Default Admin**: Shadaan Rentia (admin/admin) created on startup
- **Odoo Sync Filter**: Products page filter to show products synced/not synced to Odoo

### March 8, 2026 - Quick Sync All Feature
- **Quick Sync All Button**: Dashboard button that triggers Products → Media → Pricing syncs for all suppliers sequentially
- **Progress Indicator**: Shows current sync step, supplier name, and progress bar (X/total steps)
- **Auto-polling**: Waits for each sync to complete before moving to next step
- **Error Handling**: Continues with remaining syncs if one fails, logs warnings

### March 8, 2026 - Multi-Supplier Support
- **Raw SOAP XML Connector**: Replaced zeep/WSDL-dependent approach with raw SOAP XML requests
- **Supplier Type Selection**: Frontend dropdown for selecting supplier endpoint patterns (S&S, ATC, alphabroder, custom)
- **Auto-Endpoint Discovery**: Service URLs auto-generated based on supplier type and base URL
- **Test Connection Button**: UI button to verify supplier API connectivity with clear error messages
- **Media Password Support**: Separate password field for media API authentication
- **Advanced Options**: Expandable section for custom service URL configuration

### March 8, 2026 - Initial Implementation
- Full FastAPI backend with all CRUD endpoints for suppliers, products, sync, odoo, dashboard, settings
- PromoStandards SOAP connector for Product Data 2.0, Inventory 2.0, Pricing 1.0, Media Content 1.1
- Odoo XML-RPC integration layer (mock mode, ready for real credentials)
- MongoDB collections with proper indexing
- React admin dashboard with: Dashboard, Products, Product Detail, Suppliers, Sync Management, Settings pages
- Product filtering by supplier, category, brand, price, search, Odoo selection status
- Product select-for-Odoo toggle (individual and bulk)
- Sync trigger UI for products/inventory/pricing/media
- CDN fallback for product images when SOAP Media API authentication fails

## Configured Suppliers
1. **ATC / SanMar Canada** - Working (212 products synced)
   - Endpoint Style: `atc`
   - Base URL: https://edi.atc-apparel.com
   - Status: Active, connection successful

2. **S&S Activewear** - IP Blocked (HTTP 403)
   - Endpoint Style: `ss`
   - Base URL: https://promostandards-ca.ssactivewear.com
   - Status: Active, but server blocks requests from this IP (WAF)
   - **Resolution**: User needs to contact S&S to whitelist server IP

## Testing Results
### December 2025 (Latest)
- Backend API: 100% pass (15/15 new tests for Product Search & Individual Sync)
- Frontend UI: 100% pass (all new features working)
- Total products in database: 572

### March 8, 2026 (Previous)
- Backend API: 100% pass (23/23 tests)
- Frontend UI: 90% pass
- Integration: Working (ATC sync successful, S&S blocked by WAF)

## Known Issues
1. **S&S Activewear 403 Block**: Their server blocks requests from our IP - requires IP whitelisting
2. **Product Names**: Some products show "Array" due to SOAP response parsing (fix applied, needs re-sync)
3. **Odoo Integration**: Mocked - awaiting user credentials
4. ~~**Inventory Sync Parsing Bug**: Fixed - was not parsing nested `<Quantity><value>` XML structure correctly~~

## Prioritized Backlog

### P0 (Critical - Blocked)
- [ ] S&S Activewear IP whitelisting (requires user action)
- [ ] Connect real Odoo instance (waiting for credentials)

### P1 (Important)
- [ ] Implement APScheduler for automated periodic syncs
- [ ] Re-sync products to apply name parsing fix
- [ ] Run pricing sync to populate product prices (products currently show $0.00)
- [ ] Run media sync to display product images (currently showing placeholders)

### P2 (Nice to have)
- [ ] Add bulk data sync using BulkData SOAP endpoint
- [ ] Add product search by text index
- [ ] Add pagination to variants table on detail page
- [ ] Add export functionality (CSV/Excel)
- [ ] Add user authentication for admin dashboard
- [ ] Add webhook notifications for sync failures

## API Endpoints

### Suppliers
- `GET /api/suppliers` - List all suppliers
- `GET /api/suppliers/{id}` - Get supplier details
- `POST /api/suppliers` - Create supplier
- `PUT /api/suppliers/{id}` - Update supplier
- `DELETE /api/suppliers/{id}` - Delete supplier
- `POST /api/suppliers/{id}/test-connection` - Test supplier API connection

### Products
- `GET /api/products` - List products with filtering/pagination
- `GET /api/products/{id}` - Get product with variants/media
- `POST /api/products/{id}/select-for-odoo` - Toggle Odoo selection
- `POST /api/products/bulk-select` - Bulk select products

### Sync
- `POST /api/sync/products/{supplier_id}` - Trigger product sync
- `POST /api/sync/inventory/{supplier_id}` - Trigger inventory sync
- `POST /api/sync/pricing/{supplier_id}` - Trigger pricing sync
- `POST /api/sync/media/{supplier_id}` - Trigger media sync
- `POST /api/sync/product/{product_id}/pricing` - Sync pricing for single product
- `POST /api/sync/product/{product_id}/inventory` - Sync inventory for single product
- `POST /api/sync/product/{product_id}/media` - Sync media for single product
- `POST /api/sync/products/bulk?sync_type={type}` - Bulk sync (body: product_ids array)
- `GET /api/sync/logs` - Get sync history

### Odoo
- `POST /api/odoo/push-products` - Push selected products to Odoo
- `POST /api/odoo/test-connection` - Test Odoo connection

## Credentials
- **ATC/SanMar**: Account 37887 (working)
- **S&S Activewear**: Account 435145 (blocked by WAF)
- **Odoo**: Not provided yet
