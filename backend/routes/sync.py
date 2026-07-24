"""Sync routes: logs, trigger sync, background tasks, stop/status."""
import json
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
import deps
from deps import row_to_dict, new_id, utc_now, get_current_user, running_syncs, create_sync_log, update_sync_log
from promostandards import PromoStandardsConnector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# ==================== SYNC LOGS ====================
@router.get("/sync/logs")
async def get_sync_logs(
    supplier_id: Optional[str] = None, sync_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200), user: dict = Depends(get_current_user)
):
    async with deps.pool.acquire() as conn:
        conditions = []; values = []; param_idx = 1
        if supplier_id:
            conditions.append(f"supplier_id = ${param_idx}"); values.append(supplier_id); param_idx += 1
        if sync_type:
            conditions.append(f"sync_type = ${param_idx}"); values.append(sync_type); param_idx += 1
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM sync_logs WHERE {where_clause} ORDER BY start_time DESC LIMIT ${param_idx}"
        values.append(limit)
        rows = await conn.fetch(query, *values)
        return {"logs": [row_to_dict(r) for r in rows]}


@router.get("/sync/log/{log_id}")
async def get_sync_log_detail(log_id: str, user: dict = Depends(get_current_user)):
    """Get a single sync log by ID — used for real-time progress polling."""
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM sync_logs WHERE id = $1", log_id)
        if not row:
            raise HTTPException(404, "Sync log not found")
        return row_to_dict(row)


@router.post("/sync/stop/{task_id}")
async def stop_sync(task_id: str, user: dict = Depends(get_current_user)):
    if task_id in running_syncs:
        running_syncs[task_id]["should_stop"] = True
        return {"status": "stopping", "task_id": task_id}
    return {"status": "not_found", "task_id": task_id}


@router.get("/sync/status/{task_id}")
async def get_sync_status(task_id: str, user: dict = Depends(get_current_user)):
    if task_id in running_syncs:
        return {"status": "running", "task_id": task_id}
    return {"status": "not_running", "task_id": task_id}


# ==================== SYNC TRIGGERS ====================
@router.post("/sync/products/{supplier_id}")
async def sync_products(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "products", "Starting product sync...")
    background_tasks.add_task(sync_products_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"products_{supplier_id}"}


@router.post("/sync/inventory/{supplier_id}")
async def sync_inventory(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "inventory", "Starting inventory sync...")
    background_tasks.add_task(sync_inventory_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"inventory_{supplier_id}"}


@router.post("/sync/pricing/{supplier_id}")
async def sync_pricing(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "pricing", "Starting pricing sync...")
    background_tasks.add_task(sync_pricing_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"pricing_{supplier_id}"}


@router.post("/sync/media/{supplier_id}")
async def sync_media(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "media", "Starting media sync...")
    background_tasks.add_task(sync_media_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"media_{supplier_id}"}


@router.post("/sync/full/{supplier_id}")
async def sync_full(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "full", "Starting full sync...")
    background_tasks.add_task(sync_products_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"products_{supplier_id}"}


@router.post("/sync/all/{supplier_id}")
async def sync_all(supplier_id: str, background_tasks: BackgroundTasks, limit: int = Query(1500, ge=1), user: dict = Depends(get_current_user)):
    """Alias for /sync/full — triggers a full sync."""
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "full", f"Starting full sync (limit={limit})...")
    background_tasks.add_task(sync_products_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"products_{supplier_id}"}


@router.post("/sync/bulk-data/{supplier_id}")
async def sync_bulk_data(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "bulk_data", "Starting BulkData sync (products + images)...")
    background_tasks.add_task(sync_bulk_data_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"bulkdata_{supplier_id}", "message": "BulkData sync started"}


