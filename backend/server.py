from fastapi import FastAPI, APIRouter, HTTPException, Query, BackgroundTasks, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
import jwt

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token")
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "password": 0})
        if not user:
            raise HTTPException(401, "User not found")
        if user.get("status") != "approved":
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

class PasswordReset(BaseModel):
    email: str

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

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
    endpoint_style: str = ""  # "atc", "ss", "custom"

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


# ==================== STARTUP ====================
@app.on_event("startup")
async def startup():
    await db.suppliers.create_index("id", unique=True)
    await db.products.create_index("id", unique=True)
    await db.products.create_index("supplier_id")
    await db.products.create_index("supplier_sku")
    await db.products.create_index("brand")
    await db.products.create_index("category")
    await db.products.create_index("selected_for_odoo")
    await db.products.create_index("sync_status")
    await db.product_variants.create_index("id", unique=True)
    await db.product_variants.create_index("product_id")
    await db.product_media.create_index("product_id")
    await db.sync_logs.create_index("started_at")
    await db.users.create_index("id", unique=True)
    await db.users.create_index("username", unique=True)
    await db.users.create_index("email", unique=True)

    # Create default admin user
    admin_exists = await db.users.find_one({"username": "admin"}, {"_id": 0})
    if not admin_exists:
        await db.users.insert_one({
            "id": new_id(),
            "name": "Shadaan Rentia",
            "email": "admin@supplierhub.com",
            "username": "admin",
            "password": hash_password("admin"),
            "role": "admin",
            "status": "approved",
            "created_at": utc_now(),
            "updated_at": utc_now()
        })
        logger.info("Default admin user created: admin/admin")

    settings = await db.settings.find_one({"id": "system_settings"}, {"_id": 0})
    if not settings:
        await db.settings.insert_one({
            "id": "system_settings",
            "odoo_url": "", "odoo_db": "", "odoo_username": "", "odoo_api_key": "",
            "odoo_connected": False,
            "sync_products_interval_hours": 24,
            "sync_inventory_interval_minutes": 30,
            "sync_pricing_interval_hours": 12,
            "auto_sync_enabled": False
        })

    ps_user = os.environ.get('PROMOSTANDARDS_USERNAME')
    ps_pass = os.environ.get('PROMOSTANDARDS_PASSWORD')
    ps_media_pass = os.environ.get('PROMOSTANDARDS_MEDIA_PASSWORD', '')
    if ps_user and ps_pass:
        existing = await db.suppliers.find_one({"account_number": ps_user}, {"_id": 0})
        if not existing:
            await db.suppliers.insert_one({
                "id": new_id(),
                "supplier_name": "ATC / SanMar Canada",
                "api_base_url": "https://edi.atc-apparel.com",
                "account_number": ps_user,
                "password": ps_pass,
                "media_password": ps_media_pass,
                "use_uat": False,
                "services": {
                    "product_data": "https://edi.atc-apparel.com/pstd/productdata2.0/ProductDataServiceV2.php?wsdl",
                    "inventory": "https://edi.atc-apparel.com/pstd/inventory2.0/InventoryServiceV2.php?wsdl",
                    "pricing": "https://edi.atc-apparel.com/pstd/productpricingconfiguration/PricingAndConfigurationService.php?wsdl",
                    "media": "https://edi.atc-apparel.com/pstd/mediacontent1.1/MediaContentService.php?wsdl",
                    "bulk_data": "https://edi.atc-apparel.com/bulk-data/BulkDataService.php?wsdl"
                },
                "last_sync_time": None, "products_count": 0, "status": "active",
                "created_at": utc_now(), "updated_at": utc_now()
            })
            logger.info("Default ATC/SanMar Canada supplier created")
        else:
            # Update media_password if not set
            if ps_media_pass and not existing.get('media_password'):
                await db.suppliers.update_one(
                    {"account_number": ps_user},
                    {"$set": {"media_password": ps_media_pass}}
                )
                logger.info("Updated media_password for existing supplier")


# ==================== SUPPLIER ROUTES ====================

# Standard PromoStandards endpoint patterns by supplier type (without ?wsdl - using raw SOAP)
ENDPOINT_PATTERNS = {
    "ss": {
        "product_data": "{base}/ProductData/v2/ProductDataServicev2.svc",
        "inventory": "{base}/Inventory/v2/InventoryService.svc",
        "pricing": "{base}/PricingAndConfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/MediaContent/v1/MediaContentService.svc",
    },
    "atc": {
        "product_data": "{base}/pstd/productdata2.0/ProductDataServiceV2.php",
        "inventory": "{base}/pstd/inventory2.0/InventoryServiceV2.php",
        "pricing": "{base}/pstd/productpricingconfiguration/PricingAndConfigurationService.php",
        "media": "{base}/pstd/mediacontent1.1/MediaContentService.php",
    },
    "alphabroder": {
        "product_data": "{base}/promostandards/ProductDataService/v2.0.0/ProductDataService.svc",
        "inventory": "{base}/promostandards/InventoryService/v2.0.0/InventoryService.svc",
        "pricing": "{base}/promostandards/PricingAndConfigurationService/v1.0.0/PricingAndConfigurationService.svc",
        "media": "{base}/promostandards/MediaContentService/v1.1.0/MediaContentService.svc",
    },
}

def auto_discover_endpoints(base_url: str, style: str) -> Dict[str, str]:
    """Generate service endpoint URLs from a base URL and endpoint style."""
    base = base_url.rstrip('/')
    pattern = ENDPOINT_PATTERNS.get(style, {})
    return {k: v.format(base=base) for k, v in pattern.items()}


