# SupplierHub - PromoStandards Middleware PRD

## Original Problem Statement
Build a middleware application that integrates supplier product data using PromoStandards SOAP APIs and synchronizes selected products into Odoo ERP. Central staging database, admin curation interface, automated sync jobs.

## Architecture
- **Backend**: FastAPI (Python) with PostgreSQL
- **Frontend**: React with Shadcn UI, Tailwind CSS, dark theme
- **Database**: PostgreSQL 15 (users, suppliers, products, product_variants, product_media, sync_logs, settings, odoo_categories, category_mapping, product_sync_status)
- **SOAP Client**: Raw XML over HTTP with XML escaping (no WSDL dependency - bypasses WAF blocking)
- **Odoo Integration**: XML-RPC client for creating/updating products, variants, inventory, and images
- **Flow**: PromoStandards SOAP APIs → Raw XML Connector → PostgreSQL Staging → Admin Curation → Pre-Processing → Odoo ERP

## User Personas
- **Admin**: Manages suppliers, curates products, maps categories, triggers syncs, configures Odoo
- **System**: Automated background sync jobs for products/inventory/pricing/media

## Core Requirements (Static)
1. Multi-supplier Integration via PromoStandards (Product Data, Inventory, Pricing, Media Content)
2. Centralized staging database for all supplier product data
3. Data normalization layer (XML→JSON)
4. Admin product curation dashboard with filters
5. Odoo ERP integration layer (create/update products with full details)
6. Background sync jobs (products 24h, inventory 30min, pricing 12h)
7. REST API layer for all operations
8. Logging and error handling
9. Category mapping between supplier and Odoo e-commerce categories
10. Product pre-processing with configurable markup and validation

## What's Been Implemented

### July 24, 2026 - Lightspeed eSeries Integration (Phase 2)
- **Multi-Platform Architecture**: Evolved from Odoo-only to provider-based multi-platform integration
- **New Service: `lightspeed_service.py`**
  - Full Lightspeed eCom REST API integration (Basic Auth with api_key:api_secret)
  - Supports US1 and EU1 clusters
  - Product CRUD: create/update with automatic SKU-based lookup
  - Variant sync: pricing (priceExcl, priceCost), stock levels, SKU mapping
  - Category management: fetch all categories (paginated), create, assign to products
  - Image upload: base64 encoded attachment via product images endpoint
  - Rate limit tracking and automatic throttling
  - Mock mode when credentials not configured
- **DB Schema Additions**:
  - `settings`: lightspeed_api_key, lightspeed_api_secret, lightspeed_cluster, lightspeed_language
  - `products`: selected_for_lightspeed, lightspeed_sync_status, lightspeed_product_id
  - `category_mapping`: lightspeed_category_id
- **New API Endpoints**:
  - `POST /api/settings/lightspeed/test` - Test Lightspeed connection
  - `GET /api/categories/lightspeed` - Fetch categories from Lightspeed store
  - `POST /api/sync/lightspeed/{supplier_id}` - Push products to Lightspeed (background task)
  - `POST /api/products/{id}/select-for-lightspeed` - Toggle Lightspeed selection
  - `POST /api/products/bulk-select-lightspeed` - Bulk toggle
- **Frontend Updates**:
  - Settings: Lightspeed eCom Connection card (API Key, Secret, Cluster, Language)
  - Category Mapping: Platform selector (Odoo / Lightspeed eCom) with dynamic UI
  - Products: Dual toggle switches (Odoo blue + Lightspeed green) in grid and list views
  - Sync Management: "Push to Lightspeed" button per supplier, filter option in sync logs
- **Bug Fix**: Duplicate column assignment in settings update for lightspeed_api_secret

### March 27, 2026 - APScheduler & Auto-Push to Odoo
- **New Feature: Automated Background Sync Jobs**
  - Created `backend/scheduler.py` using APScheduler's `AsyncIOScheduler`
  - Scheduler starts on app startup, reads settings to configure jobs
  - 3 job types: products (interval in hours), inventory (interval in minutes), pricing (interval in hours)
  - Jobs auto-created/removed when `auto_sync_enabled` toggled in settings
  - Settings changes trigger automatic job rescheduling
  - New endpoints: `GET /api/scheduler/status`, `POST /api/scheduler/reschedule`
- **New Feature: Auto-Push to Odoo after BulkData Sync**
  - New `auto_push_to_odoo` setting (boolean toggle)
  - After BulkData sync completes, checks if auto-push enabled
  - If enabled, automatically pushes all pending products for that supplier to Odoo
  - Creates separate sync log entry for the auto-push
- **Frontend Settings Update**
  - Added "Auto-push to Odoo after BulkData sync" toggle
  - Added Scheduler Status panel showing RUNNING/STOPPED badge and scheduled jobs with next run times
