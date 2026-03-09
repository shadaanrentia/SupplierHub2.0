#!/usr/bin/env python3
"""
Database initialization and seeding script for SupplierHub.
Run this script to set up initial data after a fresh deployment.

Usage:
    python scripts/init_db.py [--seed-demo]

Options:
    --seed-demo    Add demo supplier and sample products
"""

import asyncio
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'backend'))

from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from datetime import datetime, timezone
import uuid

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / 'backend' / '.env')

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def new_id():
    return str(uuid.uuid4())

async def init_database():
    """Initialize database with indexes and default admin user."""
    
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'supplierhub')
    
    print(f"Connecting to MongoDB: {mongo_url}")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    print("Creating indexes...")
    
    # Suppliers
    await db.suppliers.create_index("id", unique=True)
    
    # Products
    await db.products.create_index("id", unique=True)
    await db.products.create_index("supplier_id")
    await db.products.create_index("supplier_sku")
    await db.products.create_index("brand")
    await db.products.create_index("category")
    await db.products.create_index("selected_for_odoo")
    await db.products.create_index("sync_status")
    await db.products.create_index("base_price")
    
    # Product Variants
    await db.product_variants.create_index("id", unique=True)
    await db.product_variants.create_index("product_id")
    await db.product_variants.create_index("variant_sku")
    
    # Product Media
    await db.product_media.create_index("product_id")
    
    # Sync Logs
    await db.sync_logs.create_index("started_at")
    await db.sync_logs.create_index("supplier_id")
    await db.sync_logs.create_index("status")
    
    # Users
    await db.users.create_index("id", unique=True)
    await db.users.create_index("username", unique=True)
    await db.users.create_index("email", unique=True)
    
    print("Indexes created successfully!")
    
    # Create default admin user
    admin_exists = await db.users.find_one({"username": "admin"})
    if not admin_exists:
        print("Creating default admin user...")
        await db.users.insert_one({
            "id": new_id(),
            "name": "Shadaan Rentia",
            "email": "admin@supplierhub.com",
            "username": "admin",
            "password": pwd_context.hash("admin"),
            "role": "admin",
            "status": "approved",
            "created_at": utc_now(),
            "updated_at": utc_now()
        })
        print("Default admin user created: admin/admin")
        print("WARNING: Change the default password immediately!")
    else:
        print("Admin user already exists, skipping...")
    
    # Create default settings
    settings_exist = await db.settings.find_one({"id": "system_settings"})
    if not settings_exist:
        print("Creating default settings...")
        await db.settings.insert_one({
            "id": "system_settings",
            "odoo_url": "",
            "odoo_db": "",
            "odoo_username": "",
            "odoo_password": "",
            "sync_products_interval": 24,
            "sync_inventory_interval": 0.5,
            "sync_pricing_interval": 12,
            "created_at": utc_now(),
            "updated_at": utc_now()
        })
        print("Default settings created!")
    
    print("\nDatabase initialization complete!")
    return db

async def seed_demo_data(db):
    """Add demo supplier for testing."""
    
    print("\nSeeding demo data...")
    
    # Check if demo supplier exists
    demo_supplier = await db.suppliers.find_one({"supplier_name": "Demo Supplier"})
    if demo_supplier:
        print("Demo supplier already exists, skipping...")
        return
    
    supplier_id = new_id()
    await db.suppliers.insert_one({
        "id": supplier_id,
        "supplier_name": "ATC / SanMar Canada",
        "api_base_url": "https://edi.atc-apparel.com",
        "account_number": "37887",
        "password": "edi@redleafssports.ca",  # Demo credentials
        "media_password": "",
        "endpoint_style": "atc",
        "use_uat": False,
        "services": {
            "product_data": "https://edi.atc-apparel.com/pstd/productdata2.0/ProductDataServiceV2.php",
            "inventory": "https://edi.atc-apparel.com/pstd/inventory2.0/InventoryServiceV2.php",
            "pricing": "https://edi.atc-apparel.com/pstd/productpricingconfiguration/PricingAndConfigurationService.php",
            "media": "https://edi.atc-apparel.com/pstd/mediacontent1.1/MediaContentService.php"
        },
        "status": "active",
        "products_count": 0,
        "last_sync_time": None,
        "created_at": utc_now(),
        "updated_at": utc_now()
    })
    
    print(f"Demo supplier created: ATC / SanMar Canada")
    print("You can now sync products from the Sync Management page.")

async def main():
    seed_demo = "--seed-demo" in sys.argv
    
    db = await init_database()
    
    if seed_demo:
        await seed_demo_data(db)
    
    print("\nSetup complete! You can now start the application.")
    print("Login with: admin / admin")

if __name__ == "__main__":
    asyncio.run(main())