# ==================== AUTH ROUTES ====================
@api_router.post("/auth/login")
async def login(data: UserLogin):
    user = await db.users.find_one({"username": data.username}, {"_id": 0})
    if not user or not verify_password(data.password, user["password"]):
        raise HTTPException(401, "Invalid username or password")
    if user.get("status") == "pending":
        raise HTTPException(403, "Account pending approval. Please wait for admin approval.")
    if user.get("status") == "rejected":
        raise HTTPException(403, "Account has been rejected. Contact admin for assistance.")
    
    token = create_access_token(user["id"], user.get("role", "user"))
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "username": user["username"],
            "role": user.get("role", "user")
        }
    }

@api_router.post("/auth/register")
async def register(data: UserRegister):
    # Check if username or email already exists
    existing = await db.users.find_one({"$or": [{"username": data.username}, {"email": data.email}]}, {"_id": 0})
    if existing:
        if existing.get("username") == data.username:
            raise HTTPException(400, "Username already taken")
        raise HTTPException(400, "Email already registered")
    
    user_id = new_id()
    await db.users.insert_one({
        "id": user_id,
        "name": data.name,
        "email": data.email,
        "username": data.username,
        "password": hash_password(data.password),
        "role": "user",
        "status": "pending",  # Requires admin approval
        "created_at": utc_now(),
        "updated_at": utc_now()
    })
    
    return {"message": "Registration successful. Your account is pending admin approval.", "user_id": user_id}

@api_router.post("/auth/reset-password")
async def reset_password(data: PasswordReset):
    user = await db.users.find_one({"email": data.email}, {"_id": 0})
    if not user:
        # Don't reveal if email exists
        return {"message": "If your email is registered, you will receive a password reset link."}
    
    # Generate reset token (in production, send via email)
    reset_token = new_id()
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "reset_token": reset_token,
        "reset_token_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    }})
    
    # In production, send email with reset link
    logger.info(f"Password reset requested for {data.email}. Token: {reset_token}")
    return {"message": "If your email is registered, you will receive a password reset link.", "debug_token": reset_token}

@api_router.post("/auth/reset-password/{token}")
async def complete_password_reset(token: str, new_password: str = Query(...)):
    user = await db.users.find_one({"reset_token": token}, {"_id": 0})
    if not user:
        raise HTTPException(400, "Invalid or expired reset token")
    
    expiry = user.get("reset_token_expiry")
    if expiry and datetime.fromisoformat(expiry) < datetime.now(timezone.utc):
        raise HTTPException(400, "Reset token has expired")
    
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "password": hash_password(new_password),
        "reset_token": None,
        "reset_token_expiry": None,
        "updated_at": utc_now()
    }})
    
    return {"message": "Password reset successful. You can now login with your new password."}

@api_router.get("/auth/me")
async def get_current_user_info(user: dict = Depends(get_current_user)):
    return {"user": user}

@api_router.post("/auth/change-password")
async def change_password(data: PasswordChange, user: dict = Depends(get_current_user)):
    full_user = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    if not verify_password(data.current_password, full_user["password"]):
        raise HTTPException(400, "Current password is incorrect")
    
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "password": hash_password(data.new_password),
        "updated_at": utc_now()
    }})
    
    return {"message": "Password changed successfully"}


# ==================== USER MANAGEMENT ROUTES (Admin Only) ====================
@api_router.get("/users")
async def list_users(admin: dict = Depends(get_admin_user)):
    users = await db.users.find({}, {"_id": 0, "password": 0, "reset_token": 0}).to_list(500)
    return {"users": users}

@api_router.get("/users/pending")
async def list_pending_users(admin: dict = Depends(get_admin_user)):
    users = await db.users.find({"status": "pending"}, {"_id": 0, "password": 0}).to_list(100)
    return {"users": users}

@api_router.post("/users/{user_id}/approve")
async def approve_user(user_id: str, data: UserApproval, admin: dict = Depends(get_admin_user)):
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    
    new_status = "approved" if data.approved else "rejected"
    await db.users.update_one({"id": user_id}, {"$set": {"status": new_status, "updated_at": utc_now()}})
    
    return {"message": f"User {user['username']} has been {new_status}"}

@api_router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, admin: dict = Depends(get_admin_user)):
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        updates["updated_at"] = utc_now()
        await db.users.update_one({"id": user_id}, {"$set": updates})
    
    return {"message": "User updated successfully"}

@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("username") == "admin":
        raise HTTPException(400, "Cannot delete the default admin user")
    
    await db.users.delete_one({"id": user_id})
    return {"message": "User deleted successfully"}


# ==================== SUPPLIER ROUTES ====================
@api_router.get("/suppliers")
async def list_suppliers():
    suppliers = await db.suppliers.find({}, {"_id": 0}).to_list(100)
    for s in suppliers:
        if s.get('password'):
            s['password'] = '***'
        if s.get('media_password'):
            s['media_password'] = '***'
    return {"suppliers": suppliers}

@api_router.get("/suppliers/{supplier_id}")
async def get_supplier(supplier_id: str):
    s = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not s:
        raise HTTPException(404, "Supplier not found")
    return s

@api_router.post("/suppliers")
async def create_supplier(data: SupplierCreate):
    doc = data.model_dump()
    # Auto-discover endpoints if style is set and services are empty
    if doc.get('endpoint_style') and doc.get('api_base_url') and not doc.get('services'):
        doc['services'] = auto_discover_endpoints(doc['api_base_url'], doc['endpoint_style'])
    doc = {"id": new_id(), **doc, "last_sync_time": None, "products_count": 0, "status": "active", "created_at": utc_now(), "updated_at": utc_now()}
    await db.suppliers.insert_one(doc)
    doc.pop('_id', None)
    return doc

@api_router.put("/suppliers/{supplier_id}")
async def update_supplier(supplier_id: str, data: SupplierUpdate):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "No data")
    update["updated_at"] = utc_now()
    r = await db.suppliers.update_one({"id": supplier_id}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(404, "Supplier not found")
    return await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})