@router.post("/sync/enrich-categories/{supplier_id}")
async def enrich_categories(supplier_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT supplier_name FROM suppliers WHERE id = $1", supplier_id)
        if not row: raise HTTPException(404, "Supplier not found")
        count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE supplier_id = $1 AND (category IS NULL OR category = '')", supplier_id)
    if count == 0:
        return {"status": "no_action", "message": "All products already have categories"}
    log_id = await create_sync_log(supplier_id, row['supplier_name'], "enrich_categories", f"Enriching categories for {count} products...")
    background_tasks.add_task(enrich_categories_task, supplier_id, log_id)
    return {"status": "started", "log_id": log_id, "task_id": f"enrich_{supplier_id}", "products_to_enrich": count}


# ==================== INDIVIDUAL PRODUCT SYNC ====================
@router.post("/sync/product/{product_id}/inventory")
async def sync_product_inventory(product_id: str, user: dict = Depends(get_current_user)):
    return await _sync_product_inventory_internal(product_id)

@router.post("/sync/product/{product_id}/pricing")
async def sync_product_pricing(product_id: str, user: dict = Depends(get_current_user)):
    return await _sync_product_pricing_internal(product_id)

@router.post("/sync/product/{product_id}/media")
async def sync_product_media(product_id: str, user: dict = Depends(get_current_user)):
    return await _sync_product_media_internal(product_id)


@router.post("/sync/products/bulk")
async def sync_products_bulk(
    product_ids: List[str], sync_type: str = Query(..., regex="^(pricing|inventory|media)$"),
    background_tasks: BackgroundTasks = None, user: dict = Depends(get_current_user)
):
    results = {"success": 0, "failed": 0, "errors": []}
    async with deps.pool.acquire() as conn:
        for product_id in product_ids:
            try:
                row = await conn.fetchrow("SELECT p.id, p.supplier_sku, s.* FROM products p JOIN suppliers s ON p.supplier_id = s.id WHERE p.id = $1", product_id)
                if not row:
                    results["failed"] += 1; results["errors"].append(f"Product {product_id} not found"); continue
                product_sku = row['supplier_sku']; supplier = row_to_dict(row)
                connector = PromoStandardsConnector(supplier)
                if sync_type == "inventory":
                    result = connector.get_inventory(product_sku)
                    if result.get('success') and result.get('inventory'):
                        for inv in result['inventory']:
                            await conn.execute('UPDATE product_variants SET inventory = $1, warehouse_inventory = $2, updated_at = $3 WHERE product_id = $4 AND variant_sku = $5',
                                inv.get('quantity_available', 0), json.dumps(inv.get('warehouses', [])), utc_now(), product_id, inv.get('part_id', ''))
                        results["success"] += 1
                    else: results["failed"] += 1
                elif sync_type == "pricing":
                    result = connector.get_pricing(product_sku)
                    if result.get('success') and result.get('pricing'):
                        all_prices = []
                        for pi in result['pricing']:
                            prices = pi.get('prices', []); price = 0.0
                            if prices:
                                sp = sorted(prices, key=lambda x: x.get('min_quantity', 0))
                                price = float(sp[0].get('price', 0) or 0)
                                if price > 0: all_prices.append(price)
                            await conn.execute('UPDATE product_variants SET price = $1, updated_at = $2 WHERE product_id = $3 AND variant_sku = $4',
                                price, utc_now(), product_id, pi.get('part_id', ''))
                        if all_prices:
                            await conn.execute('UPDATE products SET base_price = $1, updated_at = $2 WHERE id = $3', min(all_prices), utc_now(), product_id)
                        results["success"] += 1
                    else: results["failed"] += 1
                elif sync_type == "media":
                    result = connector.get_media(product_sku)
                    if result.get('success') and result.get('media'):
                        for mi in result['media']:
                            url = mi.get('url', '')
                            existing = await conn.fetchrow("SELECT id FROM product_media WHERE product_id = $1 AND url = $2", product_id, url)
                            if not existing and url:
                                await conn.execute('INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)',
                                    new_id(), product_id, mi.get('type', 'image'), url, mi.get('description', ''), mi.get('is_primary', False), utc_now())
                        results["success"] += 1
                    else: results["failed"] += 1
            except Exception as e:
                results["failed"] += 1; results["errors"].append(f"Error for {product_id}: {str(e)}")
    return results


# ==================== AUTO-PUSH ====================
async def auto_push_to_odoo_if_enabled(supplier_id: str):
    try:
        async with deps.pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT auto_push_to_odoo, odoo_url, odoo_db, odoo_username, odoo_api_key, markup_percentage FROM settings WHERE id = 'system_settings'")
            if not settings_row or not settings_row.get('auto_push_to_odoo'): return
            if not settings_row.get('odoo_url'):
                logger.info("Auto-push: Odoo not configured, skipping"); return
            pending_count = await conn.fetchval("SELECT COUNT(*) FROM products WHERE selected_for_odoo = TRUE AND odoo_sync_status = 'pending' AND supplier_id = $1", supplier_id)
            if pending_count == 0: return
        logger.info("Auto-push: %d products pending for Odoo", pending_count)
        push_log_id = await create_sync_log(supplier_id, "Auto", "odoo_push", f"Auto-pushing {pending_count} products to Odoo...")
        await odoo_push_task(supplier_id, push_log_id)
    except Exception as e:
        logger.error("Auto-push to Odoo error: %s", e)


async def odoo_push_task(supplier_id: str, log_id: str):
    from odoo_service import OdooService
    from deps import calculate_sale_price
    try:
        async with deps.pool.acquire() as conn:
            settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
            settings = row_to_dict(settings_row)
            markup = float(settings.get('markup_percentage') or 40)
            products = await conn.fetch('''
                SELECT p.*, cm.odoo_category_id FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                WHERE p.selected_for_odoo = TRUE AND p.odoo_sync_status = 'pending' AND p.supplier_id = $1
            ''', supplier_id)
        if not products:
            await update_sync_log(log_id, 'completed', 'No pending products', progress=100); return
        odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
        conn_test = odoo.test_connection()
        if not conn_test.get('connected'):
            await update_sync_log(log_id, 'failed', f"Odoo connection failed: {conn_test.get('message')}"); return
        synced = 0; failed = 0
        for p in products:
            product = row_to_dict(p)
            async with deps.pool.acquire() as conn:
                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
            cost = float(product.get('base_price') or 0)
            sale_price = calculate_sale_price(cost, markup)
            odoo_data = {
                'product_name': product.get('product_name'), 'supplier_sku': product.get('supplier_sku'),
                'description': product.get('description'), 'base_price': sale_price, 'cost_price': cost,
                'category_id': product.get('odoo_category_id'), 'default_category': 'SanMar Apparel',
                'variants': [row_to_dict(v) for v in variants], 'images': [row_to_dict(i) for i in images],
            }
            result = odoo.create_or_update_product(odoo_data)
            if result.get('success'):
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET odoo_sync_status = 'synced', odoo_product_id = $1, updated_at = $2 WHERE id = $3",
                        str(result.get('odoo_id', '')), utc_now(), product['id'])
                synced += 1
            else:
                async with deps.pool.acquire() as conn:
                    await conn.execute("UPDATE products SET odoo_sync_status = 'failed', updated_at = $1 WHERE id = $2", utc_now(), product['id'])
                failed += 1
        msg = f"Auto-push complete: {synced} synced, {failed} failed out of {len(products)}"
        await update_sync_log(log_id, 'completed', msg, progress=100, total=len(products), processed=synced)
        logger.info("Auto-push: %s", msg)
    except Exception as e:
        logger.error("Odoo push task error: %s", e)
        await update_sync_log(log_id, 'failed', f'Error: {str(e)}')


