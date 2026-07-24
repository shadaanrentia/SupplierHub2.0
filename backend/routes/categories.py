"""Category mapping routes."""
from fastapi import APIRouter, Depends, HTTPException
import deps
from deps import row_to_dict, new_id, get_current_user

router = APIRouter(prefix="/api")


@router.get("/supplier-categories")
async def get_supplier_categories(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return {"categories": [r['category'] for r in rows]}


@router.get("/category-mappings")
async def get_category_mappings(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT cm.*, oc.category_name as odoo_category_name
            FROM category_mapping cm LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id
            ORDER BY cm.supplier_category_name
        ''')
        return {"mappings": [row_to_dict(r) for r in rows]}


@router.post("/category-mappings")
async def create_or_update_mapping(data: dict, user: dict = Depends(get_current_user)):
    supplier_category = data.get('supplier_category_name')
    odoo_category_id = data.get('odoo_category_id')
    lightspeed_category_id = data.get('lightspeed_category_id')
    if not supplier_category:
        raise HTTPException(400, "Supplier category name is required")
    async with deps.pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO category_mapping (id, supplier_category_name, odoo_category_id, lightspeed_category_id, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (supplier_category_name) DO UPDATE SET
                odoo_category_id = COALESCE(EXCLUDED.odoo_category_id, category_mapping.odoo_category_id),
                lightspeed_category_id = COALESCE(EXCLUDED.lightspeed_category_id, category_mapping.lightspeed_category_id),
                updated_at = NOW()
        ''', new_id(), supplier_category, odoo_category_id, lightspeed_category_id)
    return {"success": True}


@router.delete("/category-mappings/{mapping_id}")
async def delete_mapping(mapping_id: str, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        await conn.execute('DELETE FROM category_mapping WHERE id = $1', mapping_id)
    return {"success": True}