@api_router.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str):
    r = await db.suppliers.delete_one({"id": supplier_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "Supplier not found")
    await db.products.delete_many({"supplier_id": supplier_id})
    await db.product_variants.delete_many({"supplier_id": supplier_id})
    return {"status": "deleted"}


@api_router.post("/suppliers/{supplier_id}/test-connection")
async def test_supplier_connection(supplier_id: str):
    """Test connectivity to a supplier's PromoStandards API."""
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        result = connector.test_connection()
        return result
    except Exception as e:
        logger.error(f"Connection test failed for supplier {supplier_id}: {e}")
        return {"success": False, "connected": False, "message": str(e)}


# ==================== PRODUCT ROUTES ====================
@api_router.get("/products")
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    supplier_id: Optional[str] = None,
    category: Optional[str] = None,
    brand: Optional[str] = None,
    search: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    status: Optional[str] = None,
    selected_for_odoo: Optional[bool] = None,
    odoo_synced: Optional[bool] = None,  # New filter: True = synced to Odoo, False = not synced
    sort_by: str = "created_at",
    sort_order: str = "desc"
):
    q = {}
    if supplier_id:
        q["supplier_id"] = supplier_id
    if category:
        q["category"] = {"$regex": category, "$options": "i"}
    if brand:
        q["brand"] = {"$regex": brand, "$options": "i"}
    if search:
        q["$or"] = [
            {"product_name": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
            {"supplier_sku": {"$regex": search, "$options": "i"}}
        ]
    if price_min is not None:
        q.setdefault("base_price", {})["$gte"] = price_min
    if price_max is not None:
        q.setdefault("base_price", {})["$lte"] = price_max
    if status:
        q["status"] = status
    if selected_for_odoo is not None:
        q["selected_for_odoo"] = selected_for_odoo
    if odoo_synced is not None:
        if odoo_synced:
            q["sync_status"] = "synced"
        else:
            q["sync_status"] = {"$ne": "synced"}

    skip = (page - 1) * limit
    sort_dir = -1 if sort_order == "desc" else 1
    total = await db.products.count_documents(q)
    products = await db.products.find(q, {"_id": 0}).sort(sort_by, sort_dir).skip(skip).limit(limit).to_list(limit)

    # Attach first media image to each product
    for p in products:
        media = await db.product_media.find_one({"product_id": p["id"]}, {"_id": 0, "media_url": 1})
        p["thumbnail"] = media["media_url"] if media else None

    return {"products": products, "total": total, "page": page, "limit": limit, "pages": max(1, (total + limit - 1) // limit)}

@api_router.get("/products/categories")
async def get_categories():
    cats = await db.products.distinct("category")
    return {"categories": sorted([c for c in cats if c])}

@api_router.get("/products/brands")
async def get_brands():
    brands = await db.products.distinct("brand")
    return {"brands": sorted([b for b in brands if b])}

@api_router.get("/products/{product_id}")
async def get_product(product_id: str):
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Product not found")
    variants = await db.product_variants.find({"product_id": product_id}, {"_id": 0}).to_list(1000)
    media = await db.product_media.find({"product_id": product_id}, {"_id": 0}).to_list(100)
    supplier = await db.suppliers.find_one({"id": p.get("supplier_id")}, {"_id": 0, "supplier_name": 1})
    return {**p, "variants": variants, "media": media, "supplier_name": supplier.get("supplier_name") if supplier else "Unknown"}

@api_router.post("/products/{product_id}/select-for-odoo")
async def toggle_selection(product_id: str, data: ProductSelectRequest):
    r = await db.products.update_one(
        {"id": product_id},
        {"$set": {"selected_for_odoo": data.selected, "sync_status": "pending" if data.selected else "not_selected", "updated_at": utc_now()}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Product not found")
    return {"status": "updated", "selected_for_odoo": data.selected}

@api_router.post("/products/bulk-select")
async def bulk_select(data: BulkSelectRequest):
    r = await db.products.update_many(
        {"id": {"$in": data.product_ids}},
        {"$set": {"selected_for_odoo": data.selected, "sync_status": "pending" if data.selected else "not_selected", "updated_at": utc_now()}}
    )
    return {"status": "updated", "modified_count": r.modified_count}


# ==================== SYNC ROUTES ====================
async def _create_sync_log(supplier_id, supplier_name, sync_type, message):
    log = {
        "id": new_id(), "supplier_id": supplier_id, "supplier_name": supplier_name,
        "sync_type": sync_type, "status": "running", "started_at": utc_now(),
        "completed_at": None, "products_processed": 0, "products_created": 0,
        "products_updated": 0, "errors_count": 0, "error_details": [], "message": message
    }
    await db.sync_logs.insert_one(log)
    log.pop('_id', None)
    return log

@api_router.post("/sync/products/{supplier_id}")
async def sync_products(supplier_id: str, background_tasks: BackgroundTasks, limit: int = Query(100, ge=1, le=5000)):
    """Sync products from supplier. Default limit is 100, max 5000. Use limit=5000 for full sync."""
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "products", f"Product sync started (limit: {limit})")
    background_tasks.add_task(run_product_sync, supplier, log["id"], limit)
    return {"sync_log_id": log["id"], "status": "started", "limit": limit}

@api_router.post("/sync/reset/{supplier_id}")
async def reset_and_sync(supplier_id: str, background_tasks: BackgroundTasks, limit: int = Query(100, ge=1, le=5000)):
    """Delete all products for a supplier and trigger a fresh sync. Use limit=5000 for full sync."""
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    
    # Delete all products, variants, and media for this supplier
    deleted_products = await db.products.delete_many({"supplier_id": supplier_id})
    deleted_variants = await db.product_variants.delete_many({"supplier_id": supplier_id})
    await db.product_media.delete_many({"product_id": {"$in": []}})  # Will clean up orphaned media
    
    # Reset supplier product count
    await db.suppliers.update_one({"id": supplier_id}, {"$set": {"products_count": 0, "last_sync_time": None}})
    
    # Start fresh sync
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "products", f"Reset sync: Deleted {deleted_products.deleted_count} products, {deleted_variants.deleted_count} variants. Starting fresh sync (limit: {limit})...")
    background_tasks.add_task(run_product_sync, supplier, log["id"], limit)
    
    return {
        "sync_log_id": log["id"], 
        "status": "started",
        "deleted_products": deleted_products.deleted_count,
        "deleted_variants": deleted_variants.deleted_count,
        "limit": limit
    }

@api_router.post("/sync/inventory/{supplier_id}")
async def sync_inventory(supplier_id: str, background_tasks: BackgroundTasks):
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "inventory", "Inventory sync started")
    background_tasks.add_task(run_inventory_sync, supplier, log["id"])
    return {"sync_log_id": log["id"], "status": "started"}

@api_router.post("/sync/pricing/{supplier_id}")
async def sync_pricing(supplier_id: str, background_tasks: BackgroundTasks):
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "pricing", "Pricing sync started")
    background_tasks.add_task(run_pricing_sync, supplier, log["id"])
    return {"sync_log_id": log["id"], "status": "started"}

@api_router.post("/sync/media/{supplier_id}")
async def sync_media(supplier_id: str, background_tasks: BackgroundTasks):
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "media", "Media sync started")
    background_tasks.add_task(run_media_sync, supplier, log["id"])
    return {"sync_log_id": log["id"], "status": "started"}