# ==================== BACKGROUND TASKS ====================
async def sync_products_task(supplier_id: str, log_id: str):
    task_id = f"products_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    try:
        async with deps.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not row: await update_sync_log(log_id, "failed", "Supplier not found"); return
            supplier = row_to_dict(row)
        connector = PromoStandardsConnector(supplier)
        await update_sync_log(log_id, "running", "Fetching product list...", 0)
        result = connector.get_sellable_products()
        if not result.get('success'):
            await update_sync_log(log_id, "failed", f"Failed to get products: {result.get('error')}"); return
        products = result.get('products', [])
        unique_skus = list(set(p['product_id'] for p in products))
        total = len(unique_skus)
        await update_sync_log(log_id, "running", f"Found {total} unique products", 0, total, 0)
        processed = 0
        for sku in unique_skus:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await update_sync_log(log_id, "stopped", f"Stopped by user. Processed {processed}/{total}", int(processed/total*100), total, processed); return
            try:
                product_data = connector.get_product(sku)
                if product_data.get('success') and product_data.get('product'):
                    p = product_data['product']
                    product_id = new_id()
                    async with deps.pool.acquire() as conn:
                        existing = await conn.fetchrow("SELECT id FROM products WHERE supplier_id = $1 AND supplier_sku = $2", supplier_id, sku)
                        if existing:
                            product_id = existing['id']
                            await conn.execute('UPDATE products SET product_name=$1, description=$2, brand=$3, category=$4, base_price=$5, last_synced=$6, updated_at=$6 WHERE id=$7',
                                p.get('product_name',''), p.get('description',''), p.get('brand',''), p.get('category',''), float(p.get('price',0) or 0), utc_now(), product_id)
                        else:
                            await conn.execute('INSERT INTO products (id, supplier_id, supplier_sku, product_name, description, brand, category, base_price, last_synced, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9,$9)',
                                product_id, supplier_id, sku, p.get('product_name',''), p.get('description',''), p.get('brand',''), p.get('category',''), float(p.get('price',0) or 0), utc_now())
                        for v in p.get('variants', []):
                            existing_var = await conn.fetchrow("SELECT id FROM product_variants WHERE product_id=$1 AND variant_sku=$2", product_id, v.get('variant_sku',''))
                            if existing_var:
                                await conn.execute('UPDATE product_variants SET color=$1, size=$2, price=$3, updated_at=$4 WHERE id=$5',
                                    v.get('color',''), v.get('size',''), float(v.get('price',0) or 0), utc_now(), existing_var['id'])
                            else:
                                await conn.execute('INSERT INTO product_variants (id, product_id, variant_sku, color, size, price, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$7)',
                                    new_id(), product_id, v.get('variant_sku',''), v.get('color',''), v.get('size',''), float(v.get('price',0) or 0), utc_now())
            except Exception as e:
                logger.error(f"Error syncing product {sku}: {e}")
            processed += 1
            if processed % 10 == 0:
                await update_sync_log(log_id, "running", f"Processing... {processed}/{total}", int(processed/total*100), total, processed)
        async with deps.pool.acquire() as conn:
            await conn.execute("UPDATE suppliers SET last_sync = $1 WHERE id = $2", utc_now(), supplier_id)
        await update_sync_log(log_id, "completed", f"Synced {processed} products", 100, total, processed)
    except Exception as e:
        logger.error(f"Sync error: {e}")
        await update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_inventory_task(supplier_id: str, log_id: str):
    task_id = f"inventory_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    try:
        async with deps.pool.acquire() as conn:
            supplier_row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier_row: await update_sync_log(log_id, "failed", "Supplier not found"); return
            supplier = row_to_dict(supplier_row)
            product_rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
            products = [row_to_dict(p) for p in product_rows]
        connector = PromoStandardsConnector(supplier)
        total = len(products); processed = 0; updated_count = 0
        await update_sync_log(log_id, "running", f"Syncing inventory for {total} products", 0, total, 0)
        for product in products:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await update_sync_log(log_id, "stopped", f"Stopped. Updated {updated_count} variants", int(processed/total*100), total, processed); return
            try:
                result = connector.get_inventory(product['supplier_sku'])
                if result.get('success') and result.get('inventory'):
                    async with deps.pool.acquire() as conn:
                        for inv in result['inventory']:
                            r = await conn.execute('UPDATE product_variants SET inventory=$1, warehouse_inventory=$2, updated_at=$3 WHERE product_id=$4 AND variant_sku=$5',
                                inv.get('quantity_available',0), json.dumps(inv.get('warehouses',[])), utc_now(), product['id'], inv.get('part_id',''))
                            if r != "UPDATE 0": updated_count += 1
            except Exception as e:
                logger.error(f"Inventory sync error for {product['supplier_sku']}: {e}")
            processed += 1
            if processed % 20 == 0:
                await update_sync_log(log_id, "running", f"Processing... {processed}/{total}", int(processed/total*100), total, processed)
        await update_sync_log(log_id, "completed", f"Updated {updated_count} variants", 100, total, processed)
    except Exception as e:
        logger.error(f"Inventory sync error: {e}"); await update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_pricing_task(supplier_id: str, log_id: str):
    task_id = f"pricing_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    try:
        async with deps.pool.acquire() as conn:
            supplier_row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier_row: await update_sync_log(log_id, "failed", "Supplier not found"); return
            supplier = row_to_dict(supplier_row)
            product_rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
            products = [row_to_dict(p) for p in product_rows]
        connector = PromoStandardsConnector(supplier)
        total = len(products); processed = 0; updated_count = 0
        await update_sync_log(log_id, "running", f"Syncing pricing for {total} products", 0, total, 0)
        for product in products:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await update_sync_log(log_id, "stopped", f"Stopped. Updated {updated_count} variants", int(processed/total*100), total, processed); return
            try:
                result = connector.get_pricing(product['supplier_sku'])
                if result.get('success') and result.get('pricing'):
                    all_prices = []
                    async with deps.pool.acquire() as conn:
                        for pi in result['pricing']:
                            prices = pi.get('prices', []); price = 0.0
                            if prices:
                                sp = sorted(prices, key=lambda x: x.get('min_quantity',0))
                                price = float(sp[0].get('price',0) or 0)
                                if price > 0: all_prices.append(price)
                            r = await conn.execute('UPDATE product_variants SET price=$1, updated_at=$2 WHERE product_id=$3 AND variant_sku=$4',
                                price, utc_now(), product['id'], pi.get('part_id',''))
                            if r != "UPDATE 0": updated_count += 1
                        if all_prices:
                            await conn.execute('UPDATE products SET base_price=$1, updated_at=$2 WHERE id=$3', min(all_prices), utc_now(), product['id'])
            except Exception as e:
                logger.error(f"Pricing sync error for {product['supplier_sku']}: {e}")
            processed += 1
            if processed % 20 == 0:
                await update_sync_log(log_id, "running", f"Processing... {processed}/{total}", int(processed/total*100), total, processed)
        await update_sync_log(log_id, "completed", f"Updated {updated_count} variants", 100, total, processed)
    except Exception as e:
        logger.error(f"Pricing sync error: {e}"); await update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_media_task(supplier_id: str, log_id: str):
    task_id = f"media_{supplier_id}"
    running_syncs[task_id] = {"status": "running", "should_stop": False}
    try:
        async with deps.pool.acquire() as conn:
            supplier_row = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier_row: await update_sync_log(log_id, "failed", "Supplier not found"); return
            supplier = row_to_dict(supplier_row)
            product_rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id = $1", supplier_id)
            products = [row_to_dict(p) for p in product_rows]
        connector = PromoStandardsConnector(supplier)
        total = len(products); processed = 0; added_count = 0
        await update_sync_log(log_id, "running", f"Syncing media for {total} products", 0, total, 0)
        for product in products:
            if running_syncs.get(task_id, {}).get('should_stop'):
                await update_sync_log(log_id, "stopped", f"Stopped. Added {added_count} media items", int(processed/total*100), total, processed); return
            try:
                result = connector.get_media(product['supplier_sku'])
                if result.get('success') and result.get('media'):
                    async with deps.pool.acquire() as conn:
                        for mi in result['media']:
                            url = mi.get('url', '')
                            existing = await conn.fetchrow("SELECT id FROM product_media WHERE product_id=$1 AND url=$2", product['id'], url)
                            if not existing and url:
                                await conn.execute('INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)',
                                    new_id(), product['id'], mi.get('type','image'), url, mi.get('description',''), mi.get('is_primary',False), utc_now())
                                added_count += 1
            except Exception as e:
                logger.error(f"Media sync error for {product['supplier_sku']}: {e}")
            processed += 1
            if processed % 20 == 0:
                await update_sync_log(log_id, "running", f"Processing... {processed}/{total}", int(processed/total*100), total, processed)
        await update_sync_log(log_id, "completed", f"Added {added_count} media items", 100, total, processed)
    except Exception as e:
        logger.error(f"Media sync error: {e}"); await update_sync_log(log_id, "failed", f"Error: {str(e)}")
    finally:
        running_syncs.pop(task_id, None)