- **Bug Fix**: Fixed user CRUD endpoints (column name mismatch: `password_hash` → `hashed_password`)

### March 16, 2026 - BulkData Sync Feature Added
- **New Feature: BulkData Service 1.0 Integration**
  - Added `get_bulk_data()` method to `promostandards.py`
  - Downloads all products with images in a single API call
  - Limited to once per day per account (error 125 for rate limiting)
  - Auto-detects supplier endpoint style from base URL (atc, ss, alphabroder, generic)
- **New Endpoint**: `/api/sync/bulk-data/{supplier_id}` - triggers BulkData sync
- **New UI Button**: "Bulk Data" (purple) on Sync Jobs page
- **Image Storage**: URLs stored in database even if download fails (for retry capability)
- **Tested with Sandbox**: Successfully synced 2 products from ATC sandbox to database and Odoo
  - Products: ATC 1000 T-SHIRT (2 variants), DISCONTINUED GILDAN® ULTRA COTTON® T-SHIRT (1 variant)
  - Inventory synced correctly (125, 200, 452 units)
  - Cost and sale prices synced correctly

### March 16, 2026 - Odoo Sync Complete (Images & Inventory)
- **Fixed Odoo Image Sync**: Images now properly download from supplier URLs and upload to Odoo
  - Main product image set via `image_1920` field
  - Additional images stored in `product.image` model
  - Better error handling for CDN restrictions and failed downloads
  - Image format detection via magic bytes for reliability
- **Fixed Odoo Inventory Sync**: Units on Hand now correctly synced to Odoo
  - Uses `stock.quant` model with fallback methods for different Odoo versions
  - Properly maps variant inventory from supplier data
  - All 6 test variants synced with correct quantities (280 total units)
- **Fixed Odoo Cost Price**: Cost price now synced to all product variants
  - Updates `standard_price` on `product.product` records after variants created
  - Works correctly with Odoo 16's variant-level pricing
- **Odoo Database Fix**: Corrected database name from `redleafssports-master-6556138` to `RedLeafsPOC27012026`
- **Settings Update**: Added `markup_percentage` to SettingsUpdate model and handler

**Verified Odoo Sync Fields:**
- ✅ Product Name
- ✅ Sale Price (with markup: $25.99 → $36.00)
- ✅ Cost Price ($25.99 on all variants)
- ✅ Description (Sales description)
- ✅ Inventory Category (SanMar Apparel)
- ✅ E-Commerce Category (mapped via category_mapping)
- ✅ Main Image (uploaded successfully)
- ✅ Extra Images (product.image records)
- ✅ Variants (6 variants with Size/Color attributes)
- ✅ Inventory (280 units distributed across variants)

### March 9, 2026 - Bug Fixes (Pricing & Media)
- **Pricing Sync Fix**: Fixed critical bug where pricing sync was looking for a non-existent `price` key instead of the `prices` array in API response
  - Now correctly extracts the first/lowest quantity tier price from the `prices` array
  - Also updates product `base_price` with the minimum variant price after pricing sync
  - Affected files: `backend/server.py` (sync_pricing_task, _sync_product_pricing_internal, bulk sync)