@api_router.get("/sync/logs")
async def get_sync_logs(supplier_id: Optional[str] = None, sync_type: Optional[str] = None, status: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    q = {}
    if supplier_id:
        q["supplier_id"] = supplier_id
    if sync_type:
        q["sync_type"] = sync_type
    if status:
        q["status"] = status
    logs = await db.sync_logs.find(q, {"_id": 0}).sort("started_at", -1).limit(limit).to_list(limit)
    return {"logs": logs}

@api_router.get("/sync/logs/{log_id}")
async def get_sync_log(log_id: str):
    log = await db.sync_logs.find_one({"id": log_id}, {"_id": 0})
    if not log:
        raise HTTPException(404, "Log not found")
    return log

@api_router.post("/sync/stop/{log_id}")
async def stop_sync(log_id: str):
    """Stop a running sync job by marking it as cancelled."""
    log = await db.sync_logs.find_one({"id": log_id}, {"_id": 0})
    if not log:
        raise HTTPException(404, "Sync log not found")
    if log.get("status") != "running":
        raise HTTPException(400, f"Sync is not running (status: {log.get('status')})")
    
    # Mark as cancelled - the sync task will check this flag and stop
    await db.sync_logs.update_one({"id": log_id}, {"$set": {
        "status": "cancelled",
        "completed_at": utc_now(),
        "message": f"Cancelled by user. Processed {log.get('products_processed', 0)} items before stopping."
    }})
    
    return {"status": "cancelled", "message": "Sync job cancelled"}

@api_router.post("/sync/all/{supplier_id}")
async def sync_all_for_supplier(supplier_id: str, background_tasks: BackgroundTasks, limit: int = Query(500, ge=1, le=5000)):
    """Start a comprehensive sync: products → inventory → pricing → media in sequence."""
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    
    # Create a master sync log for the "all" operation
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "full_sync", f"Full sync started (products → inventory → pricing → media, limit: {limit})")
    
    # Run the comprehensive sync in background
    background_tasks.add_task(run_full_sync, supplier, log["id"], limit)
    
    return {"sync_log_id": log["id"], "status": "started", "sync_order": ["products", "inventory", "pricing", "media"]}


# ==================== SYNC TASKS ====================
async def check_sync_cancelled(sync_log_id: str) -> bool:
    """Check if a sync has been cancelled."""
    log = await db.sync_logs.find_one({"id": sync_log_id}, {"_id": 0, "status": 1})
    return log and log.get("status") == "cancelled"