async def sync_bulk_data_task(supplier_id: str, log_id: str):
    task_id = f"bulkdata_{supplier_id}"
    running_syncs[task_id] = {"should_stop": False}
    try:
        async with deps.pool.acquire() as conn:
            supplier = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier: await update_sync_log(log_id, 'failed', 'Supplier not found'); return
            supplier = row_to_dict(supplier)
            await update_sync_log(log_id, 'running', 'Connecting to BulkData API...', progress=5)
            connector = PromoStandardsConnector(supplier)
            if 'bulk_data' not in connector.services and supplier.get('bulk_data_url'):
                connector.services['bulk_data'] = supplier['bulk_data_url']
            await update_sync_log(log_id, 'running', 'Calling BulkData API (this may take a while)...', progress=10)
            result = connector.get_bulk_data()
            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                if result.get('rate_limited'):
                    await update_sync_log(log_id, 'failed', f"BulkData rate limited: {error_msg}. Try again tomorrow.")
                else:
                    await update_sync_log(log_id, 'failed', f"BulkData API error: {error_msg}")
                return
            products_data = result.get('products', [])
            total_products = len(products_data)
            if total_products == 0:
                await update_sync_log(log_id, 'completed', 'No products returned from BulkData API', total=0, processed=0); return
            await update_sync_log(log_id, 'running', f'Processing {total_products} products from BulkData...', progress=15, total=total_products)
            products_by_style = {}
            for p in products_data:
                style = p.get('style', '')
                if not style: continue
                if style not in products_by_style:
                    products_by_style[style] = {'product_name': p.get('product_name',''), 'description': p.get('description',''), 'brand': p.get('brand',''), 'image_url': p.get('image_url',''), 'variants': []}
                if p.get('image_url') and not products_by_style[style]['image_url']:
                    products_by_style[style]['image_url'] = p.get('image_url')
                products_by_style[style]['variants'].append({'variant_sku': p.get('product_id',''), 'color': p.get('color',''), 'size': p.get('size',''), 'price': p.get('price',0), 'inventory': p.get('quantity',0)})
            logger.info(f"BulkData: {len(products_by_style)} unique products from {total_products} rows")
            processed = 0; images_downloaded = 0; images_failed = 0
            for style, pd in products_by_style.items():
                if running_syncs.get(task_id, {}).get("should_stop"):
                    await update_sync_log(log_id, 'stopped', f'Sync stopped by user. Processed {processed} products.'); break
                try:
                    product_id = new_id()
                    product_name = pd['product_name'] or f"Style {style}"
                    existing = await conn.fetchrow("SELECT id FROM products WHERE supplier_id=$1 AND supplier_sku=$2", supplier_id, style)
                    if existing:
                        product_id = existing['id']
                        await conn.execute('UPDATE products SET product_name=$1, description=$2, brand=$3, base_price=$4, updated_at=NOW() WHERE id=$5',
                            product_name, pd['description'], pd['brand'], min([v['price'] for v in pd['variants']] or [0]), product_id)
                    else:
                        await conn.execute('INSERT INTO products (id, supplier_id, supplier_sku, product_name, description, brand, base_price, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW(),NOW())',
                            product_id, supplier_id, style, product_name, pd['description'], pd['brand'], min([v['price'] for v in pd['variants']] or [0]))
                    for v in pd['variants']:
                        existing_var = await conn.fetchrow("SELECT id FROM product_variants WHERE product_id=$1 AND variant_sku=$2", product_id, v['variant_sku'])
                        if existing_var:
                            await conn.execute('UPDATE product_variants SET color=$1, size=$2, price=$3, inventory=$4, updated_at=NOW() WHERE id=$5',
                                v['color'], v['size'], v['price'], v['inventory'], existing_var['id'])
                        else:
                            await conn.execute('INSERT INTO product_variants (id, product_id, variant_sku, color, size, price, inventory, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW(),NOW())',
                                new_id(), product_id, v['variant_sku'], v['color'], v['size'], v['price'], v['inventory'])
                    image_url = pd.get('image_url', '')
                    if image_url:
                        existing_media = await conn.fetchval("SELECT COUNT(*) FROM product_media WHERE product_id=$1", product_id)
                        if existing_media == 0:
                            img_result = connector.download_image(image_url)
                            if img_result.get('success'):
                                await conn.execute('INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, image_base64, created_at) VALUES ($1,$2,\'image\',$3,$4,TRUE,$5,NOW()) ON CONFLICT DO NOTHING',
                                    new_id(), product_id, image_url, f"BulkData image for {style}", img_result.get('image_data',''))
                                images_downloaded += 1
                            else:
                                await conn.execute('INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at) VALUES ($1,$2,\'image\',$3,$4,TRUE,NOW()) ON CONFLICT DO NOTHING',
                                    new_id(), product_id, image_url, f"BulkData image for {style} (download failed)")
                                images_failed += 1
                    processed += 1
                    if processed % 10 == 0:
                        progress = 15 + int((processed / len(products_by_style)) * 80)
                        await update_sync_log(log_id, 'running', f'Processed {processed}/{len(products_by_style)} products, {images_downloaded} images downloaded',
                            progress=progress, total=len(products_by_style), processed=processed)
                except Exception as e:
                    logger.error(f"Error processing product {style}: {e}")
            await conn.execute("UPDATE suppliers SET last_sync=$1 WHERE id=$2", utc_now(), supplier_id)
            message = f"BulkData sync complete: {processed} products, {images_downloaded} images downloaded"
            if images_failed > 0: message += f", {images_failed} image downloads failed"
            await update_sync_log(log_id, 'running', message + ". Enriching categories...", progress=96, total=len(products_by_style), processed=processed)
            # Category enrichment
            categories_updated = 0; categories_failed = 0
            rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id=$1 AND (category IS NULL OR category='')", supplier_id)
            if rows:
                for prod_id, sku in [(r['id'], r['supplier_sku']) for r in rows]:
                    if running_syncs.get(task_id, {}).get("should_stop"): break
                    try:
                        prod_detail = connector.get_product(sku)
                        if prod_detail.get('success') is not False:
                            cat = prod_detail.get('category', '')
                            if cat:
                                await conn.execute("UPDATE products SET category=$1, updated_at=NOW() WHERE id=$2", cat, prod_id)
                                categories_updated += 1
                    except Exception as e:
                        categories_failed += 1
                message += f", {categories_updated} categories enriched"
                if categories_failed > 0: message += f" ({categories_failed} failed)"
            await update_sync_log(log_id, 'completed', message, progress=100, total=len(products_by_style), processed=processed)
            await auto_push_to_odoo_if_enabled(supplier_id)
    except Exception as e:
        logger.error(f"BulkData sync task error: {e}"); await update_sync_log(log_id, 'failed', f'Error: {str(e)}')
    finally:
        running_syncs.pop(task_id, None)


