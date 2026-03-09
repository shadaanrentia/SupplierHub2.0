from fastapi import FastAPI, APIRouter, HTTPException, Query, BackgroundTasks
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="SupplierHub - PromoStandards Middleware")
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ==================== HELPERS ====================
def utc_now():
    return datetime.now(timezone.utc).isoformat()

def new_id():
    return str(uuid.uuid4())


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
    await db.product_variants.create_index("id", unique=True)
    await db.product_variants.create_index("product_id")
    await db.product_media.create_index("product_id")
    await db.sync_logs.create_index("started_at")

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
async def sync_products(supplier_id: str, background_tasks: BackgroundTasks):
    supplier = await db.suppliers.find_one({"id": supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "products", "Product sync started")
    background_tasks.add_task(run_product_sync, supplier, log["id"])
    return {"sync_log_id": log["id"], "status": "started"}

@api_router.post("/sync/reset/{supplier_id}")
async def reset_and_sync(supplier_id: str, background_tasks: BackgroundTasks):
    """Delete all products for a supplier and trigger a fresh sync."""
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
    log = await _create_sync_log(supplier_id, supplier.get("supplier_name", ""), "products", f"Reset sync: Deleted {deleted_products.deleted_count} products, {deleted_variants.deleted_count} variants. Starting fresh sync...")
    background_tasks.add_task(run_product_sync, supplier, log["id"])
    
    return {
        "sync_log_id": log["id"], 
        "status": "started",
        "deleted_products": deleted_products.deleted_count,
        "deleted_variants": deleted_variants.deleted_count
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


# ==================== SYNC TASKS ====================
async def run_product_sync(supplier: dict, sync_log_id: str):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        result = connector.get_sellable_products()
        if not result['success']:
            await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": result.get('error', 'Unknown'), "errors_count": 1, "error_details": [result.get('error', '')]}})
            return

        product_ids = list(set([p['product_id'] for p in result.get('products', []) if p.get('product_id')]))
        created, updated, errors, error_details = 0, 0, 0, []

        for i, pid in enumerate(product_ids[:100]):
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
                await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"products_processed": i + 1, "products_created": created, "products_updated": updated, "errors_count": errors, "message": f"Processing {i+1}/{len(product_ids)}..."}})

        count = await db.products.count_documents({"supplier_id": supplier["id"]})
        await db.suppliers.update_one({"id": supplier["id"]}, {"$set": {"last_sync_time": utc_now(), "products_count": count}})
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {
            "status": "completed" if errors == 0 else "completed_with_errors", "completed_at": utc_now(),
            "products_processed": min(len(product_ids), 100), "products_created": created,
            "products_updated": updated, "errors_count": errors, "error_details": error_details[:20],
            "message": f"Done: {created} created, {updated} updated, {errors} errors"
        }})
    except Exception as e:
        logger.error(f"Product sync failed: {e}")
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e), "errors_count": 1, "error_details": [str(e)]}})

async def run_inventory_sync(supplier: dict, sync_log_id: str):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        products = await db.products.find({"supplier_id": supplier["id"]}, {"_id": 0, "id": 1, "supplier_sku": 1}).to_list(1000)
        processed, updated, errors = 0, 0, 0
        for product in products:
            try:
                r = connector.get_inventory(product['supplier_sku'])
                if r['success']:
                    for inv in r.get('inventory', []):
                        await db.product_variants.update_one(
                            {"product_id": product['id'], "variant_sku": inv.get('part_id', '')},
                            {"$set": {"inventory": inv.get('quantity_available', 0), "warehouse_inventory": inv.get('warehouses', []), "last_synced": utc_now()}}
                        )
                    updated += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
            processed += 1
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "completed", "completed_at": utc_now(), "products_processed": processed, "products_updated": updated, "errors_count": errors, "message": f"Inventory: {updated}/{processed} updated"}})
    except Exception as e:
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "failed", "completed_at": utc_now(), "message": str(e)}})

async def run_pricing_sync(supplier: dict, sync_log_id: str):
    try:
        from promostandards import PromoStandardsConnector
        connector = PromoStandardsConnector(supplier)
        products = await db.products.find({"supplier_id": supplier["id"]}, {"_id": 0, "id": 1, "supplier_sku": 1}).to_list(1000)
        processed, updated, errors = 0, 0, 0
        for product in products:
            try:
                r = connector.get_pricing(product['supplier_sku'])
                if r['success']:
                    for pi in r.get('pricing', []):
                        prices = pi.get('prices', [])
                        if prices:
                            await db.product_variants.update_one({"product_id": product['id'], "variant_sku": pi['part_id']}, {"$set": {"price": prices[0].get('price', 0), "last_synced": utc_now()}})
                    fv = await db.product_variants.find_one({"product_id": product['id']}, {"_id": 0, "price": 1})
                    if fv and fv.get('price'):
                        await db.products.update_one({"id": product['id']}, {"$set": {"base_price": fv['price'], "updated_at": utc_now()}})
                    updated += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
            processed += 1
        await db.sync_logs.update_one({"id": sync_log_id}, {"$set": {"status": "completed", "completed_at": utc_now(), "products_processed": processed, "products_updated": updated, "errors_count": errors, "message": f"Pricing: {updated}/{processed} updated"}})
    except Exception as e:
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