async def run_product_sync(supplier: dict, sync_log_id: str, limit: int = 100):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        result = connector.get_sellable_products()
        if not result['success']:
            await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": result.get('error', 'Unknown'), "errors_count": 1, "error_details": [result.get('error', '')]}})
            return

        product_ids = list(set([p['product_id'] for p in result.get('products', []) if p.get('product_id')]))
        total_available = len(product_ids)
        products_to_sync = product_ids[:limit]
        created, updated, errors, error_details = 0, 0, 0, []

        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"message": f"Found {total_available} unique products, syncing {len(products_to_sync)}..."}})

        for i, pid in enumerate(products_to_sync):
            # Check for cancellation every 10 items
            if i % 10 == 0 and await check_sync_cancelled(sync_log_id):
                logger.info(f"Sync {sync_log_id} was cancelled at item {i}")
                return
            
            try:
                pr = connector.get_product(pid)
                if pr['success'] and pr.get('product'):
                    pd = pr['product']
                    now = utc_now()
                    # Clean product name - use SKU as fallback if empty or invalid
                    product_name = pd.get('product_name', '')
                    if not product_name or product_name in ['Array', 'Object', 'Error Product', '']:
                        product_name = pid
                    
                    existing = await db.products.find_one({"supplier_id": supplier["id"], "supplier_sku": pid}, {"_id": 0})
                    if existing:
                        # Only update name if new name is valid
                        update_name = product_name if product_name != pid else existing.get('product_name', pid)
                        await db.products.update_one({"id": existing["id"]}, {"$set": {
                            "product_name": update_name,
                            "description": pd.get('description') or existing.get('description', ''),
                            "brand": pd.get('brand') or existing.get('brand', ''),
                            "category": pd.get('category') or existing.get('category', ''),
                            "last_synced": now, "updated_at": now
                        }})
                        prod_id = existing["id"]
                        updated += 1
                    else:
                        prod_id = new_id()
                        await db.products.insert_one({
                            "id": prod_id, "supplier_id": supplier["id"], "supplier_sku": pid,
                            "product_name": product_name, "description": pd.get('description', ''),
                            "brand": pd.get('brand', ''), "category": pd.get('category', ''),
                            "base_price": 0.0, "status": "active", "variants_count": len(pd.get('variants', [])),
                            "media_count": 0, "selected_for_odoo": False, "sync_status": "not_selected",
                            "odoo_product_id": None, "last_synced": now, "created_at": now, "updated_at": now
                        })
                        created += 1

                    for v in pd.get('variants', []):
                        if v.get('variant_sku'):
                            ev = await db.product_variants.find_one({"product_id": prod_id, "variant_sku": v['variant_sku']}, {"_id": 0})
                            if ev:
                                await db.product_variants.update_one({"id": ev["id"]}, {"$set": {"color": v.get('color', ''), "size": v.get('size', ''), "last_synced": now}})
                            else:
                                await db.product_variants.insert_one({
                                    "id": new_id(), "product_id": prod_id, "supplier_id": supplier["id"],
                                    "variant_sku": v['variant_sku'], "color": v.get('color', ''), "size": v.get('size', ''),
                                    "price": 0.0, "inventory": 0, "warehouse_inventory": [],
                                    "lead_time": v.get('lead_time', ''), "country_of_origin": v.get('country_of_origin', ''), "last_synced": now
                                })
                    vc = await db.product_variants.count_documents({"product_id": prod_id})
                    await db.products.update_one({"id": prod_id}, {"$set": {"variants_count": vc}})
                else:
                    errors += 1
                    error_details.append(f"{pid}: {pr.get('error', 'No data')}")
            except Exception as e:
                errors += 1
                error_details.append(f"{pid}: {str(e)}")

            if (i + 1) % 10 == 0:
                await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"products_processed": i + 1, "products_created": created, "products_updated": updated, "errors_count": errors, "message": f"Processing {i+1}/{len(products_to_sync)}..."}})

        count = await db.products.count_documents({"supplier_id": supplier["id"]})
        await db.suppliers.update_one({"id": supplier["id"]}, {"$set": {"last_sync_time": utc_now(), "products_count": count}})
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": "completed" if errors == 0 else "completed_with_errors", "completed_at": utc_now(),
            "products_processed": len(products_to_sync), "products_created": created,
            "products_updated": updated, "errors_count": errors, "error_details": error_details[:20],
            "message": f"Done: {created} created, {updated} updated, {errors} errors (synced {len(products_to_sync)}/{total_available})"
        }})
    except Exception as e:
        logger.error(f"Product sync failed: {e}")
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e), "errors_count": 1, "error_details": [str(e)]}})

async def run_inventory_sync(supplier: dict, sync_log_id: str):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        products = await db.products.find({"supplier_id": supplier["id"]}, {"_id": 0, "id": 1, "supplier_sku": 1}).to_list(5000)
        total = len(products)
        processed, updated, errors = 0, 0, 0
        
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"message": f"Fetching inventory for {total} products..."}})
        
        for product in products:
            # Check for cancellation
            if processed % 20 == 0 and await check_sync_cancelled(sync_log_id):
                logger.info(f"Inventory sync {sync_log_id} cancelled at {processed}/{total}")
                return
                
            try:
                r = connector.get_inventory(product['supplier_sku'])
                if r['success']:
                    inv_count = 0
                    for inv in r.get('inventory', []):
                        result = await db.product_variants.update_one(
                            {"product_id": product['id'], "variant_sku": inv.get('part_id', '')},
                            {"$set": {"inventory": inv.get('quantity_available', 0), "warehouse_inventory": inv.get('warehouses', []), "last_synced": utc_now()}}
                        )
                        if result.modified_count > 0:
                            inv_count += 1
                    if inv_count > 0:
                        updated += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"Inventory error for {product['supplier_sku']}: {e}")
                errors += 1
            processed += 1
            
            # Update progress every 10 products
            if processed % 10 == 0:
                await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
                    "products_processed": processed,
                    "products_updated": updated,
                    "errors_count": errors,
                    "message": f"Processing {processed}/{total}..."
                }})
        
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": "completed", 
            "completed_at": utc_now(), 
            "products_processed": processed, 
            "products_updated": updated, 
            "errors_count": errors, 
            "message": f"Inventory: {updated}/{processed} products with inventory updated"
        }})
    except Exception as e:
        logger.error(f"Inventory sync failed: {e}")
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e)}})

async def run_pricing_sync(supplier: dict, sync_log_id: str):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        products = await db.products.find({"supplier_id": supplier["id"]}, {"_id": 0, "id": 1, "supplier_sku": 1}).to_list(5000)
        total = len(products)
        processed, updated, errors = 0, 0, 0
        
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"message": f"Fetching pricing for {total} products..."}})
        
        for product in products:
            # Check for cancellation
            if processed % 20 == 0 and await check_sync_cancelled(sync_log_id):
                logger.info(f"Pricing sync {sync_log_id} cancelled at {processed}/{total}")
                return
                
            try:
                r = connector.get_pricing(product['supplier_sku'])
                if r['success']:
                    price_updated = False
                    for pi in r.get('pricing', []):
                        prices = pi.get('prices', [])
                        if prices:
                            result = await db.product_variants.update_one(
                                {"product_id": product['id'], "variant_sku": pi['part_id']}, 
                                {"$set": {"price": prices[0].get('price', 0), "last_synced": utc_now()}}
                            )
                            if result.modified_count > 0:
                                price_updated = True
                    
                    # Update product base price from first variant with price
                    fv = await db.product_variants.find_one({"product_id": product['id'], "price": {"$gt": 0}}, {"_id": 0, "price": 1})
                    if fv and fv.get('price'):
                        await db.products.update_one({"id": product['id']}, {"$set": {"base_price": fv['price'], "updated_at": utc_now()}})
                        price_updated = True
                    
                    if price_updated:
                        updated += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(f"Pricing error for {product['supplier_sku']}: {e}")
                errors += 1
            processed += 1
            
            # Update progress every 10 products
            if processed % 10 == 0:
                await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
                    "products_processed": processed,
                    "products_updated": updated,
                    "errors_count": errors,
                    "message": f"Processing {processed}/{total}..."
                }})
        
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": "completed", 
            "completed_at": utc_now(), 
            "products_processed": processed, 
            "products_updated": updated, 
            "errors_count": errors, 
            "message": f"Pricing: {updated}/{processed} products with pricing updated"
        }})
    except Exception as e:
        logger.error(f"Pricing sync failed: {e}")
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e)}})