async def enrich_categories_task(supplier_id: str, log_id: str):
    task_id = f"enrich_{supplier_id}"
    running_syncs[task_id] = {"should_stop": False}
    try:
        async with deps.pool.acquire() as conn:
            supplier = await conn.fetchrow("SELECT * FROM suppliers WHERE id = $1", supplier_id)
            if not supplier: await update_sync_log(log_id, 'failed', 'Supplier not found'); return
            supplier = row_to_dict(supplier)
            connector = PromoStandardsConnector(supplier)
            rows = await conn.fetch("SELECT id, supplier_sku FROM products WHERE supplier_id=$1 AND (category IS NULL OR category='')", supplier_id)
            if not rows: await update_sync_log(log_id, 'completed', 'No products need category enrichment', progress=100); return
            total = len(rows); updated = 0; failed = 0
            for i, r in enumerate(rows):
                if running_syncs.get(task_id, {}).get("should_stop"):
                    await update_sync_log(log_id, 'stopped', f'Stopped. Enriched {updated}/{total} categories.'); break
                try:
                    prod_detail = connector.get_product(r['supplier_sku'])
                    cat = prod_detail.get('category', '')
                    if cat:
                        await conn.execute("UPDATE products SET category=$1, updated_at=NOW() WHERE id=$2", cat, r['id']); updated += 1
                    else: failed += 1
                except Exception as e:
                    failed += 1; logger.warning(f"Category enrichment failed for {r['supplier_sku']}: {e}")
                if (i+1) % 10 == 0:
                    await update_sync_log(log_id, 'running', f'Enriched {updated}/{total} categories ({failed} failed)', progress=int(((i+1)/total)*100), total=total, processed=updated)
            msg = f"Category enrichment complete: {updated} updated, {failed} failed out of {total}"
            await update_sync_log(log_id, 'completed', msg, progress=100, total=total, processed=updated)
            logger.info(msg)
    except Exception as e:
        logger.error(f"Category enrichment error: {e}"); await update_sync_log(log_id, 'failed', f'Error: {str(e)}')
    finally:
        running_syncs.pop(task_id, None)


