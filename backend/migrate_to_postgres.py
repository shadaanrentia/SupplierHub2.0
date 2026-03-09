"""
Migration script: MongoDB to PostgreSQL
Run this once to migrate existing data.
"""
import asyncio
import asyncpg
import json
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

MONGO_URL = "mongodb://localhost:27017"
MONGO_DB = "test_database"
PG_URL = "postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db"

def parse_datetime(val):
    """Convert various datetime formats to naive datetime object or None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        # Make naive by removing timezone info
        return val.replace(tzinfo=None)
    if isinstance(val, str):
        try:
            # Handle ISO format with timezone
            dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
            return dt.replace(tzinfo=None)
        except:
            return None
    return None

async def migrate():
    # Connect to both databases
    mongo_client = AsyncIOMotorClient(MONGO_URL)
    mongo_db = mongo_client[MONGO_DB]
    
    pg_pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=5)
    
    async with pg_pool.acquire() as conn:
        # Migrate users
        print("Migrating users...")
        users = await mongo_db.users.find({}, {"_id": 0}).to_list(1000)
        for user in users:
            try:
                await conn.execute('''
                    INSERT INTO users (id, username, full_name, email, hashed_password, role, approved, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (username) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        email = EXCLUDED.email,
                        role = EXCLUDED.role,
                        approved = EXCLUDED.approved
                ''', user.get('id', ''), user.get('username', ''), user.get('full_name', user.get('name', '')),
                    user.get('email', ''), user.get('hashed_password', user.get('password', '')), user.get('role', 'user'),
                    user.get('approved', user.get('status') == 'approved'), 
                    parse_datetime(user.get('created_at')), parse_datetime(user.get('updated_at')))
            except Exception as e:
                print(f"  User error: {e}")
        print(f"  Migrated {len(users)} users")
        
        # Migrate suppliers
        print("Migrating suppliers...")
        suppliers = await mongo_db.suppliers.find({}, {"_id": 0}).to_list(100)
        for supplier in suppliers:
            try:
                await conn.execute('''
                    INSERT INTO suppliers (id, supplier_name, supplier_type, api_base_url, account_number, password, services, is_active, last_sync, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO UPDATE SET
                        supplier_name = EXCLUDED.supplier_name,
                        services = EXCLUDED.services,
                        is_active = EXCLUDED.is_active
                ''', supplier.get('id', ''), supplier.get('supplier_name', ''), supplier.get('supplier_type', ''),
                    supplier.get('api_base_url', ''), supplier.get('account_number', ''), supplier.get('password', ''),
                    json.dumps(supplier.get('services', {})), supplier.get('is_active', True),
                    parse_datetime(supplier.get('last_sync')), parse_datetime(supplier.get('created_at')), 
                    parse_datetime(supplier.get('updated_at')))
            except Exception as e:
                print(f"  Supplier error: {e}")
        print(f"  Migrated {len(suppliers)} suppliers")
        
        # Migrate products
        print("Migrating products...")
        products = await mongo_db.products.find({}, {"_id": 0}).to_list(10000)
        migrated_products = 0
        for product in products:
            try:
                await conn.execute('''
                    INSERT INTO products (id, supplier_id, supplier_sku, product_name, description, brand, category, base_price, currency, is_active, selected_for_odoo, odoo_sync_status, odoo_product_id, last_synced, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    ON CONFLICT (supplier_id, supplier_sku) DO UPDATE SET
                        product_name = EXCLUDED.product_name,
                        description = EXCLUDED.description,
                        brand = EXCLUDED.brand,
                        category = EXCLUDED.category,
                        base_price = EXCLUDED.base_price
                ''', product.get('id', ''), product.get('supplier_id', ''), product.get('supplier_sku', ''),
                    product.get('product_name', ''), product.get('description', ''), product.get('brand', ''),
                    product.get('category', ''), float(product.get('base_price', 0) or 0), product.get('currency', 'CAD'),
                    product.get('is_active', True), product.get('selected_for_odoo', False),
                    product.get('odoo_sync_status', 'not_selected'), product.get('odoo_product_id'),
                    parse_datetime(product.get('last_synced')), parse_datetime(product.get('created_at')), 
                    parse_datetime(product.get('updated_at')))
                migrated_products += 1
            except Exception as e:
                print(f"  Product error ({product.get('supplier_sku')}): {e}")
        print(f"  Migrated {migrated_products} products")
        
        # Migrate product variants
        print("Migrating product variants...")
        variants = await mongo_db.product_variants.find({}, {"_id": 0}).to_list(100000)
        migrated_variants = 0
        for variant in variants:
            try:
                await conn.execute('''
                    INSERT INTO product_variants (id, product_id, variant_sku, color, size, price, inventory, warehouse_inventory, lead_time, is_active, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (id) DO UPDATE SET
                        price = EXCLUDED.price,
                        inventory = EXCLUDED.inventory,
                        warehouse_inventory = EXCLUDED.warehouse_inventory
                ''', variant.get('id', ''), variant.get('product_id', ''), variant.get('variant_sku', ''),
                    variant.get('color', ''), variant.get('size', ''), float(variant.get('price', 0) or 0),
                    int(variant.get('inventory', 0) or 0), json.dumps(variant.get('warehouse_inventory', [])),
                    int(variant.get('lead_time', 0) or 0), variant.get('is_active', True),
                    parse_datetime(variant.get('created_at')), parse_datetime(variant.get('updated_at')))
                migrated_variants += 1
            except Exception as e:
                print(f"  Variant error: {e}")
        print(f"  Migrated {migrated_variants} variants")
        
        # Migrate product media
        print("Migrating product media...")
        media = await mongo_db.product_media.find({}, {"_id": 0}).to_list(100000)
        migrated_media = 0
        for m in media:
            try:
                await conn.execute('''
                    INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (id) DO NOTHING
                ''', m.get('id', ''), m.get('product_id', ''), m.get('media_type', 'image'),
                    m.get('url', ''), m.get('description', ''), m.get('is_primary', False),
                    parse_datetime(m.get('created_at')))
                migrated_media += 1
            except Exception as e:
                pass
        print(f"  Migrated {migrated_media} media items")
        
        # Migrate sync logs
        print("Migrating sync logs...")
        logs = await mongo_db.sync_logs.find({}, {"_id": 0}).to_list(1000)
        for log in logs:
            try:
                await conn.execute('''
                    INSERT INTO sync_logs (id, supplier_id, supplier_name, sync_type, status, message, progress, total_items, processed_items, start_time, end_time, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (id) DO NOTHING
                ''', log.get('id', ''), log.get('supplier_id', ''), log.get('supplier_name', ''),
                    log.get('sync_type', ''), log.get('status', ''), log.get('message', ''),
                    int(log.get('progress', 0) or 0), int(log.get('total_items', 0) or 0),
                    int(log.get('processed_items', 0) or 0), parse_datetime(log.get('start_time')), 
                    parse_datetime(log.get('end_time')), parse_datetime(log.get('created_at')))
            except Exception as e:
                pass
        print(f"  Migrated {len(logs)} sync logs")
        
        # Migrate settings
        print("Migrating settings...")
        settings = await mongo_db.settings.find_one({"id": "system_settings"}, {"_id": 0})
        if settings:
            try:
                await conn.execute('''
                    INSERT INTO settings (id, odoo_url, odoo_db, odoo_username, odoo_api_key, odoo_connected, sync_products_interval_hours, sync_inventory_interval_minutes, sync_pricing_interval_hours, auto_sync_enabled, preferred_warehouse)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO UPDATE SET
                        odoo_url = EXCLUDED.odoo_url,
                        odoo_db = EXCLUDED.odoo_db,
                        preferred_warehouse = EXCLUDED.preferred_warehouse
                ''', 'system_settings', settings.get('odoo_url', ''), settings.get('odoo_db', ''),
                    settings.get('odoo_username', ''), settings.get('odoo_api_key', ''),
                    settings.get('odoo_connected', False), settings.get('sync_products_interval_hours', 24),
                    settings.get('sync_inventory_interval_minutes', 30), settings.get('sync_pricing_interval_hours', 12),
                    settings.get('auto_sync_enabled', False), settings.get('preferred_warehouse', 'MISSISSAUGA/ON'))
                print("  Migrated settings")
            except Exception as e:
                print(f"  Settings error: {e}")
    
    await pg_pool.close()
    mongo_client.close()
    print("\nMigration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