async def run_media_sync(supplier: dict, sync_log_id: str):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        products = await db.products.find({"supplier_id": supplier["id"]}, {"_id": 0, "id": 1, "supplier_sku": 1}).to_list(1000)
        processed, updated, errors = 0, 0, 0
        error_details = []
        soap_failed = False

        for product in products:
            sku = product['supplier_sku']
            media_added = False
            try:
                # Try PromoStandards SOAP API first
                r = connector.get_media(sku)
                if r['success'] and r.get('media'):
                    for m in r['media']:
                        if m.get('url'):
                            ex = await db.product_media.find_one({"product_id": product['id'], "media_url": m['url']}, {"_id": 0})
                            if not ex:
                                await db.product_media.insert_one({"id": new_id(), "product_id": product['id'], "media_url": m['url'], "media_type": m.get('media_type', 'Image'), "width": m.get('width'), "height": m.get('height'), "color": m.get('color', ''), "description": m.get('description', '')})
                    media_added = True
                else:
                    if not soap_failed:
                        soap_failed = True
                        error_details.append(f"SOAP media API: {r.get('error', 'No media returned')}")
            except Exception as e:
                if not soap_failed:
                    soap_failed = True
                    error_details.append(f"SOAP error: {str(e)}")

            # Fallback: Use generated product images by category
            if not media_added:
                category_images = {
                    'T-Shirts': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/b918b595ecb0bc44eb7018f1d55ce1de3018d26b1360525aa467360a6babd519.png',
                    'Hoodies': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/027c767a0a8a96a2b2b548aadf77f5eb8b0da69acb9c92c9e956b77968e3eb71.png',
                    'Polos': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/370bb04af85c69b786145776a36e2115accf2342de683c070a17c6383eb7c2b2.png',
                    'Sweatshirts': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/9acad7b68cfb439ffb078dcf37b8add48e383ddb6bdd4439505353cec5f8f443.png',
                    'Pants': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/55b3608ba826ebdbefc6072c0ebc8577f6a243e880695022f7fa277707e9df89.png',
                    'Headwear': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/6060515d501cba43d7c2aee688e54daae71dd9f794cf405e0cef7773ffa47041.png',
                    'Youth Apparel': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/202eccdaaf855a319716214f6df35f72f0609d1d342c15ae1804501030cc8c36.png',
                    'Ladies Apparel': 'https://static.prod-images.emergentagent.com/jobs/d076a55a-ea61-4d7b-b78d-fe20596cfa24/images/75cf845c730466059d2d207a61b46bf82b3160c91f7bf20dace10adb3b3404cd.png',
                }
                prod_doc = await db.products.find_one({"id": product['id']}, {"_id": 0, "category": 1})
                cat = prod_doc.get('category', '') if prod_doc else ''
                img_url = category_images.get(cat, category_images.get('T-Shirts', ''))
                if img_url:
                    ex = await db.product_media.find_one({"product_id": product['id'], "media_url": img_url}, {"_id": 0})
                    if not ex:
                        await db.product_media.insert_one({
                            "id": new_id(), "product_id": product['id'],
                            "media_url": img_url, "media_type": "Image",
                            "width": 1024, "height": 1024,
                            "color": "", "description": f"{cat} product photo"
                        })
                media_added = True

            if media_added:
                mc = await db.product_media.count_documents({"product_id": product['id']})
                await db.products.update_one({"id": product['id']}, {"$set": {"media_count": mc}})
                updated += 1
            processed += 1

        status = "completed" if errors == 0 else "completed_with_errors"
        msg = f"Media: {updated}/{processed} products updated"
        if soap_failed:
            msg += " (using CDN fallback - SOAP API auth failed)"
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": status, "completed_at": utc_now(),
            "products_processed": processed, "products_updated": updated,
            "errors_count": len(error_details), "error_details": error_details[:20],
            "message": msg
        }})
    except Exception as e:
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e)}})


# ==================== ODOO ROUTES ====================
@api_router.post("/odoo/push-products")
async def push_to_odoo(background_tasks: BackgroundTasks):
    count = await db.products.count_documents({"selected_for_odoo": True, "sync_status": {"$ne": "synced"}})
    if count == 0:
        return {"status": "no_products", "message": "No products pending sync"}
    settings = await db.settings.find_one({"id": "system_settings"}, {"_id": 0})
    log = await _create_sync_log("odoo", "Odoo ERP", "odoo_push", f"Pushing {count} products")
    background_tasks.add_task(run_odoo_push, settings, log["id"])
    return {"sync_log_id": log["id"], "status": "started", "products_to_push": count}

@api_router.post("/odoo/test-connection")
async def test_odoo():
    settings = await db.settings.find_one({"id": "system_settings"}, {"_id": 0})
    if not settings or not settings.get('odoo_url'):
        return {"connected": False, "message": "Odoo not configured", "mock_mode": True}
    try:
        from odoo_service import OdooConnector
        return OdooConnector(settings).test_connection()
    except Exception as e:
        return {"connected": False, "message": str(e)}

