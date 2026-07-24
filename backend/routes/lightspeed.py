"""Lightspeed (X-Series) routes: test, categories, push."""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import deps
from deps import row_to_dict, utc_now, new_id, get_current_user, calculate_sale_price, create_sync_log, update_sync_log
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/settings/lightspeed/test")
async def test_lightspeed_connection(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lightspeed_store_id, lightspeed_secret_token FROM settings WHERE id = 'system_settings'")
    if not row:
        raise HTTPException(404, "Settings not found")
    from lightspeed_service import LightspeedService
    ls = LightspeedService(row['lightspeed_store_id'], row['lightspeed_secret_token'])
    return ls.test_connection()


@router.get("/categories/lightspeed")
async def get_lightspeed_categories(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lightspeed_store_id, lightspeed_secret_token FROM settings WHERE id = 'system_settings'")
    if not row:
        raise HTTPException(404, "Settings not found")
    from lightspeed_service import LightspeedService
    ls = LightspeedService(row['lightspeed_store_id'], row['lightspeed_secret_token'])
    return ls.get_categories()


@router.post("/sync/lightspeed/{supplier_id}")
async def push_to_lightspeed(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        supplier = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not supplier:
            raise HTTPException(404, "Supplier not found")
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM products WHERE selected_for_lightspeed = TRUE AND lightspeed_sync_status = 'pending' AND supplier_id = $1",
            supplier_id)
    log_id = await create_sync_log(supplier_id, supplier['supplier_name'], "lightspeed_push", f"Pushing {count} products to Lightspeed...")
    background_tasks.add_task(lightspeed_push_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "products_to_push": count}


async def lightspeed_push_task(supplier_id: str, log_id: str):
    from lightspeed_service import LightspeedService
    try:
        async with deps.pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
            settings = row_to_dict(settings_row)
            markup = float(settings.get('markup_percentage') or 40)
            ls = LightspeedService(settings.get('lightspeed_store_id', ''), settings.get('lightspeed_secret_token', ''))
            conn_test = ls.test_connection()
            if not conn_test.get('connected'):
                await update_sync_log(log_id, 'failed', f"Lightspeed connection failed: {conn_test.get('message')}")
                return
            products = await conn.fetch('''
                SELECT p.*, cm.lightspeed_category_id FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                WHERE p.selected_for_lightspeed = TRUE AND p.lightspeed_sync_status = 'pending' AND p.supplier_id = $1
            ''', supplier_id)
        if not products:
            await update_sync_log(log_id, 'completed', 'No pending products for Lightspeed', progress=100)
            return
        synced = 0; failed = 0; total = len(products)
        for i, p in enumerate(products):
            product = row_to_dict(p)
            async with deps.pool.acquire() as conn:
                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
            cost = float(product.get('base_price') or 0)
            sale_price = calculate_sale_price(cost, markup)
            ls_data = {
                'product_name': product.get('product_name'), 'supplier_sku': product.get('supplier_sku'),
                'description': product.get('description'), 'base_price': sale_price, 'cost_price': cost,
                'category_id': product.get('lightspeed_category_id'),
                'variants': [row_to_dict(v) for v in variants], 'images': [row_to_dict(img) for img in images],
            }
            result = ls.create_or_update_product(ls_data)
            if result.get('success'):
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET lightspeed_sync_status = 'synced', lightspeed_product_id = $1, updated_at = $2 WHERE id = $3",
                        str(result.get('lightspeed_id', '')), utc_now(), product['id'])
                synced += 1
            else:
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET lightspeed_sync_status = 'failed', updated_at = $1 WHERE id = $2", utc_now(), product['id'])
                failed += 1
            # Update progress on every product for real-time tracking
            progress = int(((i + 1) / total) * 100)
            await update_sync_log(log_id, 'running', f'Pushed {synced}/{total} to Lightspeed ({failed} failed)', progress=progress, total=total, processed=synced)
        msg = f"Lightspeed push complete: {synced} synced, {failed} failed out of {total}"
        await update_sync_log(log_id, 'completed', msg, progress=100, total=total, processed=synced)
        logger.info(msg)
    except Exception as e:
        logger.error(f"Lightspeed push error: {e}")
        await update_sync_log(log_id, 'failed', f'Error: {str(e)}')
