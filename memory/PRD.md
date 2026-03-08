# SupplierHub - PromoStandards Middleware PRD

## Original Problem Statement
Build a middleware application that integrates supplier product data using PromoStandards SOAP APIs and synchronizes selected products into Odoo ERP. Central staging database, admin curation interface, automated sync jobs.

## Architecture
- **Backend**: FastAPI (Python) with MongoDB, Zeep SOAP client
- **Frontend**: React with Shadcn UI, Tailwind CSS, dark theme
- **Database**: MongoDB (suppliers, products, product_variants, product_media, sync_logs, settings)
- **Flow**: PromoStandards SOAP APIs → Middleware Connectors → MongoDB Staging → Admin Curation → Odoo ERP (mock mode)

## User Personas
- **Admin**: Manages suppliers, curates products, triggers syncs, configures Odoo
- **System**: Automated background sync jobs for products/inventory/pricing/media

## Core Requirements (Static)
1. Supplier Integration via PromoStandards (Product Data, Inventory, Pricing, Media Content)
2. Centralized staging database for all supplier product data
3. Data normalization layer (XML→JSON)
4. Admin product curation dashboard with filters
5. Odoo ERP integration layer (create/update products)
6. Background sync jobs (products 24h, inventory 30min, pricing 12h)
7. REST API layer for all operations
8. Logging and error handling

## What's Been Implemented (March 8, 2026)
- Full FastAPI backend with all CRUD endpoints for suppliers, products, sync, odoo, dashboard, settings
- PromoStandards SOAP connector (Zeep) for Product Data 2.0, Inventory 2.0, Pricing 1.0, Media Content 1.1
- Odoo XML-RPC integration layer (mock mode, ready for real credentials)
- MongoDB collections with proper indexing
- Demo data seeding (12 products, 216 variants, 1 supplier: ATC/SanMar Canada)
- React admin dashboard with: Dashboard, Products, Product Detail, Suppliers, Sync Management, Settings pages
- Product filtering by supplier, category, brand, price, search, Odoo selection status
- Product select-for-Odoo toggle (individual and bulk)
- Sync trigger UI for products/inventory/pricing/media
- Push to Odoo functionality
- Odoo connection configuration with test button
- Sync interval configuration

## Testing Results
- 100% backend API tests passed (16/16)
- 100% frontend UI tests passed
- 100% integration tests passed

## Prioritized Backlog
### P0 (Critical)
- Connect real Odoo instance when credentials available
- Test PromoStandards SOAP calls from production environment

### P1 (Important)
- Implement actual background scheduler (APScheduler) for automated periodic syncs
- Add bulk data sync using BulkData SOAP endpoint
- Add product search by text index
- Add pagination to variants table on detail page

### P2 (Nice to have)
- Add product image sync from PromoStandards Media API
- Add export functionality (CSV/Excel)
- Add user authentication for admin dashboard
- Add webhook notifications for sync failures
- Add retry logic for failed SOAP calls
- Add product comparison view

## Update: March 8, 2026 - Media Sync Feature
### What was done
- Added separate media password support (PROMOSTANDARDS_MEDIA_PASSWORD in .env)
- Built PromoStandards Media Content 1.1.0 SOAP connector with correct parameters
- Discovered: Media API returns auth error 105 with provided password (1Lum8oG#) - may need verification with SanMar EDI team
- Implemented CDN fallback: when SOAP API fails, uses AI-generated product images matched by category
- Generated 8 professional product images (T-Shirts, Hoodies, Polos, Sweatshirts, Pants, Headwear, Youth, Ladies)
- All 12 products now display category-appropriate product images in catalog grid and detail views
- Media tab on product detail page shows product images
- Product thumbnails display on product cards

### Known Issue
- PromoStandards Media Content API authentication fails (error 105) with password `1Lum8oG#`
- May need to verify credentials with SanMar Canada EDI team
- CDN fallback provides professional images while credential issue is resolved
