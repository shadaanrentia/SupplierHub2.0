from fastapi import FastAPI, APIRouter, HTTPException, Query, BackgroundTasks, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import asyncpg
import os
import logging
import uuid
import json
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
import jwt

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# PostgreSQL Configuration
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://supplierhub:supplierhub_pass@localhost:5432/supplierhub_db')
pool = None

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'supplierhub-secret-key-change-in-production')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

app = FastAPI(title="SupplierHub - PromoStandards Middleware")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==================== HELPERS ====================
def utc_now():
    """Return current UTC time as naive datetime (no timezone info) for PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def utc_now_str():
    return datetime.now(timezone.utc).isoformat()

def new_id():
    return str(uuid.uuid4())

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def row_to_dict(row):
    """Convert asyncpg Record to dict, handling JSONB fields."""
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif k in ('services', 'warehouse_inventory'):
            # Handle JSONB - could be dict, list, or string
            if isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[k] = {} if k == 'services' else []
            elif v is None:
                d[k] = {} if k == 'services' else []
    return d

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token")
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, username, full_name, email, role, approved FROM users WHERE id = $1", user_id)
            if not row:
                raise HTTPException(401, "User not found")
            user = row_to_dict(row)
            if not user.get("approved"):
                raise HTTPException(403, "Account not approved")
            return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

async def get_admin_user(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# ==================== AUTH MODELS ====================
class UserRegister(BaseModel):
    name: str
    email: str
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserApproval(BaseModel):
    user_id: str
    approved: bool

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


# ==================== MODELS ====================
class SupplierCreate(BaseModel):
    supplier_name: str
    api_base_url: str = ""
    account_number: str = ""
    password: str = ""
    media_password: str = ""
    use_uat: bool = False
    services: Dict[str, str] = {}
    endpoint_style: str = ""
    bulk_data_url: str = ""

class SupplierUpdate(BaseModel):
    supplier_name: Optional[str] = None
    api_base_url: Optional[str] = None
    account_number: Optional[str] = None
    password: Optional[str] = None
    media_password: Optional[str] = None
    use_uat: Optional[bool] = None
    services: Optional[Dict[str, str]] = None
    endpoint_style: Optional[str] = None
    status: Optional[str] = None
    bulk_data_url: Optional[str] = None

class ProductSelectRequest(BaseModel):
    product_id: str
    selected: bool

class BulkSelectRequest(BaseModel):
    product_ids: List[str]
    selected: bool

class SettingsUpdate(BaseModel):
    sync_products_interval_hours: Optional[int] = None
    sync_inventory_interval_minutes: Optional[int] = None
    sync_pricing_interval_hours: Optional[int] = None
    auto_sync_enabled: Optional[bool] = None
    odoo_url: Optional[str] = None
    odoo_db: Optional[str] = None
    odoo_username: Optional[str] = None
    odoo_api_key: Optional[str] = None
    preferred_warehouse: Optional[str] = None
    markup_percentage: Optional[float] = None
    auto_push_to_odoo: Optional[bool] = None
    lightspeed_api_key: Optional[str] = None
    lightspeed_api_secret: Optional[str] = None
    lightspeed_cluster: Optional[str] = None
    lightspeed_language: Optional[str] = None


# ==================== STARTUP & SHUTDOWN ====================
@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    
    async with pool.acquire() as conn:
        # Create tables
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(64) PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                full_name VARCHAR(200),
                email VARCHAR(200) UNIQUE,
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
                media_password TEXT,
                use_uat BOOLEAN DEFAULT FALSE,
                endpoint_style VARCHAR(50),
                services JSONB DEFAULT '{}',
                bulk_data_url TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                status VARCHAR(50) DEFAULT 'active',
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
                image_base64 TEXT,
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
                markup_percentage DECIMAL(5,2) DEFAULT 40.00,
                default_warehouse VARCHAR(200) DEFAULT 'Main Warehouse',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_supplier ON products(supplier_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_sku ON products(supplier_sku)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_media_product ON product_media(product_id)')
        
        # Create odoo_categories table
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS odoo_categories (
                id VARCHAR(64) PRIMARY KEY,
                odoo_category_id INTEGER NOT NULL UNIQUE,
                category_name VARCHAR(300) NOT NULL,
                parent_category VARCHAR(300),
                parent_id INTEGER,
                is_selected BOOLEAN DEFAULT FALSE,
                last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create category_mapping table
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS category_mapping (
                id VARCHAR(64) PRIMARY KEY,
                supplier_category_name VARCHAR(300) NOT NULL UNIQUE,
                supplier_category_id VARCHAR(100),
                odoo_category_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create product_sync_status table for tracking sync progress
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS product_sync_status (
                id VARCHAR(64) PRIMARY KEY,
                product_id VARCHAR(64) REFERENCES products(id) ON DELETE CASCADE,
                supplier_id VARCHAR(64),
                odoo_product_id VARCHAR(100),
                odoo_template_id INTEGER,
                sync_status VARCHAR(50) DEFAULT 'pending',
                cost_price DECIMAL(10,2),
                sale_price DECIMAL(10,2),
                mapped_category_id INTEGER,
                variants_count INTEGER DEFAULT 0,
                images_count INTEGER DEFAULT 0,
                validation_errors JSONB DEFAULT '[]',
                last_sync_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(product_id)
            )
        ''')
        
        # Add columns to products table if not exists
        await conn.execute('''
            ALTER TABLE products ADD COLUMN IF NOT EXISTS preprocessing_status VARCHAR(50) DEFAULT 'pending'
        ''')
        await conn.execute('''
            ALTER TABLE products ADD COLUMN IF NOT EXISTS calculated_sale_price DECIMAL(10,2)
        ''')
        
        # Add columns to settings if not exists  
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS markup_percentage DECIMAL(5,2) DEFAULT 40.00
        ''')
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS default_warehouse VARCHAR(200) DEFAULT 'Main Warehouse'
        ''')
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS auto_push_to_odoo BOOLEAN DEFAULT FALSE
        ''')
        
        # Lightspeed eCom settings columns
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_api_key VARCHAR(500) DEFAULT ''
        ''')
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_api_secret VARCHAR(500) DEFAULT ''
        ''')
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_cluster VARCHAR(10) DEFAULT 'us1'
        ''')
        await conn.execute('''
            ALTER TABLE settings ADD COLUMN IF NOT EXISTS lightspeed_language VARCHAR(10) DEFAULT 'en'
        ''')
        
        # Add lightspeed_category_id to category_mapping
        await conn.execute('''
            ALTER TABLE category_mapping ADD COLUMN IF NOT EXISTS lightspeed_category_id INTEGER
        ''')
        
        # Add destination platform tracking to products
        await conn.execute('''
            ALTER TABLE products ADD COLUMN IF NOT EXISTS lightspeed_sync_status VARCHAR(50) DEFAULT 'pending'
        ''')
        await conn.execute('''
            ALTER TABLE products ADD COLUMN IF NOT EXISTS lightspeed_product_id VARCHAR(100)
        ''')
        await conn.execute('''
            ALTER TABLE products ADD COLUMN IF NOT EXISTS selected_for_lightspeed BOOLEAN DEFAULT FALSE
        ''')
        
        # Create default admin user
        admin = await conn.fetchrow("SELECT id FROM users WHERE username = 'admin'")
        if not admin:
            await conn.execute('''
                INSERT INTO users (id, username, full_name, email, hashed_password, role, approved)
                VALUES ($1, 'admin', 'Shadaan Rentia', 'admin@supplierhub.com', $2, 'admin', TRUE)
            ''', new_id(), hash_password('admin'))
            logger.info("Default admin user created: admin/admin")
        
        # Create default settings
        settings = await conn.fetchrow("SELECT id FROM settings WHERE id = 'system_settings'")
        if not settings:
            await conn.execute('''
                INSERT INTO settings (id, odoo_url, odoo_db, odoo_username, odoo_api_key, preferred_warehouse)
                VALUES ('system_settings', '', '', '', '', 'MISSISSAUGA/ON')
            ''')
    
    logger.info("PostgreSQL database initialized")

    # Initialize and apply scheduler
    from scheduler import init_scheduler, apply_schedule_from_settings
    init_scheduler(pool)
    await apply_schedule_from_settings()

@app.on_event("shutdown")
async def shutdown():
    global pool
    from scheduler import shutdown_scheduler
    shutdown_scheduler()
    if pool:
        await pool.close()


# ==================== CORS ====================
origins = os.environ.get('CORS_ORIGINS', '*')
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins.split(',') if origins != '*' else ['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== AUTH ROUTES ====================
@api_router.post("/auth/login")
async def login(data: UserLogin):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, username, full_name, email, hashed_password, role, approved FROM users WHERE username = $1", data.username)
        if not row:
            raise HTTPException(401, "Invalid credentials")
        user = row_to_dict(row)
        if not verify_password(data.password, user['hashed_password']):
            raise HTTPException(401, "Invalid credentials")
        if not user.get('approved'):
            raise HTTPException(403, "Account not approved")
        token = create_access_token(user['id'], user['role'])
        return {"token": token, "user": {"id": user['id'], "username": user['username'], "full_name": user['full_name'], "email": user['email'], "role": user['role']}}

@api_router.post("/users/register")
async def register(data: UserRegister):
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE username = $1 OR email = $2", data.username, data.email)
        if existing:
            raise HTTPException(400, "Username or email already exists")
        user_id = new_id()
        await conn.execute('''
            INSERT INTO users (id, username, full_name, email, hashed_password, role, approved, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, 'user', FALSE, $6, $6)
        ''', user_id, data.username, data.name, data.email, hash_password(data.password), utc_now())
        return {"message": "Registration successful. Awaiting admin approval.", "user_id": user_id}

@api_router.get("/users")
async def get_users(user: dict = Depends(get_admin_user)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username, full_name, email, role, approved, created_at FROM users ORDER BY created_at DESC")
        return {"users": [row_to_dict(r) for r in rows]}

class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str
    role: str = "user"

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None

class PasswordReset(BaseModel):
    new_password: str

@api_router.post("/users")
async def create_user(data: UserCreate, admin: dict = Depends(get_admin_user)):
    """Create a new user (admin only)."""
    if not data.username or not data.password:
        raise HTTPException(400, "Username and password are required")
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE username = $1", data.username)
        if existing:
            raise HTTPException(400, "Username already exists")
        
        user_id = new_id()
        await conn.execute("""
            INSERT INTO users (id, username, email, hashed_password, role, approved, created_at)
            VALUES ($1, $2, $3, $4, $5, TRUE, $6)
        """, user_id, data.username, data.email, hash_password(data.password), data.role, utc_now())
        
        return {"status": "created", "id": user_id}

@api_router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, admin: dict = Depends(get_admin_user)):
    """Update user details (admin only)."""
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not existing:
            raise HTTPException(404, "User not found")
        
        update_fields = []
        values = []
        param_idx = 1
        
        if data.username:
            update_fields.append(f"username = ${param_idx}")
            values.append(data.username)
            param_idx += 1
        if data.email is not None:
            update_fields.append(f"email = ${param_idx}")
            values.append(data.email)
            param_idx += 1
        if data.role:
            update_fields.append(f"role = ${param_idx}")
            values.append(data.role)
            param_idx += 1
        if data.password:
            if len(data.password) < 6:
                raise HTTPException(400, "Password must be at least 6 characters")
            update_fields.append(f"hashed_password = ${param_idx}")
            values.append(hash_password(data.password))
            param_idx += 1
        
        if update_fields:
            update_fields.append(f"updated_at = ${param_idx}")
            values.append(utc_now())
            param_idx += 1
            values.append(user_id)
            
            query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ${param_idx}"
            await conn.execute(query, *values)
        
        return {"status": "updated"}

@api_router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, data: PasswordReset, admin: dict = Depends(get_admin_user)):
    """Reset a user's password (admin only)."""
    if len(data.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET hashed_password = $1, updated_at = $2 WHERE id = $3",
            hash_password(data.new_password), utc_now(), user_id
        )
        if result == "UPDATE 0":
            raise HTTPException(404, "User not found")
        return {"status": "password_reset"}

@api_router.put("/users/{user_id}/approve")
async def approve_user(user_id: str, data: UserApproval, admin: dict = Depends(get_admin_user)):
    async with pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET approved = $1, updated_at = $2 WHERE id = $3", data.approved, utc_now(), user_id)
        if result == "UPDATE 0":
            raise HTTPException(404, "User not found")
        return {"status": "updated", "approved": data.approved}