- **XML Escaping**: Added proper XML escaping for special characters in supplier credentials (e.g., # @ &)
  - Uses `xml.sax.saxutils.escape` for account_id, password, and media_password
  - Also escapes product_id in API requests
  - Affected file: `backend/promostandards.py`
- **Media Proxy Endpoint**: Added new `GET /api/media_proxy?url=<encoded_url>` endpoint to bypass CDN restrictions
  - Validates URL domain against allowed supplier domains
  - Streams image content with proper headers
  - Affected file: `backend/server.py`
- **Frontend Media Display**: Updated ProductDetail.jsx to use the media proxy for all images
  - Added "Open original" link for fallback access
  - Improved error handling display
  - Affected file: `frontend/src/pages/ProductDetail.jsx`

**Note**: Supplier CDNs have CAPTCHA bot protection that blocks server-side requests. Images may not display even with proxy. Users can click "Open original" to view in browser after passing CAPTCHA.

### December 2025 - PostgreSQL Migration & Final Features
- **Database Migration**: Migrated from MongoDB to PostgreSQL
  - All 572 products, 18,825 variants, 2 suppliers successfully migrated
  - New schema with proper foreign keys and indexes
  - Migration script: `/app/backend/migrate_to_postgres.py`
  - Using asyncpg for async PostgreSQL operations
- **Axios Interceptor**: Added authentication interceptor for automatic token handling
  - `/app/frontend/src/lib/axios.js` - auto-attaches Bearer token to all requests
  - Auto-redirects to login on 401 errors
- **Bug Fixes**:
  - Fixed Dashboard Total Variants count (now shows 18,825)
  - Fixed Welcome toast to show full_name correctly
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
- **Warehouse-Specific Inventory Display**:
  - New setting to select preferred warehouse (Settings page)
  - Product detail page now shows inventory only for the selected warehouse (default: MISSISSAUGA/ON)
  - API endpoint `GET /api/settings/warehouses` to fetch available warehouse locations
  - Fixed inventory sync XML parsing for nested `<Quantity><value>` structure

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
- PostgreSQL database with proper schema, foreign keys, and indexes
- React admin dashboard with: Dashboard, Products, Product Detail, Product Search, Suppliers, Sync Management, Settings, Users pages
- Product filtering by supplier, category, brand, price, search, Odoo selection status
- Product select-for-Odoo toggle (individual and bulk)
- Sync trigger UI for products/inventory/pricing/media
- Warehouse-specific inventory display (default: MISSISSAUGA/ON)
- CDN fallback for product images when SOAP Media API authentication fails

## Configured Suppliers
1. **ATC / SanMar Canada** - Working (572 products synced)
   - Endpoint Style: `atc`
   - Base URL: https://edi.atc-apparel.com
   - Status: Active, connection successful

2. **S&S Activewear** - IP Blocked (HTTP 403)
   - Endpoint Style: `ss`
   - Base URL: https://promostandards-ca.ssactivewear.com
   - Status: Active, but server blocks requests from this IP (WAF)
   - **Resolution**: User needs to contact S&S to whitelist server IP

## Testing Results
### December 2025 (PostgreSQL Migration)
- Backend API: 100% pass (21/21 tests)
- Frontend UI: 100% pass (all features working)
- Database: PostgreSQL with 572 products, 18,825 variants, 2 suppliers

### Previous (MongoDB era)
- Backend API: 100% pass (23/23 tests)
- Frontend UI: 90% pass
- Integration: Working (ATC sync successful, S&S blocked by WAF)

## Known Issues
1. **All Supplier APIs CAPTCHA Protected**: PromoStandards API endpoints have bot protection that blocks server-side requests. Users need to contact their supplier to whitelist the server's IP address.
2. ~~**Odoo Integration Incomplete**: Fixed - all fields now syncing correctly (images, inventory, cost)~~
3. ~~**Pricing Sync Bug**: Fixed - was looking for non-existent `price` key instead of `prices` array~~
4. ~~**Inventory Sync Parsing Bug**: Fixed - was not parsing nested `<Quantity><value>` XML structure correctly~~
5. ~~**XML Special Characters**: Fixed - credentials with special characters like # @ & now properly escaped~~
6. **PostgreSQL Non-Persistent**: Preview environment PostgreSQL data resets on restart (platform limitation)

## Prioritized Backlog

### P0 (Critical - Blocked)
- [ ] Get supplier IP whitelisting (ATC, S&S, etc.) - requires user to contact suppliers

### P1 (Important)
- [x] Implement APScheduler for automated periodic syncs ✅ (March 27, 2026)
- [x] Auto-push to Odoo after BulkData sync ✅ (March 27, 2026)
- [x] Lightspeed eSeries Integration (Phase 2A+2B) ✅ (July 24, 2026)
- [ ] Re-sync products after IP whitelisting to get pricing/inventory/media data
- [ ] Refactor server.py into smaller modules (routes/products.py, routes/odoo.py, etc.)

### P2 (Nice to have)
- [x] Add bulk data sync using BulkData SOAP endpoint ✅
- [ ] Image retry mechanism for failed downloads
- [ ] Add product search by text index
- [ ] Add pagination to variants table on detail page
- [ ] Add export functionality (CSV/Excel)
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

### Media
- `GET /api/media_proxy?url={encoded_url}` - Proxy media requests to bypass CDN restrictions

### Odoo
- `POST /api/odoo/push-products` - Push selected products to Odoo
- `POST /api/odoo/test-connection` - Test Odoo connection

## Credentials
- **ATC/SanMar Production**: 
  - Account: `37887`
  - Password: `edi@redleafssports.ca`
  - Media Password: `dE3@tg37`
  - Base URL: `https://edi.atc-apparel.com`
- **ATC Sandbox (Testing)**:
  - Account: `sandbox`
  - Password: `sandbox123`
- **Odoo**: 
  - URL: `https://odoo.redleafssports.ca`
  - Database: `RedLeafsPOC27012026`
  - Username: `talk2shadaan@gmail.com`
  - API Key: `5e15b2949864642da048a991cc19a57b80236be7`
  - Verified: ✅ Connected (Odoo 16.0)

## Testing Results (March 16, 2026)
- Backend API: 100% pass
- Odoo Integration: 100% pass (all fields syncing)
- Media Sync: Working (with public image URLs)
- Inventory Sync: Working (stock.quant model)
- Cost Price Sync: Working (variant-level pricing)