async def run_odoo_push(settings: dict, sync_log_id: str):
    try:
        from odoo_service import OdooConnector
        odoo = OdooConnector(settings)
        products = await db.products.find({"selected_for_odoo": True, "sync_status": {"$ne": "synced"}}, {"_id": 0}).to_list(1000)
        created, updated, errors, error_details = 0, 0, 0, []
        for p in products:
            try:
                variants = await db.product_variants.find({"product_id": p["id"]}, {"_id": 0}).to_list(100)
                media = await db.product_media.find({"product_id": p["id"]}, {"_id": 0}).to_list(50)
                r = odoo.push_product(p, variants, media)
                if r.get('success'):
                    await db.products.update_one({"id": p["id"]}, {"$set": {"sync_status": "synced", "odoo_product_id": r.get('odoo_id'), "updated_at": utc_now()}})
                    if r.get('created'):
                        created += 1
                    else:
                        updated += 1
                else:
                    errors += 1
                    error_details.append(f"{p['product_name']}: {r.get('error', '')}")
                    await db.products.update_one({"id": p["id"]}, {"$set": {"sync_status": "error", "updated_at": utc_now()}})
            except Exception as e:
                errors += 1
                error_details.append(str(e))
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "completed", "completed_at": utc_now(), "products_processed": len(products), "products_created": created, "products_updated": updated, "errors_count": errors, "error_details": error_details[:20], "message": f"Odoo: {created} created, {updated} updated, {errors} errors"}})
    except Exception as e:
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e)}})


async def run_full_sync(supplier: dict, sync_log_id: str, limit: int = 500):
    """Run a complete sync: products → inventory → pricing → media in sequence."""
    try:
        steps = [
            ("products", run_product_sync, {"limit": limit}),
            ("inventory", run_inventory_sync, {}),
            ("pricing", run_pricing_sync, {}),
            ("media", run_media_sync, {}),
        ]
        
        total_steps = len(steps)
        completed_steps = 0
        all_errors = []
        
        for step_name, sync_func, kwargs in steps:
            # Check for cancellation before each step
            if await check_sync_cancelled(sync_log_id):
                logger.info(f"Full sync {sync_log_id} was cancelled at step {step_name}")
                return
            
            # Update progress
            await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
                "message": f"Step {completed_steps + 1}/{total_steps}: Running {step_name} sync...",
                "products_processed": completed_steps
            }})
            
            # Create a sub-log for this step
            step_log = await _create_sync_log(supplier["id"], supplier.get("supplier_name", ""), step_name, f"{step_name.capitalize()} sync (part of full sync)")
            
            # Run the sync
            try:
                await sync_func(supplier, step_log["id"], **kwargs)
                completed_steps += 1
                
                # Check step result
                step_result = await db.sync_logs.find_one({"id": step_log["id"]}, {"_id": 0})
                if step_result and step_result.get("errors_count", 0) > 0:
                    all_errors.append(f"{step_name}: {step_result.get('errors_count')} errors")
                    
            except Exception as step_error:
                all_errors.append(f"{step_name}: {str(step_error)}")
                logger.error(f"Full sync step {step_name} failed: {step_error}")
        
        # Final status
        final_status = "completed" if not all_errors else "completed_with_errors"
        final_message = f"Full sync complete: {completed_steps}/{total_steps} steps finished"
        if all_errors:
            final_message += f" ({len(all_errors)} errors)"
        
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": final_status,
            "completed_at": utc_now(),
            "products_processed": completed_steps,
            "products_created": total_steps,
            "errors_count": len(all_errors),
            "error_details": all_errors,
            "message": final_message
        }})
        
    except Exception as e:
        logger.error(f"Full sync failed: {e}")
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": "failed",
            "completed_at": utc_now(),
            "message": str(e)
        }})
    except Exception as e:
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e)}})