@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1 AND role != 'admin'", user_id)
        if result == "DELETE 0":
            raise HTTPException(404, "User not found or cannot delete admin")
        return {"status": "deleted"}

@api_router.get("/users/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user


# ==================== SUPPLIERS ====================
@api_router.get("/suppliers")
async def get_suppliers(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM suppliers ORDER BY supplier_name")
        suppliers = []
        for row in rows:
            s = row_to_dict(row)
            if s.get('password'):
                s['password'] = '***'
            if s.get('media_password'):
                s['media_password'] = '***'
            suppliers.append(s)
        return {"suppliers": suppliers}

@api_router.post("/suppliers")
async def create_supplier(data: SupplierCreate, user: dict = Depends(get_admin_user)):
    supplier_id = new_id()
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO suppliers (id, supplier_name, api_base_url, account_number, password, media_password, use_uat, endpoint_style, services, bulk_data_url, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'active', $11, $11)
        ''', supplier_id, data.supplier_name, data.api_base_url, data.account_number, data.password, data.media_password, data.use_uat, data.endpoint_style, json.dumps(data.services), data.bulk_data_url, utc_now())
        return {"id": supplier_id, "message": "Supplier created"}

@api_router.get("/suppliers/{supplier_id}")
async def get_supplier(supplier_id: str, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        s = row_to_dict(row)
        if s.get('password'):
            s['password'] = '***'
        if s.get('media_password'):
            s['media_password'] = '***'
        return s

@api_router.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, data: SupplierUpdate, user: dict = Depends(get_admin_user)):
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not existing:
            raise HTTPException(404, "Supplier not found")
        
        update_fields = []
        values = []
        param_idx = 1
        
        if data.supplier_name is not None:
            update_fields.append(f"supplier_name = ${param_idx}")
            values.append(data.supplier_name)
            param_idx += 1
        if data.api_base_url is not None:
            update_fields.append(f"api_base_url = ${param_idx}")
            values.append(data.api_base_url)
            param_idx += 1
        if data.account_number is not None:
            update_fields.append(f"account_number = ${param_idx}")
            values.append(data.account_number)
            param_idx += 1
        if data.password is not None and data.password != '***':
            update_fields.append(f"password = ${param_idx}")
            values.append(data.password)
            param_idx += 1
        if data.media_password is not None and data.media_password != '***':
            update_fields.append(f"media_password = ${param_idx}")
            values.append(data.media_password)
            param_idx += 1
        if data.use_uat is not None:
            update_fields.append(f"use_uat = ${param_idx}")
            values.append(data.use_uat)
            param_idx += 1
        if data.endpoint_style is not None:
            update_fields.append(f"endpoint_style = ${param_idx}")
            values.append(data.endpoint_style)
            param_idx += 1
        if data.services is not None:
            update_fields.append(f"services = ${param_idx}")
            values.append(json.dumps(data.services))
            param_idx += 1
        if data.status is not None:
            update_fields.append(f"status = ${param_idx}")
            values.append(data.status)
            param_idx += 1
        if data.bulk_data_url is not None:
            update_fields.append(f"bulk_data_url = ${param_idx}")
            values.append(data.bulk_data_url)
            param_idx += 1
        
        update_fields.append(f"updated_at = ${param_idx}")
        values.append(utc_now())
        param_idx += 1
        
        values.append(supplier_id)
        
        if update_fields:
            query = f"UPDATE suppliers SET {', '.join(update_fields)} WHERE id = ${param_idx}"
            await conn.execute(query, *values)
        
        return {"status": "updated"}

@api_router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str, user: dict = Depends(get_admin_user)):
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM suppliers WHERE id = $1", supplier_id)
        if result == "DELETE 0":
            raise HTTPException(404, "Supplier not found")
        return {"status": "deleted"}

@api_router.post("/suppliers/{supplier_id}/test")
async def test_supplier(supplier_id: str, user: dict = Depends(get_current_user)):
    from promostandards import PromoStandardsConnector
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier = row_to_dict(row)
        connector = PromoStandardsConnector(supplier)
        result = connector.test_connection()
        return result


@api_router.get("/suppliers/{supplier_id}/catalog")
async def search_supplier_catalog(
    supplier_id: str,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    get_details: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """Search the supplier's catalog directly via PromoStandards API.
    
    By default returns just SKUs from GetProductSellable (fast).
    Set get_details=true to fetch full product details (slower).
    """
    from promostandards import PromoStandardsConnector
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier = row_to_dict(row)
        
        # Get existing product SKUs to mark which are already imported
        existing_rows = await conn.fetch("SELECT supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
        existing_skus = set(r['supplier_sku'] for r in existing_rows)
    
    connector = PromoStandardsConnector(supplier)
    
    # Get all sellable products from the supplier
    result = connector.get_sellable_products()
    if not result.get('success'):
        raise HTTPException(500, f"Failed to fetch catalog: {result.get('error')}")
    
    all_products = result.get('products', [])
    
    # Get unique product IDs
    unique_skus = list(set(p['product_id'] for p in all_products))
    total_count = len(unique_skus)
    
    # Filter by search query if provided
    if search:
        search_lower = search.lower()
        unique_skus = [sku for sku in unique_skus if search_lower in sku.lower()]
    
    # Limit results
    unique_skus = unique_skus[:limit]
    
    # Build product list
    products = []
    
    if get_details:
        # Fetch full product details for each SKU (slower)
        for sku in unique_skus:
            product_data = connector.get_product(sku)
            if product_data.get('success') and product_data.get('product'):
                p = product_data['product']
                products.append({
                    'supplier_sku': sku,
                    'product_name': p.get('name', ''),
                    'description': p.get('description', ''),
                    'brand': p.get('brand', ''),
                    'category': p.get('category', ''),
                    'variant_count': len(p.get('variants', [])),
                    'is_imported': sku in existing_skus
                })
    else:
        # Return just SKUs (fast)
        for sku in unique_skus:
            products.append({
                'supplier_sku': sku,
                'product_name': '',
                'description': '',
                'brand': '',
                'category': '',
                'variant_count': 0,
                'is_imported': sku in existing_skus
            })
    
    return {
        'products': products,
        'total_in_catalog': total_count,
        'showing': len(products),
        'supplier_name': supplier.get('supplier_name', '')
    }


@api_router.post("/suppliers/{supplier_id}/import-product/{product_sku}")
async def import_product_from_catalog(
    supplier_id: str,
    product_sku: str,
    user: dict = Depends(get_current_user)
):
    """Import a single product from the supplier's catalog into the database."""
    from promostandards import PromoStandardsConnector
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier = row_to_dict(row)
        
        # Check if already imported
        existing = await conn.fetchrow("SELECT id FROM products WHERE supplier_id = $1 AND supplier_sku = $2", supplier_id, product_sku)
        if existing:
            return {"success": False, "message": "Product already imported", "product_id": existing['id']}
    
    connector = PromoStandardsConnector(supplier)
    
    # Fetch product details
    product_data = connector.get_product(product_sku)
    if not product_data.get('success') or not product_data.get('product'):
        raise HTTPException(500, f"Failed to fetch product: {product_data.get('error', 'Unknown error')}")
    
    p = product_data['product']
    product_id = new_id()
    
    async with pool.acquire() as conn:
        # Insert product
        await conn.execute('''
            INSERT INTO products (id, supplier_id, supplier_sku, product_name, description, brand, category, base_price, last_synced, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9, $9)
        ''', product_id, supplier_id, product_sku, p.get('product_name', ''), p.get('description', ''),
            p.get('brand', ''), p.get('category', ''), float(p.get('price', 0) or 0), utc_now())
        
        # Insert variants
        variants_added = 0
        for v in p.get('variants', []):
            variant_id = new_id()
            await conn.execute('''
                INSERT INTO product_variants (id, product_id, variant_sku, color, size, price, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
            ''', variant_id, product_id, v.get('variant_sku', ''), v.get('color', ''), v.get('size', ''),
                float(v.get('price', 0) or 0), utc_now())
            variants_added += 1
    
    return {
        "success": True,
        "message": f"Imported product with {variants_added} variants",
        "product_id": product_id,
        "product_name": p.get('product_name', ''),
        "variants_added": variants_added
    }


# ==================== PRODUCTS ====================
@api_router.get("/products")
async def get_products(
    supplier_id: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    search: Optional[str] = None,
    selected: Optional[bool] = None,
    odoo_status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user)
):
    async with pool.acquire() as conn:
        conditions = []
        values = []
        param_idx = 1
        
        if supplier_id:
            conditions.append(f"supplier_id = ${param_idx}")
            values.append(supplier_id)
            param_idx += 1
        if category and category != "all":
            conditions.append(f"category = ${param_idx}")
            values.append(category)
            param_idx += 1
        if brand and brand != "all":
            conditions.append(f"brand = ${param_idx}")
            values.append(brand)
            param_idx += 1
        if search:
            conditions.append(f"(product_name ILIKE ${param_idx} OR supplier_sku ILIKE ${param_idx})")
            values.append(f"%{search}%")
            param_idx += 1
        if selected is not None:
            conditions.append(f"selected_for_odoo = ${param_idx}")
            values.append(selected)
            param_idx += 1
        if odoo_status and odoo_status != "all":
            conditions.append(f"odoo_sync_status = ${param_idx}")
            values.append(odoo_status)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Get total count
        count_query = f"SELECT COUNT(*) FROM products WHERE {where_clause}"
        total = await conn.fetchval(count_query, *values)
        
        # Get products with pagination
        offset = (page - 1) * limit
        products_query = f"""
            SELECT p.*, s.supplier_name,
                   (SELECT COUNT(*) FROM product_variants WHERE product_id = p.id) as variant_count
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE {where_clause}
            ORDER BY p.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        values.extend([limit, offset])
        
        rows = await conn.fetch(products_query, *values)
        products = [row_to_dict(r) for r in rows]
        
        return {
            "products": products,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

@api_router.get("/products/categories")
async def get_categories(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return {"categories": [r['category'] for r in rows]}

@api_router.get("/products/brands")
async def get_brands(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != '' ORDER BY brand")
        return {"brands": [r['brand'] for r in rows]}

@api_router.get("/products/{product_id}")
async def get_product(product_id: str, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.*, s.supplier_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = $1
        """, product_id)
        if not row:
            raise HTTPException(404, "Product not found")
        product = row_to_dict(row)
        
        # Get variants
        variant_rows = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1 ORDER BY variant_sku", product_id)
        variants = [row_to_dict(v) for v in variant_rows]
        
        # Get media
        media_rows = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product_id)
        media = [row_to_dict(m) for m in media_rows]
        
        # Get preferred warehouse from settings
        settings = await conn.fetchrow("SELECT preferred_warehouse FROM settings WHERE id = 'system_settings'")
        preferred_warehouse = settings['preferred_warehouse'] if settings else ""
        
        # Update variants with warehouse-specific inventory
        for v in variants:
            warehouse_inventory = v.get('warehouse_inventory', [])
            if isinstance(warehouse_inventory, str):
                warehouse_inventory = json.loads(warehouse_inventory)
            if preferred_warehouse and warehouse_inventory:
                for wh in warehouse_inventory:
                    if wh.get('name') == preferred_warehouse:
                        v['inventory'] = wh.get('quantity', 0)
                        v['warehouse_name'] = wh.get('name', '')
                        break
        
        product['variants'] = variants
        product['media'] = media
        product['preferred_warehouse'] = preferred_warehouse
        
        return product

@api_router.post("/products/{product_id}/select-for-odoo")
async def toggle_selection(product_id: str, data: ProductSelectRequest, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        result = await conn.execute("""
            UPDATE products SET selected_for_odoo = $1, odoo_sync_status = $2, updated_at = $3 WHERE id = $4
        """, data.selected, status, utc_now(), product_id)
        if result == "UPDATE 0":
            raise HTTPException(404, "Product not found")
        return {"status": "updated", "selected_for_odoo": data.selected}

@api_router.post("/products/bulk-select")
async def bulk_select(data: BulkSelectRequest, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        await conn.execute("""
            UPDATE products SET selected_for_odoo = $1, odoo_sync_status = $2, updated_at = $3 WHERE id = ANY($4)
        """, data.selected, status, utc_now(), data.product_ids)
        return {"status": "updated"}

@api_router.post("/products/{product_id}/select-for-lightspeed")
async def toggle_lightspeed_selection(product_id: str, data: ProductSelectRequest, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        result = await conn.execute("""
            UPDATE products SET selected_for_lightspeed = $1, lightspeed_sync_status = $2, updated_at = $3 WHERE id = $4
        """, data.selected, status, utc_now(), product_id)
        if result == "UPDATE 0":
            raise HTTPException(404, "Product not found")
        return {"status": "updated", "selected_for_lightspeed": data.selected}

@api_router.post("/products/bulk-select-lightspeed")
async def bulk_select_lightspeed(data: BulkSelectRequest, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        status = "pending" if data.selected else "not_selected"
        await conn.execute("""
            UPDATE products SET selected_for_lightspeed = $1, lightspeed_sync_status = $2, updated_at = $3 WHERE id = ANY($4)
        """, data.selected, status, utc_now(), data.product_ids)
        return {"status": "updated"}

class BulkDeleteRequest(BaseModel):
    product_ids: list

@api_router.post("/products/bulk-delete")
async def bulk_delete_products(data: BulkDeleteRequest, user: dict = Depends(get_admin_user)):
    """Delete multiple products by ID."""
    async with pool.acquire() as conn:
        # Delete related records first (cascade should handle this but being explicit)
        await conn.execute("DELETE FROM product_variants WHERE product_id = ANY($1)", data.product_ids)
        await conn.execute("DELETE FROM product_media WHERE product_id = ANY($1)", data.product_ids)
        result = await conn.execute("DELETE FROM products WHERE id = ANY($1)", data.product_ids)
        deleted = int(result.split()[-1]) if result else 0
        return {"status": "deleted", "count": deleted}

@api_router.delete("/products/delete-all")
async def delete_all_products(user: dict = Depends(get_admin_user)):
    """Delete all products. Use with caution!"""
    async with pool.acquire() as conn:
        # Get count before deleting
        count = await conn.fetchval("SELECT COUNT(*) FROM products")
        # Delete all (cascade will handle variants and media)
        await conn.execute("DELETE FROM product_variants")
        await conn.execute("DELETE FROM product_media")
        await conn.execute("DELETE FROM products")
        return {"status": "deleted", "count": count}


# ==================== DASHBOARD ====================
@api_router.get("/dashboard/stats")
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        total_products = await conn.fetchval("SELECT COUNT(*) FROM products")
        selected_products = await conn.fetchval("SELECT COUNT(*) FROM products WHERE selected_for_odoo = TRUE")
        selected_lightspeed = await conn.fetchval("SELECT COUNT(*) FROM products WHERE selected_for_lightspeed = TRUE")
        total_suppliers = await conn.fetchval("SELECT COUNT(*) FROM suppliers")
        active_suppliers = await conn.fetchval("SELECT COUNT(*) FROM suppliers WHERE status = 'active'")
        synced_products = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'synced'")
        pending_products = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'pending'")
        total_variants = await conn.fetchval("SELECT COUNT(*) FROM product_variants")
        active_products = await conn.fetchval("SELECT COUNT(*) FROM products WHERE is_active = TRUE")
        
        # Category distribution
        category_rows = await conn.fetch("""
            SELECT COALESCE(category, 'Uncategorized') as category, COUNT(*) as count 
            FROM products 
            GROUP BY category 
            ORDER BY count DESC 
            LIMIT 10
        """)
        category_distribution = [{"category": r['category'][:20], "count": r['count']} for r in category_rows]
        
        # Brand distribution
        brand_rows = await conn.fetch("""
            SELECT COALESCE(brand, 'Unknown') as brand, COUNT(*) as count 
            FROM products 
            GROUP BY brand 
            ORDER BY count DESC 
            LIMIT 10
        """)
        brand_distribution = [{"brand": r['brand'][:15], "count": r['count']} for r in brand_rows]
        
        # Supplier distribution
        supplier_rows = await conn.fetch("""
            SELECT s.supplier_name as supplier, COUNT(p.id) as count 
            FROM suppliers s
            LEFT JOIN products p ON p.supplier_id = s.id
            GROUP BY s.id, s.supplier_name
            ORDER BY count DESC
        """)
        supplier_distribution = [{"supplier": r['supplier'][:15], "count": r['count']} for r in supplier_rows]
        
        return {
            "total_products": total_products,
            "selected_for_odoo": selected_products,
            "selected_for_lightspeed": selected_lightspeed,
            "synced_to_odoo": synced_products,
            "total_suppliers": total_suppliers,
            "active_suppliers": active_suppliers,
            "pending_products": pending_products,
            "total_variants": total_variants,
            "active_products": active_products,
            "category_distribution": category_distribution,
            "brand_distribution": brand_distribution,
            "supplier_distribution": supplier_distribution
        }


# ==================== SYNC LOGS ====================
@api_router.get("/sync/logs")
async def get_sync_logs(
    supplier_id: Optional[str] = None,
    sync_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user)
):
    async with pool.acquire() as conn:
        conditions = []
        values = []
        param_idx = 1
        
        if supplier_id:
            conditions.append(f"supplier_id = ${param_idx}")
            values.append(supplier_id)
            param_idx += 1
        if sync_type:
            conditions.append(f"sync_type = ${param_idx}")
            values.append(sync_type)
            param_idx += 1
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT * FROM sync_logs WHERE {where_clause}
            ORDER BY start_time DESC LIMIT ${param_idx}
        """
        values.append(limit)
        
        rows = await conn.fetch(query, *values)
        return {"logs": [row_to_dict(r) for r in rows]}


# ==================== SETTINGS ====================
@api_router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not row:
            return {
                "id": "system_settings", "odoo_url": "", "odoo_db": "", "odoo_username": "", "odoo_api_key": "",
                "odoo_connected": False, "sync_products_interval_hours": 24, "sync_inventory_interval_minutes": 30,
                "sync_pricing_interval_hours": 12, "auto_sync_enabled": False, "preferred_warehouse": "MISSISSAUGA/ON"
            }
        s = row_to_dict(row)
        if s.get('odoo_api_key'):
            s['odoo_api_key'] = '***'
        if s.get('lightspeed_api_secret'):
            s['lightspeed_api_secret'] = '***'
        return s

@api_router.put("/settings")
async def update_settings(data: SettingsUpdate, user: dict = Depends(get_admin_user)):
    async with pool.acquire() as conn:
        update_fields = []
        values = []
        param_idx = 1
        
        # Regular fields (not secrets)
        for field in ['sync_products_interval_hours', 'sync_inventory_interval_minutes', 'sync_pricing_interval_hours',
                      'auto_sync_enabled', 'odoo_url', 'odoo_db', 'odoo_username', 'preferred_warehouse', 'markup_percentage',
                      'auto_push_to_odoo', 'lightspeed_api_key', 'lightspeed_cluster', 'lightspeed_language']:
            val = getattr(data, field, None)
            if val is not None:
                update_fields.append(f"{field} = ${param_idx}")
                values.append(val)
                param_idx += 1
        
        # Handle secret fields separately (only update if not masked)
        if data.odoo_api_key and data.odoo_api_key != '***':
            update_fields.append(f"odoo_api_key = ${param_idx}")
            values.append(data.odoo_api_key)
            param_idx += 1
        
        if data.lightspeed_api_secret and data.lightspeed_api_secret != '***':
            update_fields.append(f"lightspeed_api_secret = ${param_idx}")
            values.append(data.lightspeed_api_secret)
            param_idx += 1
        
        update_fields.append(f"updated_at = ${param_idx}")
        values.append(utc_now())
        param_idx += 1
        
        if update_fields:
            query = f"UPDATE settings SET {', '.join(update_fields)} WHERE id = 'system_settings'"
            await conn.execute(query, *values)
        
        # Reschedule background jobs if sync-related settings changed
        from scheduler import apply_schedule_from_settings
        await apply_schedule_from_settings()
        
        return {"status": "updated", "success": True}

@api_router.get("/settings/warehouses")
async def get_available_warehouses(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT jsonb_array_elements(warehouse_inventory)->>'name' as name
            FROM product_variants
            WHERE warehouse_inventory != '[]'::jsonb AND warehouse_inventory IS NOT NULL
        """)
        warehouses = sorted(set(r['name'] for r in rows if r['name']))
        return {"warehouses": warehouses}


# ==================== SCHEDULER ROUTES ====================
@api_router.get("/scheduler/status")
async def scheduler_status(user: dict = Depends(get_current_user)):
    from scheduler import get_scheduler_status
    return get_scheduler_status()

@api_router.post("/scheduler/reschedule")
async def reschedule_jobs(user: dict = Depends(get_admin_user)):
    from scheduler import apply_schedule_from_settings
    await apply_schedule_from_settings()
    from scheduler import get_scheduler_status
    return {"status": "rescheduled", **get_scheduler_status()}


# ==================== LIGHTSPEED ROUTES ====================
@api_router.post("/settings/lightspeed/test")
async def test_lightspeed_connection(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lightspeed_api_key, lightspeed_api_secret, lightspeed_cluster, lightspeed_language FROM settings WHERE id = 'system_settings'")
    if not row:
        raise HTTPException(404, "Settings not found")
    from lightspeed_service import LightspeedService
    ls = LightspeedService(row['lightspeed_api_key'], row['lightspeed_api_secret'], row['lightspeed_cluster'], row['lightspeed_language'])
    return ls.test_connection()

@api_router.get("/categories/lightspeed")
async def get_lightspeed_categories(user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lightspeed_api_key, lightspeed_api_secret, lightspeed_cluster, lightspeed_language FROM settings WHERE id = 'system_settings'")
    if not row:
        raise HTTPException(404, "Settings not found")
    from lightspeed_service import LightspeedService
    ls = LightspeedService(row['lightspeed_api_key'], row['lightspeed_api_secret'], row['lightspeed_cluster'], row['lightspeed_language'])
    return ls.get_categories()

@api_router.post("/sync/lightspeed/{supplier_id}")
async def push_to_lightspeed(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Push selected products to Lightspeed eCom."""
    async with pool.acquire() as conn:
        supplier = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not supplier:
            raise HTTPException(404, "Supplier not found")
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM products WHERE selected_for_lightspeed = TRUE AND lightspeed_sync_status = 'pending' AND supplier_id = $1",
            supplier_id
        )
    log_id = await _create_sync_log(supplier_id, supplier['supplier_name'], "lightspeed_push", f"Pushing {count} products to Lightspeed...")
    background_tasks.add_task(lightspeed_push_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "products_to_push": count}

async def lightspeed_push_task(supplier_id: str, log_id: str):
    """Background task to push products to Lightspeed eCom."""
    from lightspeed_service import LightspeedService
    try:
        async with pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
            settings = row_to_dict(settings_row)
            markup = float(settings.get('markup_percentage') or 40)

            ls = LightspeedService(
                settings.get('lightspeed_api_key', ''),
                settings.get('lightspeed_api_secret', ''),
                settings.get('lightspeed_cluster', 'us1'),
                settings.get('lightspeed_language', 'en')
            )

            conn_test = ls.test_connection()
            if not conn_test.get('connected'):
                await _update_sync_log(log_id, 'failed', f"Lightspeed connection failed: {conn_test.get('message')}")
                return

            products = await conn.fetch('''
                SELECT p.*, cm.lightspeed_category_id
                FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                WHERE p.selected_for_lightspeed = TRUE AND p.lightspeed_sync_status = 'pending' AND p.supplier_id = $1
            ''', supplier_id)

        if not products:
            await _update_sync_log(log_id, 'completed', 'No pending products for Lightspeed', progress=100)
            return

        synced = 0
        failed = 0
        total = len(products)

        for i, p in enumerate(products):
            product = row_to_dict(p)
            async with pool.acquire() as conn:
                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])

            cost = float(product.get('base_price') or 0)
            sale_price = calculate_sale_price(cost, markup)

            ls_data = {
                'product_name': product.get('product_name'),
                'supplier_sku': product.get('supplier_sku'),
                'description': product.get('description'),
                'base_price': sale_price,
                'cost_price': cost,
                'category_id': product.get('lightspeed_category_id'),
                'variants': [row_to_dict(v) for v in variants],
                'images': [row_to_dict(img) for img in images],
            }

            result = ls.create_or_update_product(ls_data)
            if result.get('success'):
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE products SET lightspeed_sync_status = 'synced', lightspeed_product_id = $1, updated_at = $2 WHERE id = $3",
                        str(result.get('lightspeed_id', '')), utc_now(), product['id']
                    )
                synced += 1
            else:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE products SET lightspeed_sync_status = 'failed', updated_at = $1 WHERE id = $2",
                        utc_now(), product['id']
                    )
                failed += 1

            if (i + 1) % 5 == 0:
                progress = int(((i + 1) / total) * 100)
                await _update_sync_log(log_id, 'running', f'Pushed {synced}/{total} to Lightspeed ({failed} failed)', progress=progress, total=total, processed=synced)

        msg = f"Lightspeed push complete: {synced} synced, {failed} failed out of {total}"
        await _update_sync_log(log_id, 'completed', msg, progress=100, total=total, processed=synced)
        logger.info(msg)

    except Exception as e:
        logger.error(f"Lightspeed push error: {e}")
        await _update_sync_log(log_id, 'failed', f'Error: {str(e)}')


# ==================== SYNC ROUTES ====================
# Global dict to track running sync tasks
running_syncs = {}

async def _auto_push_to_odoo_if_enabled(supplier_id: str):
    """Check settings and auto-push pending products to Odoo if enabled."""
    try:
        async with pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT auto_push_to_odoo, odoo_url, odoo_db, odoo_username, odoo_api_key, markup_percentage FROM settings WHERE id = 'system_settings'")
            if not settings_row or not settings_row.get('auto_push_to_odoo'):
                return
            if not settings_row.get('odoo_url'):
                logger.info("Auto-push: Odoo not configured, skipping")
                return

            pending_count = await conn.fetchval(
                "SELECT COUNT(*) FROM products WHERE selected_for_odoo = TRUE AND odoo_sync_status = 'pending' AND supplier_id = $1",
                supplier_id
            )
            if pending_count == 0:
                logger.info("Auto-push: No pending products for supplier %s", supplier_id)
                return

        logger.info("Auto-push: %d products pending for Odoo, starting push...", pending_count)
        push_log_id = await _create_sync_log(supplier_id, "Auto", "odoo_push", f"Auto-pushing {pending_count} products to Odoo...")
        await _odoo_push_task(supplier_id, push_log_id)

    except Exception as e:
        logger.error("Auto-push to Odoo error: %s", e)


async def _odoo_push_task(supplier_id: str, log_id: str):
    """Push pending products for a specific supplier to Odoo."""
    from odoo_service import OdooService
    try:
        async with pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
            settings = row_to_dict(settings_row)
            markup = float(settings.get('markup_percentage') or 40)

            products = await conn.fetch('''
                SELECT p.*, cm.odoo_category_id
                FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending' AND p.supplier_id = $1
            ''', supplier_id)

        if not products:
            await _update_sync_log(log_id, 'completed', 'No pending products', progress=100)
            return

        odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
        conn_test = odoo.test_connection()
        if not conn_test.get('connected'):
            await _update_sync_log(log_id, 'failed', f"Odoo connection failed: {conn_test.get('message')}")
            return

        synced = 0
        failed = 0
        for p in products:
            product = row_to_dict(p)
            async with pool.acquire() as conn:
                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])

            cost = float(product.get('base_price') or 0)
            sale_price = calculate_sale_price(cost, markup)

            odoo_data = {
                'product_name': product.get('product_name'),
                'supplier_sku': product.get('supplier_sku'),
                'description': product.get('description'),
                'base_price': sale_price,
                'cost_price': cost,
                'category_id': product.get('odoo_category_id'),
                'default_category': 'SanMar Apparel',
                'variants': [row_to_dict(v) for v in variants],
                'images': [row_to_dict(i) for i in images],
            }

            result = odoo.create_or_update_product(odoo_data)
            if result.get('success'):
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                        str(result.get('odoo_id', '')), utc_now(), product['id']
                    )
                synced += 1
            else:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE products SET odoo_sync_status = 'failed', updated_at = $1 WHERE id = $2",
                        utc_now(), product['id']
                    )
                failed += 1

        msg = f"Auto-push complete: {synced} synced, {failed} failed out of {len(products)}"
        await _update_sync_log(log_id, 'completed', msg, progress=100, total=len(products), processed=synced)
        logger.info("Auto-push: %s", msg)

    except Exception as e:
        logger.error("Odoo push task error: %s", e)
        await _update_sync_log(log_id, 'failed', f'Error: {str(e)}')

async def _create_sync_log(supplier_id, supplier_name, sync_type, message):
    log_id = new_id()
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO sync_logs (id, supplier_id, supplier_name, sync_type, status, message, start_time, created_at)
            VALUES ($1, $2, $3, $4, 'running', $5, $6, $6)
        ''', log_id, supplier_id, supplier_name, sync_type, message, utc_now())
    return log_id

async def _update_sync_log(log_id, status, message, progress=0, total=0, processed=0):
    async with pool.acquire() as conn:
        end_time = utc_now() if status in ['completed', 'failed', 'stopped'] else None
        await conn.execute('''
            UPDATE sync_logs SET status = $1, message = $2, progress = $3, total_items = $4, processed_items = $5, end_time = $6
            WHERE id = $7
        ''', status, message, progress, total, processed, end_time, log_id)


# Import PromoStandards connector
from promostandards import PromoStandardsConnector


async def sync_products_task(supplier_id: str, log_id: str):
    """Background task to sync products from a supplier."""
    task_id = f"products_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not row:
                await _update_sync_log(log_id, "failed", "Supplier not found")
                return
            supplier = row_to_dict(row)
        
        connector = PromoStandardsConnector(supplier)
        
        # Get sellable products
        await _update_sync_log(log_id, "running", "Fetching product list...", 0)
        result = connector.get_sellable_products()
        
        if not result.get('success'):
            await _update_sync_log(log_id, "failed", f"Failed to get products: {result.get('error')}")
            return
        
        products = result.get('products', [])
        unique_skus = list(set(p['product_id'] for p in products))
        total = len(unique_skus)
        
        await _update_sync_log(log_id, "running", f"Found {total} unique products", 0, total, 0)
        
        processed = 0
        for sku in unique_skus:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await _update_sync_log(log_id, "stopped", f"Stopped by user. Processed {processed}/{total}", int(processed/total*100), total, processed)
                return
            
            try:
                product_data = connector.get_product(sku)
                if product_data.get('success') and product_data.get('product'):
                    p = product_data['product']
                    product_id = new_id()
                    
                    async with pool.acquire() as conn:
                        # Upsert product
                        existing = await conn.fetchrow("SELECT id FROM products WHERE supplier_id = $1 AND supplier_sku = $2", supplier_id, sku)
                        
                        if existing:
                            product_id = existing['id']
                            await conn.execute('''
                                UPDATE products SET product_name = $1, description = $2, brand = $3, category = $4,
                                    base_price = $5, last_synced = $6, updated_at = $6 WHERE id = $7
                            ''', p.get('product_name', ''), p.get('description', ''), p.get('brand', ''),
                                p.get('category', ''), float(p.get('price', 0) or 0), utc_now(), product_id)
                        else:
                            await conn.execute('''
                                INSERT INTO products (id, supplier_id, supplier_sku, product_name, description, brand, category, base_price, last_synced, created_at, updated_at)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9, $9)
                            ''', product_id, supplier_id, sku, p.get('product_name', ''), p.get('description', ''),
                                p.get('brand', ''), p.get('category', ''), float(p.get('price', 0) or 0), utc_now())
                        
                        # Handle variants
                        for v in p.get('variants', []):
                            variant_id = new_id()
                            existing_var = await conn.fetchrow("SELECT id FROM product_variants WHERE product_id = $1 AND variant_sku = $2", product_id, v.get('variant_sku', ''))
                            
                            if existing_var:
                                await conn.execute('''
                                    UPDATE product_variants SET color = $1, size = $2, price = $3, updated_at = $4 WHERE id = $5
                                ''', v.get('color', ''), v.get('size', ''), float(v.get('price', 0) or 0), utc_now(), existing_var['id'])
                            else:
                                await conn.execute('''
                                    INSERT INTO product_variants (id, product_id, variant_sku, color, size, price, created_at, updated_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                                ''', variant_id, product_id, v.get('variant_sku', ''), v.get('color', ''), v.get('size', ''),
                                    float(v.get('price', 0) or 0), utc_now())
                
            except Exception as e:
                logger.error(f"Error syncing product {sku}: {e}")
            
            processed += 1
            if processed % 10 == 0:
                progress = int(processed / total * 100)
                await _update_sync_log(log_id, "running", f"Processing... {processed}/{total}", progress, total, processed)
        
        # Update supplier last_sync
        async with pool.acquire() as conn:
            await conn.execute("UPDATE suppliers SET last_sync = $1 WHERE id = $2", utc_now(), supplier_id)
        
        await _update_sync_log(log_id, "completed", f"Synced {processed} products", 100, total, processed)
        
    except Exception as e:
        logger.error(f"Sync error: {e}")
        await _update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_inventory_task(supplier_id: str, log_id: str):
    """Background task to sync inventory for all products of a supplier."""
    task_id = f"inventory_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    
    try:
        async with pool.acquire() as conn:
            supplier_row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier_row:
                await _update_sync_log(log_id, "failed", "Supplier not found")
                return
            supplier = row_to_dict(supplier_row)
            
            # Get all products for this supplier
            product_rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
            products = [row_to_dict(p) for p in product_rows]
        
        connector = PromoStandardsConnector(supplier)
        total = len(products)
        processed = 0
        updated_count = 0
        
        await _update_sync_log(log_id, "running", f"Syncing inventory for {total} products", 0, total, 0)
        
        for product in products:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await _update_sync_log(log_id, "stopped", f"Stopped. Updated {updated_count} variants", int(processed/total*100), total, processed)
                return
            
            try:
                result = connector.get_inventory(product['supplier_sku'])
                if result.get('success') and result.get('inventory'):
                    async with pool.acquire() as conn:
                        for inv in result['inventory']:
                            part_id = inv.get('part_id', '')
                            qty = inv.get('quantity_available', 0)
                            warehouses = inv.get('warehouses', [])
                            
                            r = await conn.execute('''
                                UPDATE product_variants SET inventory = $1, warehouse_inventory = $2, updated_at = $3
                                WHERE product_id = $4 AND variant_sku = $5
                            ''', qty, json.dumps(warehouses), utc_now(), product['id'], part_id)
                            
                            if r != "UPDATE 0":
                                updated_count += 1
            except Exception as e:
                logger.error(f"Inventory sync error for {product['supplier_sku']}: {e}")
            
            processed += 1
            if processed % 20 == 0:
                progress = int(processed / total * 100)
                await _update_sync_log(log_id, "running", f"Processing... {processed}/{total}", progress, total, processed)
        
        await _update_sync_log(log_id, "completed", f"Updated {updated_count} variants", 100, total, processed)
        
    except Exception as e:
        logger.error(f"Inventory sync error: {e}")
        await _update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_pricing_task(supplier_id: str, log_id: str):
    """Background task to sync pricing for all products of a supplier."""
    task_id = f"pricing_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    
    try:
        async with pool.acquire() as conn:
            supplier_row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier_row:
                await _update_sync_log(log_id, "failed", "Supplier not found")
                return
            supplier = row_to_dict(supplier_row)
            
            product_rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
            products = [row_to_dict(p) for p in product_rows]
        
        connector = PromoStandardsConnector(supplier)
        total = len(products)
        processed = 0
        updated_count = 0
        
        await _update_sync_log(log_id, "running", f"Syncing pricing for {total} products", 0, total, 0)
        
        for product in products:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await _update_sync_log(log_id, "stopped", f"Stopped. Updated {updated_count} variants", int(processed/total*100), total, processed)
                return
            
            try:
                result = connector.get_pricing(product['supplier_sku'])
                if result.get('success') and result.get('pricing'):
                    all_prices = []  # Track all prices to calculate base_price
                    async with pool.acquire() as conn:
                        for price_item in result['pricing']:
                            part_id = price_item.get('part_id', '')
                            # Extract the first/lowest quantity price from the prices array
                            prices = price_item.get('prices', [])
                            price = 0.0
                            if prices:
                                # Sort by min_quantity and get the first (lowest tier) price
                                sorted_prices = sorted(prices, key=lambda x: x.get('min_quantity', 0))
                                price = float(sorted_prices[0].get('price', 0) or 0)
                                if price > 0:
                                    all_prices.append(price)
                            
                            r = await conn.execute('''
                                UPDATE product_variants SET price = $1, updated_at = $2
                                WHERE product_id = $3 AND variant_sku = $4
                            ''', price, utc_now(), product['id'], part_id)
                            
                            if r != "UPDATE 0":
                                updated_count += 1
                        
                        # Update product base_price with the minimum variant price
                        if all_prices:
                            base_price = min(all_prices)
                            await conn.execute('''
                                UPDATE products SET base_price = $1, updated_at = $2
                                WHERE id = $3
                            ''', base_price, utc_now(), product['id'])
            except Exception as e:
                logger.error(f"Pricing sync error for {product['supplier_sku']}: {e}")
            
            processed += 1
            if processed % 20 == 0:
                progress = int(processed / total * 100)
                await _update_sync_log(log_id, "running", f"Processing... {processed}/{total}", progress, total, processed)
        
        await _update_sync_log(log_id, "completed", f"Updated {updated_count} variants", 100, total, processed)
        
    except Exception as e:
        logger.error(f"Pricing sync error: {e}")
        await _update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_media_task(supplier_id: str, log_id: str):
    """Background task to sync media for all products of a supplier."""
    task_id = f"media_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    
    try:
        async with pool.acquire() as conn:
            supplier_row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier_row:
                await _update_sync_log(log_id, "failed", "Supplier not found")
                return
            supplier = row_to_dict(supplier_row)
            
            product_rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
            products = [row_to_dict(p) for p in product_rows]
        
        connector = PromoStandardsConnector(supplier)
        total = len(products)
        processed = 0
        added_count = 0
        
        await _update_sync_log(log_id, "running", f"Syncing media for {total} products", 0, total, 0)
        
        for product in products:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await _update_sync_log(log_id, "stopped", f"Stopped. Added {added_count} media items", int(processed/total*100), total, processed)
                return
            
            try:
                result = connector.get_media(product['supplier_sku'])
                if result.get('success') and result.get('media'):
                    async with pool.acquire() as conn:
                        for media_item in result['media']:
                            media_id = new_id()
                            url = media_item.get('url', '')
                            
                            # Check if URL already exists
                            existing = await conn.fetchrow("SELECT id FROM product_media WHERE product_id = $1 AND url = $2", product['id'], url)
                            if not existing and url:
                                await conn.execute('''
                                    INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                                ''', media_id, product['id'], media_item.get('type', 'image'), url,
                                    media_item.get('description', ''), media_item.get('is_primary', False), utc_now())
                                added_count += 1
            except Exception as e:
                logger.error(f"Media sync error for {product['supplier_sku']}: {e}")
            
            processed += 1
            if processed % 20 == 0:
                progress = int(processed / total * 100)
                await _update_sync_log(log_id, "running", f"Processing... {processed}/{total}", progress, total, processed)
        
        await _update_sync_log(log_id, "completed", f"Added {added_count} media items", 100, total, processed)
        
    except Exception as e:
        logger.error(f"Media sync error: {e}")
        await _update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


# Sync endpoints
@api_router.post("/sync/products/bulk")
async def sync_products_bulk(
    product_ids: List[str],
    sync_type: str = Query(..., regex="^(pricing|inventory|media)$"),
    background_tasks: BackgroundTasks = None,
    user: dict = Depends(get_current_user)
):
    """Bulk sync pricing/inventory/media for multiple products."""
    results = {"success": 0, "failed": 0, "errors": []}
    
    async with pool.acquire() as conn:
        for product_id in product_ids:
            try:
                row = await conn.fetchrow("""
                    SELECT p.id, p.supplier_sku, s.*
                    FROM products p
                    JOIN suppliers s ON p.supplier_id = s.id
                    WHERE p.id = $1
                """, product_id)
                
                if not row:
                    results["failed"] += 1
                    results["errors"].append(f"Product {product_id} not found")
                    continue
                
                product_sku = row['supplier_sku']
                supplier = row_to_dict(row)
                connector = PromoStandardsConnector(supplier)
                
                if sync_type == "inventory":
                    result = connector.get_inventory(product_sku)
                    if result.get('success') and result.get('inventory'):
                        for inv in result['inventory']:
                            part_id = inv.get('part_id', '')
                            qty = inv.get('quantity_available', 0)
                            warehouses = inv.get('warehouses', [])
                            await conn.execute('''
                                UPDATE product_variants SET inventory = $1, warehouse_inventory = $2, updated_at = $3
                                WHERE product_id = $4 AND variant_sku = $5
                            ''', qty, json.dumps(warehouses), utc_now(), product_id, part_id)
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                        
                elif sync_type == "pricing":
                    result = connector.get_pricing(product_sku)
                    if result.get('success') and result.get('pricing'):
                        all_prices = []
                        for price_item in result['pricing']:
                            part_id = price_item.get('part_id', '')
                            # Extract the first/lowest quantity price from the prices array
                            prices = price_item.get('prices', [])
                            price = 0.0
                            if prices:
                                # Sort by min_quantity and get the first (lowest tier) price
                                sorted_prices = sorted(prices, key=lambda x: x.get('min_quantity', 0))
                                price = float(sorted_prices[0].get('price', 0) or 0)
                                if price > 0:
                                    all_prices.append(price)
                            await conn.execute('''
                                UPDATE product_variants SET price = $1, updated_at = $2
                                WHERE product_id = $3 AND variant_sku = $4
                            ''', price, utc_now(), product_id, part_id)
                        # Update product base_price
                        if all_prices:
                            await conn.execute('''
                                UPDATE products SET base_price = $1, updated_at = $2
                                WHERE id = $3
                            ''', min(all_prices), utc_now(), product_id)
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                        
                elif sync_type == "media":
                    result = connector.get_media(product_sku)
                    if result.get('success') and result.get('media'):
                        for media_item in result['media']:
                            url = media_item.get('url', '')
                            existing = await conn.fetchrow("SELECT id FROM product_media WHERE product_id = $1 AND url = $2", product_id, url)
                            if not existing and url:
                                await conn.execute('''
                                    INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                                ''', new_id(), product_id, media_item.get('type', 'image'), url,
                                    media_item.get('description', ''), media_item.get('is_primary', False), utc_now())
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                        
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"Error for {product_id}: {str(e)}")
    
    return results


@api_router.post("/sync/products/{supplier_id}")
async def sync_products(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']
    
    log_id = await _create_sync_log(supplier_id, supplier_name, "products", "Starting product sync...")
    background_tasks.add_task(sync_products_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"products_{supplier_id}"}


@api_router.post("/sync/inventory/{supplier_id}")
async def sync_inventory(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']
    
    log_id = await _create_sync_log(supplier_id, supplier_name, "inventory", "Starting inventory sync...")
    background_tasks.add_task(sync_inventory_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"inventory_{supplier_id}"}


@api_router.post("/sync/pricing/{supplier_id}")
async def sync_pricing(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']
    
    log_id = await _create_sync_log(supplier_id, supplier_name, "pricing", "Starting pricing sync...")
    background_tasks.add_task(sync_pricing_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"pricing_{supplier_id}"}


@api_router.post("/sync/media/{supplier_id}")
async def sync_media(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']
    
    log_id = await _create_sync_log(supplier_id, supplier_name, "media", "Starting media sync...")
    background_tasks.add_task(sync_media_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"media_{supplier_id}"}


@api_router.post("/sync/full/{supplier_id}")
async def sync_full(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """Start a full sync (products, then inventory, pricing, media)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']
    
    log_id = await _create_sync_log(supplier_id, supplier_name, "full", "Starting full sync...")
    background_tasks.add_task(sync_products_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"products_{supplier_id}"}


@api_router.post("/sync/bulk-data/{supplier_id}")
async def sync_bulk_data(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """
    Sync products using BulkData Service 1.0.
    This downloads all product data including images in a single API call.
    Images from BulkData CAN be downloaded (unlike MediaContent URLs).
    Limited to once per day per account.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']
    
    log_id = await _create_sync_log(supplier_id, supplier_name, "bulk_data", "Starting BulkData sync (products + images)...")
    background_tasks.add_task(sync_bulk_data_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"bulkdata_{supplier_id}", "message": "BulkData sync started - this will download products with images"}


async def sync_bulk_data_task(supplier_id: str, log_id: str):
    """Background task to sync products and images using BulkData Service."""
    import os
    import base64
    
    task_id = f"bulkdata_{supplier_id}"
    running_syncs[task_id] = {"should_stop": False}
    
    try:
        async with pool.acquire() as conn:
            # Get supplier config
            supplier = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier:
                await _update_sync_log(log_id, 'failed', 'Supplier not found')
                return
            
            supplier = row_to_dict(supplier)
            
            await _update_sync_log(log_id, 'running', 'Connecting to BulkData API...', progress=5)
            
            # Initialize connector
            connector = PromoStandardsConnector(supplier)
            
            # Inject bulk_data_url from supplier if services doesn't have it
            if 'bulk_data' not in connector.services and supplier.get('bulk_data_url'):
                connector.services['bulk_data'] = supplier['bulk_data_url']
            
            # Call BulkData API
            await _update_sync_log(log_id, 'running', 'Calling BulkData API (this may take a while)...', progress=10)
            result = connector.get_bulk_data()
            
            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                if result.get('rate_limited'):
                    await _update_sync_log(log_id, 'failed', f"BulkData rate limited: {error_msg}. This API can only be called once per day. Try again tomorrow.")
                else:
                    await _update_sync_log(log_id, 'failed', f"BulkData API error: {error_msg}")
                return
            
            products_data = result.get('products', [])
            total_products = len(products_data)
            
            if total_products == 0:
                await _update_sync_log(log_id, 'completed', 'No products returned from BulkData API', total=0, processed=0)
                return
            
            await _update_sync_log(log_id, 'running', f'Processing {total_products} products from BulkData...', progress=15, total=total_products)
            
            # Group by style to create product records (BulkData returns one row per size/color)
            products_by_style = {}
            for p in products_data:
                style = p.get('style', '')
                if not style:
                    continue
                if style not in products_by_style:
                    products_by_style[style] = {
                        'product_name': p.get('product_name', ''),
                        'description': p.get('description', ''),
                        'brand': p.get('brand', ''),
                        'image_url': p.get('image_url', ''),
                        'variants': []
                    }
                # If this row has a better image URL (some rows may be empty), use it
                if p.get('image_url') and not products_by_style[style]['image_url']:
                    products_by_style[style]['image_url'] = p.get('image_url')
                    
                products_by_style[style]['variants'].append({
                    'variant_sku': p.get('product_id', ''),
                    'color': p.get('color', ''),
                    'size': p.get('size', ''),
                    'price': p.get('price', 0),
                    'inventory': p.get('quantity', 0),
                })
            
            logger.info(f"BulkData: {len(products_by_style)} unique products from {total_products} rows")
            
            processed = 0
            images_downloaded = 0
            images_failed = 0
            
            for style, product_data in products_by_style.items():
                if running_syncs.get(task_id, {}).get("should_stop"):
                    await _update_sync_log(log_id, 'stopped', f'Sync stopped by user. Processed {processed} products.')
                    break
                
                try:
                    product_id = new_id()
                    product_name = product_data['product_name'] or f"Style {style}"
                    
                    # Check if product exists
                    existing = await conn.fetchrow(
                        "SELECT id FROM products WHERE supplier_id = $1 AND supplier_sku = $2",
                        supplier_id, style
                    )
                    
                    if existing:
                        product_id = existing['id']
                        # Update existing product
                        await conn.execute('''
                            UPDATE products SET 
                                product_name = $1, description = $2, brand = $3, 
                                base_price = $4, updated_at = NOW()
                            WHERE id = $5
                        ''', product_name, product_data['description'], product_data['brand'],
                            min([v['price'] for v in product_data['variants']] or [0]), product_id)
                    else:
                        # Create new product
                        await conn.execute('''
                            INSERT INTO products (id, supplier_id, supplier_sku, product_name, description, brand, base_price, created_at, updated_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                        ''', product_id, supplier_id, style, product_name, product_data['description'], 
                            product_data['brand'], min([v['price'] for v in product_data['variants']] or [0]))
                    
                    # Upsert variants
                    for v in product_data['variants']:
                        variant_sku = v['variant_sku']
                        existing_var = await conn.fetchrow(
                            "SELECT id FROM product_variants WHERE product_id = $1 AND variant_sku = $2",
                            product_id, variant_sku
                        )
                        if existing_var:
                            await conn.execute('''
                                UPDATE product_variants SET color = $1, size = $2, price = $3, inventory = $4, updated_at = NOW()
                                WHERE id = $5
                            ''', v['color'], v['size'], v['price'], v['inventory'], existing_var['id'])
                        else:
                            await conn.execute('''
                                INSERT INTO product_variants (id, product_id, variant_sku, color, size, price, inventory, created_at, updated_at)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                            ''', new_id(), product_id, variant_sku, v['color'], v['size'], v['price'], v['inventory'])
                    
                    # Download and save image if available
                    image_url = product_data.get('image_url', '')
                    if image_url:
                        # Check if we already have this image
                        existing_media = await conn.fetchval(
                            "SELECT COUNT(*) FROM product_media WHERE product_id = $1", product_id
                        )
                        
                        if existing_media == 0:
                            # Try to download the image
                            img_result = connector.download_image(image_url)
                            if img_result.get('success'):
                                # Store in database with base64 data
                                await conn.execute('''
                                    INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, image_base64, created_at)
                                    VALUES ($1, $2, 'image', $3, $4, TRUE, $5, NOW())
                                    ON CONFLICT DO NOTHING
                                ''', new_id(), product_id, image_url, f"BulkData image for {style}", img_result.get('image_data', ''))
                                images_downloaded += 1
                            else:
                                # Still store the URL so we have a reference (can retry later)
                                await conn.execute('''
                                    INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at)
                                    VALUES ($1, $2, 'image', $3, $4, TRUE, NOW())
                                    ON CONFLICT DO NOTHING
                                ''', new_id(), product_id, image_url, f"BulkData image for {style} (download failed)")
                                images_failed += 1
                                logger.warning(f"Failed to download image for {style}: {img_result.get('error')}")
                    
                    processed += 1
                    
                    # Update progress every 10 products
                    if processed % 10 == 0:
                        progress = 15 + int((processed / len(products_by_style)) * 80)
                        await _update_sync_log(
                            log_id, 'running', 
                            f'Processed {processed}/{len(products_by_style)} products, {images_downloaded} images downloaded',
                            progress=progress, total=len(products_by_style), processed=processed
                        )
                        
                except Exception as e:
                    logger.error(f"Error processing product {style}: {e}")
            
            # Update supplier last_sync
            await conn.execute("UPDATE suppliers SET last_sync = $1 WHERE id = $2", utc_now(), supplier_id)
            
            message = f"BulkData sync complete: {processed} products, {images_downloaded} images downloaded"
            if images_failed > 0:
                message += f", {images_failed} image downloads failed"
            
            await _update_sync_log(log_id, 'running', message + ". Enriching categories from Product Data API...", progress=96, total=len(products_by_style), processed=processed)
            
            # Enrich categories: BulkData doesn't include category info,
            # so fetch from Product Data API for products missing categories
            categories_updated = 0
            categories_failed = 0
            styles_needing_category = []
            
            rows = await conn.fetch(
                "SELECT id, supplier_sku FROM products WHERE supplier_id = $1 AND (category IS NULL OR category = '')",
                supplier_id
            )
            styles_needing_category = [(r['id'], r['supplier_sku']) for r in rows]
            
            if styles_needing_category:
                logger.info(f"BulkData: Enriching categories for {len(styles_needing_category)} products")
                for prod_id, sku in styles_needing_category:
                    if running_syncs.get(task_id, {}).get("should_stop"):
                        break
                    try:
                        prod_detail = connector.get_product(sku)
                        if prod_detail.get('success') is not False:
                            cat = prod_detail.get('category', '')
                            if cat:
                                await conn.execute(
                                    "UPDATE products SET category = $1, updated_at = NOW() WHERE id = $2",
                                    cat, prod_id
                                )
                                categories_updated += 1
                    except Exception as e:
                        categories_failed += 1
                        logger.warning(f"Failed to get category for {sku}: {e}")
                
                message += f", {categories_updated} categories enriched"
                if categories_failed > 0:
                    message += f" ({categories_failed} category lookups failed)"
            
            await _update_sync_log(log_id, 'completed', message, progress=100, total=len(products_by_style), processed=processed)
            
            # Auto-push to Odoo if enabled
            await _auto_push_to_odoo_if_enabled(supplier_id)
            
    except Exception as e:
        logger.error(f"BulkData sync task error: {e}")
        await _update_sync_log(log_id, 'failed', f'Error: {str(e)}')
    finally:
        running_syncs.pop(task_id, None)


@api_router.post("/sync/enrich-categories/{supplier_id}")
async def enrich_categories(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    """
    Enrich categories for products that have empty categories.
    Fetches category data from the Product Data API for each product.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row:
            raise HTTPException(404, "Supplier not found")
        supplier_name = row['supplier_name']

        count = await conn.fetchval(
            "SELECT COUNT(*) FROM products WHERE supplier_id = $1 AND (category IS NULL OR category = '')",
            supplier_id
        )

    if count == 0:
        return {"status": "no_action", "message": "All products already have categories"}

    log_id = await _create_sync_log(supplier_id, supplier_name, "enrich_categories", f"Enriching categories for {count} products...")
    background_tasks.add_task(enrich_categories_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"enrich_{supplier_id}", "products_to_enrich": count}


async def enrich_categories_task(supplier_id: str, log_id: str):
    """Background task to enrich product categories from Product Data API."""
    task_id = f"enrich_{supplier_id}"
    running_syncs[task_id] = {"should_stop": False}

    try:
        async with pool.acquire() as conn:
            supplier = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier:
                await _update_sync_log(log_id, 'failed', 'Supplier not found')
                return

            supplier = row_to_dict(supplier)
            from promostandards import PromoStandardsConnector
            connector = PromoStandardsConnector(supplier)

            rows = await conn.fetch(
                "SELECT id, supplier_sku FROM products WHERE supplier_id = $1 AND (category IS NULL OR category = '')",
                supplier_id
            )

            if not rows:
                await _update_sync_log(log_id, 'completed', 'No products need category enrichment', progress=100)
                return

            total = len(rows)
            updated = 0
            failed = 0

            for i, r in enumerate(rows):
                if running_syncs.get(task_id, {}).get("should_stop"):
                    await _update_sync_log(log_id, 'stopped', f'Stopped. Enriched {updated}/{total} categories.')
                    break

                try:
                    prod_detail = connector.get_product(r['supplier_sku'])
                    cat = prod_detail.get('category', '')
                    if cat:
                        await conn.execute(
                            "UPDATE products SET category = $1, updated_at = NOW() WHERE id = $2",
                            cat, r['id']
                        )
                        updated += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    logger.warning(f"Category enrichment failed for {r['supplier_sku']}: {e}")

                if (i + 1) % 10 == 0:
                    progress = int(((i + 1) / total) * 100)
                    await _update_sync_log(
                        log_id, 'running',
                        f'Enriched {updated}/{total} categories ({failed} failed)',
                        progress=progress, total=total, processed=updated
                    )

            msg = f"Category enrichment complete: {updated} updated, {failed} failed out of {total}"
            await _update_sync_log(log_id, 'completed', msg, progress=100, total=total, processed=updated)
            logger.info(msg)

    except Exception as e:
        logger.error(f"Category enrichment error: {e}")
        await _update_sync_log(log_id, 'failed', f'Error: {str(e)}')
    finally:
        running_syncs.pop(task_id, None)




@api_router.post("/sync/stop/{task_id}")
async def stop_sync(task_id: str, user: dict = Depends(get_current_user)):
    if task_id in running_syncs:
        running_syncs[task_id]["should_stop"] = True
        return {"status": "stopping", "task_id": task_id}
    return {"status": "not_found", "task_id": task_id}


@api_router.get("/sync/status/{task_id}")
async def get_sync_status(task_id: str, user: dict = Depends(get_current_user)):
    if task_id in running_syncs:
        return {"status": "running", "task_id": task_id}
    return {"status": "not_running", "task_id": task_id}


# Individual product sync endpoints
async def _sync_product_inventory_internal(product_id: str) -> dict:
    """Internal function to sync inventory for a single product."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.id, p.supplier_sku, s.*
            FROM products p
            JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = $1
        """, product_id)
        
        if not row:
            return {"success": False, "message": "Product not found"}
        
        product_sku = row['supplier_sku']
        supplier = row_to_dict(row)
        
        connector = PromoStandardsConnector(supplier)
        result = connector.get_inventory(product_sku)
        
        if not result.get('success'):
            return {"success": False, "message": result.get('error', 'Failed to fetch inventory')}
        
        inventory_items = result.get('inventory', [])
        updated_count = 0
        
        for inv in inventory_items:
            part_id = inv.get('part_id', '')
            qty = inv.get('quantity_available', 0)
            warehouses = inv.get('warehouses', [])
            
            r = await conn.execute('''
                UPDATE product_variants SET inventory = $1, warehouse_inventory = $2, updated_at = $3
                WHERE product_id = $4 AND variant_sku = $5
            ''', qty, json.dumps(warehouses), utc_now(), product_id, part_id)
            
            if r != "UPDATE 0":
                updated_count += 1
        
        return {"success": True, "message": f"Updated inventory for {updated_count} variants", "variants_updated": updated_count}


async def _sync_product_pricing_internal(product_id: str) -> dict:
    """Internal function to sync pricing for a single product."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.id, p.supplier_sku, s.*
            FROM products p
            JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = $1
        """, product_id)
        
        if not row:
            return {"success": False, "message": "Product not found"}
        
        product_sku = row['supplier_sku']
        supplier = row_to_dict(row)
        
        connector = PromoStandardsConnector(supplier)
        result = connector.get_pricing(product_sku)
        
        if not result.get('success'):
            return {"success": False, "message": result.get('error', 'Failed to fetch pricing')}
        
        pricing_items = result.get('pricing', [])
        updated_count = 0
        all_prices = []  # Track all prices to calculate base_price
        
        for price_item in pricing_items:
            part_id = price_item.get('part_id', '')
            # Extract the first/lowest quantity price from the prices array
            prices = price_item.get('prices', [])
            price = 0.0
            if prices:
                # Sort by min_quantity and get the first (lowest tier) price
                sorted_prices = sorted(prices, key=lambda x: x.get('min_quantity', 0))
                price = float(sorted_prices[0].get('price', 0) or 0)
                if price > 0:
                    all_prices.append(price)
            
            r = await conn.execute('''
                UPDATE product_variants SET price = $1, updated_at = $2
                WHERE product_id = $3 AND variant_sku = $4
            ''', price, utc_now(), product_id, part_id)
            
            if r != "UPDATE 0":
                updated_count += 1
        
        # Update product base_price with the minimum variant price
        if all_prices:
            base_price = min(all_prices)
            await conn.execute('''
                UPDATE products SET base_price = $1, updated_at = $2
                WHERE id = $3
            ''', base_price, utc_now(), product_id)
        
        return {"success": True, "message": f"Updated pricing for {updated_count} variants", "variants_updated": updated_count}


async def _sync_product_media_internal(product_id: str) -> dict:
    """Internal function to sync media for a single product."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.id, p.supplier_sku, s.*
            FROM products p
            JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.id = $1
        """, product_id)
        
        if not row:
            return {"success": False, "message": "Product not found"}
        
        product_sku = row['supplier_sku']
        supplier = row_to_dict(row)
        
        connector = PromoStandardsConnector(supplier)
        result = connector.get_media(product_sku)
        
        if not result.get('success'):
            return {"success": False, "message": result.get('error', 'Failed to fetch media')}
        
        media_items = result.get('media', [])
        added_count = 0
        
        for media_item in media_items:
            url = media_item.get('url', '')
            if not url:
                continue
            
            existing = await conn.fetchrow("SELECT id FROM product_media WHERE product_id = $1 AND url = $2", product_id, url)
            if not existing:
                await conn.execute('''
                    INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                ''', new_id(), product_id, media_item.get('type', 'image'), url,
                    media_item.get('description', ''), media_item.get('is_primary', False), utc_now())
                added_count += 1
        
        return {"success": True, "message": f"Added {added_count} media items", "media_added": added_count}


@api_router.post("/sync/product/{product_id}/inventory")
async def sync_product_inventory(product_id: str, user: dict = Depends(get_current_user)):
    return await _sync_product_inventory_internal(product_id)

@api_router.post("/sync/product/{product_id}/pricing")
async def sync_product_pricing(product_id: str, user: dict = Depends(get_current_user)):
    return await _sync_product_pricing_internal(product_id)

@api_router.post("/sync/product/{product_id}/media")
async def sync_product_media(product_id: str, user: dict = Depends(get_current_user)):
    return await _sync_product_media_internal(product_id)


# ==================== ODOO ROUTES ====================
@api_router.post("/odoo/test-connection")
async def test_odoo_connection(user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not row:
            return {"success": False, "message": "Settings not configured"}
        settings = row_to_dict(row)
    
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    result = odoo.test_connection()
    
    async with pool.acquire() as conn:
        await conn.execute("UPDATE settings SET odoo_connected = $1 WHERE id = 'system_settings'", result.get('success', False))
    
    return result


@api_router.post("/odoo/push-products")
async def push_to_odoo(user: dict = Depends(get_current_user)):
    """Push selected products to Odoo ERP."""
    from odoo_service import OdooService
    async with pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)
        
        # Check pending products count first
        pending_count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE selected_for_odoo = TRUE AND odoo_sync_status = 'pending'")
        
        if pending_count == 0:
            return {"status": "no_products", "message": "No products pending sync to Odoo"}
        
        products = await conn.fetch('''
            SELECT p.*, cm.odoo_category_id
            FROM products p
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending'
        ''')
    
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    
    # Test connection first
    conn_test = odoo.test_connection()
    if not conn_test.get('connected'):
        raise HTTPException(400, f"Odoo connection failed: {conn_test.get('message')}")
    
    synced = 0
    failed = 0
    for p in products:
        product = row_to_dict(p)
        
        # Get variants and images
        async with pool.acquire() as conn:
            variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
            images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
        
        # Calculate sale price
        cost = float(product.get('base_price') or 0)
        sale_price = calculate_sale_price(cost, markup)
        
        # Prepare full product data
        odoo_data = {
            'product_name': product.get('product_name'),
            'supplier_sku': product.get('supplier_sku'),
            'description': product.get('description'),
            'base_price': sale_price,
            'cost_price': cost,
            'category_id': product.get('odoo_category_id'),
            'default_category': 'SanMar Apparel',
            'variants': [row_to_dict(v) for v in variants],
            'images': [row_to_dict(i) for i in images],
        }
        
        result = odoo.create_or_update_product(odoo_data)
        if result.get('success'):
            async with pool.acquire() as conn:
                await conn.execute("UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                    str(result.get('odoo_id', '')), utc_now(), product['id'])
            synced += 1
        else:
            failed += 1
            logger.error(f"Failed to push {product.get('supplier_sku')}: {result.get('error')}")
    
    return {"status": "completed", "products_to_push": len(products), "synced": synced, "failed": failed}


@api_router.post("/odoo/sync-products")
async def sync_to_odoo(background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    async with pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)
        
        if not settings.get('odoo_connected'):
            raise HTTPException(400, "Odoo not connected")
        
        products = await conn.fetch('''
            SELECT p.*, cm.odoo_category_id
            FROM products p
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending'
        ''')
    
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    
    synced = 0
    for p in products:
        product = row_to_dict(p)
        
        # Get variants and images
        async with pool.acquire() as conn:
            variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
            images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
        
        # Calculate sale price
        cost = float(product.get('base_price') or 0)
        sale_price = calculate_sale_price(cost, markup)
        
        # Prepare full product data
        odoo_data = {
            'product_name': product.get('product_name'),
            'supplier_sku': product.get('supplier_sku'),
            'description': product.get('description'),
            'base_price': sale_price,
            'cost_price': cost,
            'category_id': product.get('odoo_category_id'),
            'default_category': 'SanMar Apparel',
            'variants': [row_to_dict(v) for v in variants],
            'images': [row_to_dict(i) for i in images],
        }
        
        result = odoo.create_or_update_product(odoo_data)
        if result.get('success'):
            async with pool.acquire() as conn:
                await conn.execute("UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                    str(result.get('odoo_id', '')), utc_now(), product['id'])
            synced += 1
    
    return {"synced": synced, "total": len(products)}


# ==================== ODOO CATEGORY SYNC & MAPPING ====================

@api_router.post("/odoo/sync-categories")
async def sync_odoo_categories(user: dict = Depends(get_current_user)):
    """Fetch and sync e-commerce categories from Odoo."""
    from odoo_service import OdooService
    async with pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
    
    odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
    
    result = odoo.get_ecommerce_categories()
    if not result.get('success'):
        raise HTTPException(400, result.get('error', 'Failed to fetch categories'))
    
    categories = result.get('categories', [])
    
    # Store categories in database
    async with pool.acquire() as conn:
        synced = 0
        for cat in categories:
            await conn.execute('''
                INSERT INTO odoo_categories (id, odoo_category_id, category_name, parent_category, parent_id, last_synced, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
                ON CONFLICT (odoo_category_id) DO UPDATE SET
                    category_name = EXCLUDED.category_name,
                    parent_category = EXCLUDED.parent_category,
                    parent_id = EXCLUDED.parent_id,
                    last_synced = NOW(),
                    updated_at = NOW()
            ''', new_id(), cat['odoo_category_id'], cat['category_name'], 
                cat.get('parent_category'), cat.get('parent_id'))
            synced += 1
    
    return {"success": True, "synced": synced, "total": len(categories)}


@api_router.get("/odoo/categories")
async def get_odoo_categories(user: dict = Depends(get_current_user)):
    """Get stored Odoo categories."""
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT * FROM odoo_categories ORDER BY parent_category NULLS FIRST, category_name
        ''')
        categories = [row_to_dict(r) for r in rows]
    return {"categories": categories}


@api_router.put("/odoo/categories/{category_id}/select")
async def toggle_odoo_category_selection(category_id: str, data: dict, user: dict = Depends(get_current_user)):
    """Toggle category selection for product sync."""
    is_selected = data.get('is_selected', False)
    async with pool.acquire() as conn:
        await conn.execute('''
            UPDATE odoo_categories SET is_selected = $1, updated_at = NOW() WHERE id = $2
        ''', is_selected, category_id)
    return {"success": True}


@api_router.put("/odoo/categories/bulk-select")
async def bulk_select_odoo_categories(data: dict, user: dict = Depends(get_current_user)):
    """Bulk update category selections."""
    category_ids = data.get('category_ids', [])
    is_selected = data.get('is_selected', False)
    async with pool.acquire() as conn:
        await conn.execute('''
            UPDATE odoo_categories SET is_selected = $1, updated_at = NOW() WHERE id = ANY($2)
        ''', is_selected, category_ids)
    return {"success": True, "updated": len(category_ids)}


@api_router.get("/supplier-categories")
async def get_supplier_categories(user: dict = Depends(get_current_user)):
    """Get unique supplier categories from synced products."""
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT DISTINCT category FROM products 
            WHERE category IS NOT NULL AND category != ''
            ORDER BY category
        ''')
        categories = [r['category'] for r in rows]
    return {"categories": categories}


@api_router.get("/category-mappings")
async def get_category_mappings(user: dict = Depends(get_current_user)):
    """Get all category mappings."""
    async with pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT cm.*, oc.category_name as odoo_category_name
            FROM category_mapping cm
            LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id
            ORDER BY cm.supplier_category_name
        ''')
        mappings = [row_to_dict(r) for r in rows]
    return {"mappings": mappings}


@api_router.post("/category-mappings")
async def create_or_update_mapping(data: dict, user: dict = Depends(get_current_user)):
    """Create or update a category mapping. Supports both Odoo and Lightspeed category IDs."""
    supplier_category = data.get('supplier_category_name')
    odoo_category_id = data.get('odoo_category_id')
    lightspeed_category_id = data.get('lightspeed_category_id')
    
    if not supplier_category:
        raise HTTPException(400, "Supplier category name is required")
    
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO category_mapping (id, supplier_category_name, odoo_category_id, lightspeed_category_id, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (supplier_category_name) DO UPDATE SET
                odoo_category_id = COALESCE(EXCLUDED.odoo_category_id, category_mapping.odoo_category_id),
                lightspeed_category_id = COALESCE(EXCLUDED.lightspeed_category_id, category_mapping.lightspeed_category_id),
                updated_at = NOW()
        ''', new_id(), supplier_category, odoo_category_id, lightspeed_category_id)
    
    return {"success": True}


@api_router.delete("/category-mappings/{mapping_id}")
async def delete_mapping(mapping_id: str, user: dict = Depends(get_current_user)):
    """Delete a category mapping."""
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM category_mapping WHERE id = $1', mapping_id)
    return {"success": True}


# ==================== PRODUCT PREPROCESSING & FINAL SYNC ====================

def calculate_sale_price(cost_price: float, markup_percentage: float) -> float:
    """Calculate sale price from cost with markup, rounded to nearest whole number."""
    if not cost_price or cost_price <= 0:
        return 0
    sale_price = cost_price + (cost_price * markup_percentage / 100)
    return round(sale_price)


@api_router.get("/preprocessing/products")
async def get_preprocessing_products(
    page: int = 1, 
    limit: int = 50, 
    status: str = None,
    user: dict = Depends(get_current_user)
):
    """Get products with preprocessing data for Odoo sync."""
    offset = (page - 1) * limit
    
    async with pool.acquire() as conn:
        # Get settings for markup
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        
        # Build query
        where_clause = ""
        if status:
            where_clause = f"WHERE p.preprocessing_status = '{status}'"
        
        # Get products with their data
        query = f'''
            SELECT 
                p.*,
                s.supplier_name,
                cm.odoo_category_id as mapped_odoo_category_id,
                oc.category_name as odoo_category_name,
                (SELECT COUNT(*) FROM product_variants pv WHERE pv.product_id = p.id) as variants_count,
                (SELECT COUNT(*) FROM product_media pm WHERE pm.product_id = p.id) as images_count,
                pss.sync_status,
                pss.sale_price as calculated_sale_price,
                pss.validation_errors,
                pss.last_sync_date
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.id
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id
            LEFT JOIN product_sync_status pss ON p.id = pss.product_id
            {where_clause}
            ORDER BY p.updated_at DESC
            LIMIT $1 OFFSET $2
        '''
        
        rows = await conn.fetch(query, limit, offset)
        
        # Get total count
        count_query = f"SELECT COUNT(*) FROM products p {where_clause}"
        total = await conn.fetchval(count_query)
        
        products = []
        for row in rows:
            product = row_to_dict(row)
            # Calculate sale price if not already calculated
            cost_price = float(product.get('base_price') or 0)
            if not product.get('calculated_sale_price'):
                product['calculated_sale_price'] = calculate_sale_price(cost_price, markup)
            product['cost_price'] = cost_price
            product['markup_percentage'] = markup
            
            # Determine validation status
            errors = []
            if not product.get('mapped_odoo_category_id'):
                errors.append("Missing category mapping")
            if not product.get('images_count') or product['images_count'] == 0:
                errors.append("No images")
            if cost_price <= 0:
                errors.append("Invalid price")
            
            product['validation_errors'] = errors
            product['is_valid'] = len(errors) == 0
            product['status'] = 'ready' if len(errors) == 0 else 'invalid'
            
            products.append(product)
        
        return {
            "products": products,
            "total": total,
            "page": page,
            "limit": limit,
            "markup_percentage": markup
        }


@api_router.get("/preprocessing/summary")
async def get_preprocessing_summary(user: dict = Depends(get_current_user)):
    """Get summary statistics for preprocessing."""
    async with pool.acquire() as conn:
        # Total products
        total_products = await conn.fetchval("SELECT COUNT(*) FROM products")
        
        # Total variants
        total_variants = await conn.fetchval("SELECT COUNT(*) FROM product_variants")
        
        # Products with category mapping
        mapped_count = await conn.fetchval('''
            SELECT COUNT(DISTINCT p.id) FROM products p
            INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE cm.odoo_category_id IS NOT NULL
        ''')
        
        # Products without category mapping
        unmapped_count = await conn.fetchval('''
            SELECT COUNT(*) FROM products p
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE cm.odoo_category_id IS NULL OR p.category IS NULL OR p.category = ''
        ''')
        
        # Products with images
        with_images = await conn.fetchval('''
            SELECT COUNT(DISTINCT product_id) FROM product_media
        ''')
        
        # Products without images
        without_images = total_products - with_images
        
        # Products with valid price
        with_price = await conn.fetchval("SELECT COUNT(*) FROM products WHERE base_price > 0")
        
        # Sync status counts
        synced = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'synced'")
        pending = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'pending' OR odoo_sync_status IS NULL")
        failed = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'failed'")
        
        # Ready for sync (has mapping, price, images)
        ready_for_sync = await conn.fetchval('''
            SELECT COUNT(DISTINCT p.id) FROM products p
            INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name
            WHERE cm.odoo_category_id IS NOT NULL 
            AND p.base_price > 0
            AND p.odoo_sync_status != 'synced'
        ''')
        
        return {
            "total_products": total_products,
            "total_variants": total_variants,
            "category_mapping": {
                "mapped": mapped_count,
                "unmapped": unmapped_count
            },
            "images": {
                "with_images": with_images,
                "without_images": without_images
            },
            "pricing": {
                "with_price": with_price,
                "without_price": total_products - with_price
            },
            "sync_status": {
                "synced": synced,
                "pending": pending,
                "failed": failed,
                "ready": ready_for_sync
            }
        }


@api_router.post("/preprocessing/recalculate-prices")
async def recalculate_all_prices(user: dict = Depends(get_current_user)):
    """Recalculate sale prices for all products based on current markup."""
    async with pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        
        products = await conn.fetch("SELECT id, base_price FROM products WHERE base_price > 0")
        updated = 0
        
        for p in products:
            cost = float(p['base_price'])
            sale_price = calculate_sale_price(cost, markup)
            
            # Update or insert sync status
            await conn.execute('''
                INSERT INTO product_sync_status (id, product_id, cost_price, sale_price, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (product_id) DO UPDATE SET
                    cost_price = EXCLUDED.cost_price,
                    sale_price = EXCLUDED.sale_price,
                    updated_at = NOW()
            ''', new_id(), p['id'], cost, sale_price)
            updated += 1
        
        return {"success": True, "updated": updated, "markup_percentage": markup}


@api_router.post("/preprocessing/validate-products")
async def validate_products_for_sync(data: dict = None, user: dict = Depends(get_current_user)):
    """Validate products and prepare them for Odoo sync."""
    product_ids = data.get('product_ids', []) if data else []
    
    async with pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        
        # Get products to validate
        if product_ids:
            products = await conn.fetch("SELECT * FROM products WHERE id = ANY($1)", product_ids)
        else:
            products = await conn.fetch("SELECT * FROM products")
        
        validated = 0
        invalid = 0
        
        for p in products:
            product = row_to_dict(p)
            errors = []
            
            # Check category mapping
            mapping = await conn.fetchrow('''
                SELECT cm.odoo_category_id FROM category_mapping cm
                WHERE cm.supplier_category_name = $1 AND cm.odoo_category_id IS NOT NULL
            ''', product.get('category', ''))
            
            if not mapping:
                errors.append("Missing category mapping")
            
            # Check price
            cost = float(product.get('base_price') or 0)
            if cost <= 0:
                errors.append("Invalid or missing price")
            
            # Check images
            images_count = await conn.fetchval(
                "SELECT COUNT(*) FROM product_media WHERE product_id = $1", 
                product['id']
            )
            if images_count == 0:
                errors.append("No product images")
            
            # Calculate sale price
            sale_price = calculate_sale_price(cost, markup) if cost > 0 else 0
            
            # Determine status
            status = 'ready' if len(errors) == 0 else 'invalid'
            
            # Update sync status
            await conn.execute('''
                INSERT INTO product_sync_status (id, product_id, supplier_id, cost_price, sale_price, 
                    mapped_category_id, images_count, validation_errors, sync_status, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                ON CONFLICT (product_id) DO UPDATE SET
                    cost_price = EXCLUDED.cost_price,
                    sale_price = EXCLUDED.sale_price,
                    mapped_category_id = EXCLUDED.mapped_category_id,
                    images_count = EXCLUDED.images_count,
                    validation_errors = EXCLUDED.validation_errors,
                    sync_status = EXCLUDED.sync_status,
                    updated_at = NOW()
            ''', new_id(), product['id'], product.get('supplier_id'), cost, sale_price,
                mapping['odoo_category_id'] if mapping else None, images_count,
                json.dumps(errors), status)
            
            if len(errors) == 0:
                validated += 1
            else:
                invalid += 1
        
        return {
            "success": True,
            "total": len(products),
            "validated": validated,
            "invalid": invalid
        }


@api_router.post("/preprocessing/sync-to-odoo")
async def sync_preprocessed_to_odoo(data: dict = None, user: dict = Depends(get_current_user)):
    """Sync validated products to Odoo with full variant, image, and inventory support."""
    from odoo_service import OdooService
    
    product_ids = data.get('product_ids', []) if data else []
    sync_all = data.get('sync_all', False) if data else False
    
    async with pool.acquire() as conn:
        # Get settings
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row:
            raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)
        
        # Connect to Odoo
        odoo = OdooService(
            settings.get('odoo_url'), 
            settings.get('odoo_db'), 
            settings.get('odoo_username'), 
            settings.get('odoo_api_key')
        )
        
        conn_test = odoo.test_connection()
        if not conn_test.get('connected'):
            raise HTTPException(400, f"Odoo connection failed: {conn_test.get('message')}")
        
        # Get products to sync
        if sync_all:
            # Get all valid products (have category mapping and price)
            products = await conn.fetch('''
                SELECT p.*, cm.odoo_category_id, pss.sale_price
                FROM products p
                INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name
                LEFT JOIN product_sync_status pss ON p.id = pss.product_id
                WHERE cm.odoo_category_id IS NOT NULL 
                AND p.base_price > 0
                AND (p.odoo_sync_status != 'synced' OR p.odoo_sync_status IS NULL)
            ''')
        elif product_ids:
            products = await conn.fetch('''
                SELECT p.*, cm.odoo_category_id, pss.sale_price
                FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                LEFT JOIN product_sync_status pss ON p.id = pss.product_id
                WHERE p.id = ANY($1)
            ''', product_ids)
        else:
            return {"success": False, "error": "No products specified"}
        
        synced = 0
        failed = 0
        errors = []
        
        for p in products:
            product = row_to_dict(p)
            try:
                # Calculate sale price if not set
                cost = float(product.get('base_price') or 0)
                sale_price = product.get('sale_price') or calculate_sale_price(cost, markup)
                
                # Get variants
                variants = await conn.fetch(
                    "SELECT * FROM product_variants WHERE product_id = $1", 
                    product['id']
                )
                
                # Get images
                images = await conn.fetch(
                    "SELECT * FROM product_media WHERE product_id = $1", 
                    product['id']
                )
                
                # Prepare product data for Odoo
                odoo_data = {
                    'product_name': product.get('product_name'),
                    'supplier_sku': product.get('supplier_sku'),
                    'description': product.get('description'),
                    'base_price': sale_price,  # Use calculated sale price
                    'cost_price': cost,
                    'category_id': product.get('odoo_category_id'),  # e-commerce category
                    'default_category': 'SanMar Apparel',  # Inventory category
                    'variants': [row_to_dict(v) for v in variants],
                    'images': [row_to_dict(i) for i in images],
                }
                
                # Push to Odoo
                result = odoo.create_or_update_product(odoo_data)
                
                if result.get('success'):
                    # Update product status
                    await conn.execute('''
                        UPDATE products SET 
                            odoo_sync_status = 'synced', 
                            odoo_product_id = $1, 
                            calculated_sale_price = $2,
                            updated_at = NOW()
                        WHERE id = $3
                    ''', str(result.get('odoo_id', '')), sale_price, product['id'])
                    
                    # Update sync status
                    await conn.execute('''
                        UPDATE product_sync_status SET 
                            sync_status = 'synced',
                            odoo_product_id = $1,
                            last_sync_date = NOW(),
                            updated_at = NOW()
                        WHERE product_id = $2
                    ''', str(result.get('odoo_id', '')), product['id'])
                    
                    synced += 1
                else:
                    await conn.execute('''
                        UPDATE products SET odoo_sync_status = 'failed', updated_at = NOW()
                        WHERE id = $1
                    ''', product['id'])
                    failed += 1
                    errors.append({
                        'product_id': product['id'],
                        'sku': product.get('supplier_sku'),
                        'error': result.get('error')
                    })
                    
            except Exception as e:
                logger.error(f"Error syncing {product.get('supplier_sku')}: {e}")
                failed += 1
                errors.append({
                    'product_id': product['id'],
                    'sku': product.get('supplier_sku'),
                    'error': str(e)
                })
        
        return {
            "success": True,
            "total": len(products),
            "synced": synced,
            "failed": failed,
            "errors": errors[:10] if errors else [],  # Return first 10 errors
            "warning": "Images from SanMar CDN (media.sanmarcanada.com) are blocked. Contact SanMar to whitelist your server IP for image access." if failed == 0 and synced > 0 else None
        }


@api_router.get("/preprocessing/product/{product_id}/preview")
async def preview_product_for_odoo(product_id: str, user: dict = Depends(get_current_user)):
    """Preview how a product will look when synced to Odoo."""
    async with pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        
        product = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
        if not product:
            raise HTTPException(404, "Product not found")
        
        product = row_to_dict(product)
        
        # Get category mapping
        mapping = await conn.fetchrow('''
            SELECT cm.*, oc.category_name as odoo_category_name
            FROM category_mapping cm
            LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id
            WHERE cm.supplier_category_name = $1
        ''', product.get('category', ''))
        
        # Get variants
        variants = await conn.fetch(
            "SELECT * FROM product_variants WHERE product_id = $1 ORDER BY color, size", 
            product_id
        )
        
        # Get images
        images = await conn.fetch(
            "SELECT * FROM product_media WHERE product_id = $1", 
            product_id
        )
        
        # Calculate prices
        cost_price = float(product.get('base_price') or 0)
        sale_price = calculate_sale_price(cost_price, markup)
        
        # Build preview object
        preview = {
            "product_template": {
                "name": product.get('product_name'),
                "default_code": product.get('supplier_sku'),
                "description": product.get('description'),
                "list_price": sale_price,
                "standard_price": cost_price,
                "categ_id": mapping['odoo_category_id'] if mapping else None,
                "category_name": mapping['odoo_category_name'] if mapping else "Not Mapped",
                "type": "product",
                "sale_ok": True,
                "purchase_ok": True,
            },
            "attributes": {
                "colors": list(set(v['color'] for v in variants if v.get('color'))),
                "sizes": list(set(v['size'] for v in variants if v.get('size'))),
            },
            "variants": [
                {
                    "sku": v['variant_sku'],
                    "color": v.get('color'),
                    "size": v.get('size'),
                    "price": float(v.get('price') or sale_price),
                    "inventory": v.get('inventory', 0),
                }
                for v in variants
            ],
            "images": [
                {
                    "url": img['url'],
                    "type": img.get('media_type', 'image'),
                    "is_primary": img.get('is_primary', False),
                }
                for img in images
            ],
            "validation": {
                "is_valid": bool(mapping and cost_price > 0),
                "errors": []
            }
        }
        
        # Add validation errors
        if not mapping:
            preview["validation"]["errors"].append("Category not mapped")
        if cost_price <= 0:
            preview["validation"]["errors"].append("Invalid price")
        if len(images) == 0:
            preview["validation"]["errors"].append("No images")
        
        return preview


# ==================== MEDIA PROXY ====================
from fastapi.responses import StreamingResponse
import httpx

@api_router.get("/media_proxy")
async def media_proxy(url: str):
    """Proxy media requests to bypass CDN restrictions.
    
    Some supplier CDNs block direct image access (403 Forbidden).
    This endpoint fetches the image server-side and returns it to the client.
    """
    if not url:
        raise HTTPException(400, "URL parameter is required")
    
    # Validate URL is from an allowed domain (security measure)
    allowed_domains = [
        'cdn-atc.ca', 'cdn.ssactivewear.com', 'media.alphabroder.com',
        'images.atc.ca', 'atc.ca', 'ssactivewear.com', 'alphabroder.com',
        'www.atc.ca', 'www.ssactivewear.com', 'www.alphabroder.com'
    ]
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Check if domain is allowed (or contains an allowed domain)
        is_allowed = any(allowed in domain for allowed in allowed_domains)
        if not is_allowed:
            raise HTTPException(403, f"Domain not allowed: {domain}")
        
        # Fetch the image with proper headers
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': f'https://{domain}/',
            }
            
            response = await client.get(url, headers=headers, follow_redirects=True)
            
            if response.status_code != 200:
                raise HTTPException(response.status_code, f"Failed to fetch image: HTTP {response.status_code}")
            
            # Get content type from response or guess from URL
            content_type = response.headers.get('content-type', 'image/jpeg')
            if 'text/html' in content_type:
                raise HTTPException(403, "Received HTML instead of image - CDN may still be blocking")
            
            # Stream the response back
            return StreamingResponse(
                iter([response.content]),
                media_type=content_type,
                headers={
                    'Cache-Control': 'public, max-age=86400',
                    'Access-Control-Allow-Origin': '*',
                }
            )
            
    except httpx.RequestError as e:
        logger.error(f"Media proxy error: {e}")
        raise HTTPException(500, f"Failed to fetch media: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Media proxy error: {e}")
        raise HTTPException(500, f"Media proxy error: {str(e)}")


# ==================== HEALTH CHECK ====================
@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "database": "postgresql", "timestamp": utc_now_str()}


# Include router
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
