"""
PostgreSQL Database Connection and Schema Management
"""
import asyncpg
import os
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Database connection pool
pool = None

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db')

async def init_db():
    """Initialize database connection pool and create tables."""
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    
    async with pool.acquire() as conn:
        # Create tables
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(64) PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                full_name VARCHAR(200),
                email VARCHAR(200),
                hashed_password TEXT NOT NULL,
                role VARCHAR(50) DEFAULT 'user',
                approved BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS suppliers (
                id VARCHAR(64) PRIMARY KEY,
                supplier_name VARCHAR(200) NOT NULL,
                supplier_type VARCHAR(100),
                api_base_url TEXT,
                account_number VARCHAR(100),
                password TEXT,
                services JSONB DEFAULT '{}',
                is_active BOOLEAN DEFAULT TRUE,
                last_sync TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id VARCHAR(64) PRIMARY KEY,
                supplier_id VARCHAR(64) REFERENCES suppliers(id) ON DELETE CASCADE,
                supplier_sku VARCHAR(200) NOT NULL,
                product_name TEXT,
                description TEXT,
                brand VARCHAR(200),
                category VARCHAR(200),
                base_price DECIMAL(10,2) DEFAULT 0,
                currency VARCHAR(10) DEFAULT 'CAD',
                is_active BOOLEAN DEFAULT TRUE,
                selected_for_odoo BOOLEAN DEFAULT FALSE,
                odoo_sync_status VARCHAR(50) DEFAULT 'not_selected',
                odoo_product_id VARCHAR(100),
                last_synced TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(supplier_id, supplier_sku)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS product_variants (
                id VARCHAR(64) PRIMARY KEY,
                product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                variant_sku VARCHAR(200) NOT NULL,
                color VARCHAR(200),
                size VARCHAR(100),
                price DECIMAL(10,2) DEFAULT 0,
                inventory INTEGER DEFAULT 0,
                warehouse_inventory JSONB DEFAULT '[]',
                lead_time INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS product_media (
                id VARCHAR(64) PRIMARY KEY,
                product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                media_type VARCHAR(50) DEFAULT 'image',
                url TEXT NOT NULL,
                description TEXT,
                is_primary BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sync_logs (
                id VARCHAR(64) PRIMARY KEY,
                supplier_id VARCHAR(64),
                supplier_name VARCHAR(200),
                sync_type VARCHAR(50) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                message TEXT,
                progress INTEGER DEFAULT 0,
                total_items INTEGER DEFAULT 0,
                processed_items INTEGER DEFAULT 0,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id VARCHAR(64) PRIMARY KEY,
                odoo_url TEXT,
                odoo_db VARCHAR(200),
                odoo_username VARCHAR(200),
                odoo_api_key TEXT,
                odoo_connected BOOLEAN DEFAULT FALSE,
                sync_products_interval_hours INTEGER DEFAULT 24,
                sync_inventory_interval_minutes INTEGER DEFAULT 30,
                sync_pricing_interval_hours INTEGER DEFAULT 12,
                auto_sync_enabled BOOLEAN DEFAULT FALSE,
                preferred_warehouse VARCHAR(200) DEFAULT 'MISSISSAUGA/ON',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes for better performance
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_sku ON products(supplier_sku)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_variants_sku ON product_variants(variant_sku)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_media_product ON product_media(product_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_sync_logs_supplier ON sync_logs(supplier_id)')
        
        # Insert default settings if not exists
        await conn.execute('''
            INSERT INTO settings (id, odoo_url, odoo_db, odoo_username, odoo_api_key)
            VALUES ('system_settings', '', '', '', '')
            ON CONFLICT (id) DO NOTHING
        ''')
        
        # Create default admin user if not exists
        from auth import get_password_hash
        admin_hash = get_password_hash('admin')
        await conn.execute('''
            INSERT INTO users (id, username, full_name, email, hashed_password, role, approved)
            VALUES ($1, 'admin', 'Administrator', 'admin@example.com', $2, 'admin', TRUE)
            ON CONFLICT (username) DO NOTHING
        ''', 'admin-user-id', admin_hash)
        
        logger.info("Database tables created successfully")

async def close_db():
    """Close database connection pool."""
    global pool
    if pool:
        await pool.close()

def get_pool():
    """Get the database connection pool."""
    return pool

@asynccontextmanager
async def get_connection():
    """Context manager for database connections."""
    async with pool.acquire() as conn:
        yield conn