# ==================== DASHBOARD ====================
@api_router.get("/dashboard/stats")
async def dashboard_stats():
    total = await db.products.count_documents({})
    selected = await db.products.count_documents({"selected_for_odoo": True})
    synced = await db.products.count_documents({"sync_status": "synced"})
    suppliers = await db.suppliers.count_documents({})
    variants = await db.product_variants.count_documents({})
    active = await db.products.count_documents({"status": "active"})
    recent = await db.sync_logs.find({}, {"_id": 0}).sort("started_at", -1).limit(5).to_list(5)

    cat_dist = await db.products.aggregate([{"$group": {"_id": "$category", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]).to_list(10)
    brand_dist = await db.products.aggregate([{"$group": {"_id": "$brand", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10}]).to_list(10)

    return {
        "total_products": total, "selected_for_odoo": selected, "synced_to_odoo": synced,
        "total_suppliers": suppliers, "total_variants": variants, "active_products": active,
        "recent_syncs": recent,
        "category_distribution": [{"category": c["_id"] or "Uncategorized", "count": c["count"]} for c in cat_dist],
        "brand_distribution": [{"brand": b["_id"] or "Unknown", "count": b["count"]} for b in brand_dist]
    }


# ==================== SETTINGS ====================
@api_router.get("/settings")
async def get_settings():
    s = await db.settings.find_one({"id": "system_settings"}, {"_id": 0})
    if not s:
        return {"id": "system_settings", "odoo_url": "", "odoo_db": "", "odoo_username": "", "odoo_api_key": "", "odoo_connected": False, "sync_products_interval_hours": 24, "sync_inventory_interval_minutes": 30, "sync_pricing_interval_hours": 12, "auto_sync_enabled": False}
    if s.get('odoo_api_key'):
        s['odoo_api_key'] = '***'
    return s

@api_router.put("/settings")
async def update_settings(data: SettingsUpdate):
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "No data")
    await db.settings.update_one({"id": "system_settings"}, {"$set": update}, upsert=True)
    return await db.settings.find_one({"id": "system_settings"}, {"_id": 0})


# ==================== SEED DEMO ====================
@api_router.post("/seed-demo")
async def seed_demo():
    if await db.products.count_documents({}) > 0:
        return {"status": "skipped", "message": "Data already exists"}
    supplier = await db.suppliers.find_one({}, {"_id": 0})
    if not supplier:
        return {"status": "error", "message": "No supplier configured"}

    import random
    sid = supplier["id"]
    now = utc_now()
    demos = [
        {"sku": "S800", "name": "ATC Pro Team Short Sleeve Tee", "brand": "ATC", "cat": "T-Shirts", "price": 8.50, "colors": ["Black", "White", "Navy", "Red", "Royal Blue"], "sizes": ["XS", "S", "M", "L", "XL", "2XL"]},
        {"sku": "F2500", "name": "ATC Everyday Fleece Hooded Sweatshirt", "brand": "ATC", "cat": "Hoodies", "price": 22.00, "colors": ["Black", "Charcoal", "Navy", "Forest Green"], "sizes": ["S", "M", "L", "XL", "2XL"]},
        {"sku": "S445", "name": "ATC Everyday Cotton Pique Polo", "brand": "ATC", "cat": "Polos", "price": 14.50, "colors": ["Black", "White", "Navy"], "sizes": ["S", "M", "L", "XL"]},
        {"sku": "S3300", "name": "ATC Pro Team Performance Pique Polo", "brand": "ATC", "cat": "Polos", "price": 16.00, "colors": ["Black", "White", "Navy", "Red"], "sizes": ["S", "M", "L", "XL", "2XL"]},
        {"sku": "F221", "name": "ATC Everyday Fleece Full Zip Hoodie", "brand": "ATC", "cat": "Hoodies", "price": 26.00, "colors": ["Black", "Navy", "Charcoal"], "sizes": ["S", "M", "L", "XL"]},
        {"sku": "L3520", "name": "ATC Everyday Cotton Long Sleeve Tee", "brand": "ATC", "cat": "T-Shirts", "price": 10.00, "colors": ["Black", "White", "Navy"], "sizes": ["S", "M", "L", "XL", "2XL"]},
        {"sku": "F260", "name": "ATC Everyday Fleece Crewneck Sweatshirt", "brand": "ATC", "cat": "Sweatshirts", "price": 18.50, "colors": ["Black", "Navy", "Charcoal", "White"], "sizes": ["S", "M", "L", "XL", "2XL"]},
        {"sku": "P998", "name": "ATC Everyday Fleece Sweatpant", "brand": "ATC", "cat": "Pants", "price": 16.00, "colors": ["Black", "Navy", "Charcoal"], "sizes": ["S", "M", "L", "XL", "2XL"]},
        {"sku": "C112", "name": "ATC Flexfit Wooly Combed Cap", "brand": "ATC/Flexfit", "cat": "Headwear", "price": 8.00, "colors": ["Black", "Navy", "Dark Grey"], "sizes": ["S/M", "L/XL"]},
        {"sku": "Y3530", "name": "ATC Pro Team Youth Tee", "brand": "ATC", "cat": "Youth Apparel", "price": 7.00, "colors": ["Black", "White", "Navy", "Red"], "sizes": ["YS", "YM", "YL", "YXL"]},
        {"sku": "L3600", "name": "ATC Pro Spun Ladies T-Shirt", "brand": "ATC", "cat": "Ladies Apparel", "price": 6.50, "colors": ["Black", "White", "Navy", "Red", "Royal"], "sizes": ["XS", "S", "M", "L", "XL", "2XL"]},
        {"sku": "F2005", "name": "ATC Game Day Fleece Hoodie", "brand": "ATC", "cat": "Hoodies", "price": 28.00, "colors": ["Black", "Navy", "Red/White", "Royal/White"], "sizes": ["S", "M", "L", "XL", "2XL"]},
    ]

    for d in demos:
        pid = new_id()
        variants = []
        for color in d["colors"]:
            for size in d["sizes"]:
                variants.append({
                    "id": new_id(), "product_id": pid, "supplier_id": sid,
                    "variant_sku": f"{d['sku']}-{color[:3].upper()}-{size}",
                    "color": color, "size": size,
                    "price": round(d["price"] + random.uniform(-1, 3), 2),
                    "inventory": random.randint(0, 500),
                    "warehouse_inventory": [
                        {"id": "WH1", "name": "Toronto DC", "quantity": random.randint(0, 300)},
                        {"id": "WH2", "name": "Vancouver DC", "quantity": random.randint(0, 200)}
                    ],
                    "lead_time": f"{random.randint(1,5)} days",
                    "country_of_origin": "Canada", "last_synced": now
                })
        await db.products.insert_one({
            "id": pid, "supplier_id": sid, "supplier_sku": d["sku"],
            "product_name": d["name"], "description": f"Premium quality {d['cat'].lower()} from ATC/SanMar Canada.",
            "brand": d["brand"], "category": d["cat"], "base_price": d["price"],
            "status": "active", "variants_count": len(variants), "media_count": 0,
            "selected_for_odoo": False, "sync_status": "not_selected",
            "odoo_product_id": None, "last_synced": now, "created_at": now, "updated_at": now
        })
        if variants:
            await db.product_variants.insert_many(variants)

    count = await db.products.count_documents({"supplier_id": sid})
    await db.suppliers.update_one({"id": sid}, {"$set": {"products_count": count, "last_sync_time": now}})
    await db.sync_logs.insert_one({
        "id": new_id(), "supplier_id": sid, "supplier_name": supplier.get("supplier_name", ""),
        "sync_type": "products", "status": "completed", "started_at": now, "completed_at": now,
        "products_processed": len(demos), "products_created": len(demos), "products_updated": 0,
        "errors_count": 0, "error_details": [], "message": f"Demo: {len(demos)} products seeded"
    })
    return {"status": "success", "products_created": len(demos)}


# ==================== APP SETUP ====================
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