# ==================== INTERNAL HELPERS ====================
async def _sync_product_inventory_internal(product_id: str) -> dict:
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT p.id, p.supplier_sku, s.* FROM products p JOIN suppliers s ON p.supplier_id=s.id WHERE p.id=$1", product_id)
        if not row: return {"success": False, "message": "Product not found"}
        connector = PromoStandardsConnector(row_to_dict(row))
        result = connector.get_inventory(row['supplier_sku'])
        if not result.get('success'): return {"success": False, "message": result.get('error', 'Failed to fetch inventory')}
        updated_count = 0
        for inv in result.get('inventory', []):
            r = await conn.execute('UPDATE product_variants SET inventory=$1, warehouse_inventory=$2, updated_at=$3 WHERE product_id=$4 AND variant_sku=$5',
                inv.get('quantity_available',0), json.dumps(inv.get('warehouses',[])), utc_now(), product_id, inv.get('part_id',''))
            if r != "UPDATE 0": updated_count += 1
        return {"success": True, "message": f"Updated inventory for {updated_count} variants", "variants_updated": updated_count}


async def _sync_product_pricing_internal(product_id: str) -> dict:
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT p.id, p.supplier_sku, s.* FROM products p JOIN suppliers s ON p.supplier_id=s.id WHERE p.id=$1", product_id)
        if not row: return {"success": False, "message": "Product not found"}
        connector = PromoStandardsConnector(row_to_dict(row))
        result = connector.get_pricing(row['supplier_sku'])
        if not result.get('success'): return {"success": False, "message": result.get('error', 'Failed to fetch pricing')}
        updated_count = 0; all_prices = []
        for pi in result.get('pricing', []):
            prices = pi.get('prices', []); price = 0.0
            if prices:
                sp = sorted(prices, key=lambda x: x.get('min_quantity',0))
                price = float(sp[0].get('price',0) or 0)
                if price > 0: all_prices.append(price)
            r = await conn.execute('UPDATE product_variants SET price=$1, updated_at=$2 WHERE product_id=$3 AND variant_sku=$4',
                price, utc_now(), product_id, pi.get('part_id',''))
            if r != "UPDATE 0": updated_count += 1
        if all_prices:
            await conn.execute('UPDATE products SET base_price=$1, updated_at=$2 WHERE id=$3', min(all_prices), utc_now(), product_id)
        return {"success": True, "message": f"Updated pricing for {updated_count} variants", "variants_updated": updated_count}


async def _sync_product_media_internal(product_id: str) -> dict:
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT p.id, p.supplier_sku, s.* FROM products p JOIN suppliers s ON p.supplier_id=s.id WHERE p.id=$1", product_id)
        if not row: return {"success": False, "message": "Product not found"}
        connector = PromoStandardsConnector(row_to_dict(row))
        result = connector.get_media(row['supplier_sku'])
        if not result.get('success'): return {"success": False, "message": result.get('error', 'Failed to fetch media')}
        added_count = 0
        for mi in result.get('media', []):
            url = mi.get('url', '')
            if not url: continue
            existing = await conn.fetchrow("SELECT id FROM product_media WHERE product_id=$1 AND url=$2", product_id, url)
            if not existing:
                await conn.execute('INSERT INTO product_media (id, product_id, media_type, url, description, is_primary, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)',
                    new_id(), product_id, mi.get('type','image'), url, mi.get('description',''), mi.get('is_primary',False), utc_now())
                added_count += 1
        return {"success": True, "message": f"Added {added_count} media items", "media_added": added_count}
