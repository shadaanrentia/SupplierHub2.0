"""Preprocessing routes: products validation, pricing, Odoo sync, preview."""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
import deps
from deps import row_to_dict, new_id, utc_now, get_current_user, calculate_sale_price

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/preprocessing/products")
async def get_preprocessing_products(page: int = 1, limit: int = 50, status: str = None, user: dict = Depends(get_current_user)):
    offset = (page - 1) * limit
    async with deps.pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        where_clause = f"WHERE p.preprocessing_status = '{status}'" if status else ""
        query = f'''
            SELECT p.*, s.supplier_name, cm.odoo_category_id as mapped_odoo_category_id,
                cm.lightspeed_category_id as mapped_lightspeed_category_id,
                oc.category_name as odoo_category_name,
                (SELECT COUNT(*) FROM product_variants pv WHERE pv.product_id = p.id) as variants_count,
                (SELECT COUNT(*) FROM product_media pm WHERE pm.product_id = p.id) as images_count,
                pss.sync_status, pss.sale_price as calculated_sale_price, pss.validation_errors, pss.last_sync_date
            FROM products p LEFT JOIN suppliers s ON p.supplier_id = s.id
            LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
            LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id
            LEFT JOIN product_sync_status pss ON p.id = pss.product_id
            {where_clause} ORDER BY p.updated_at DESC LIMIT $1 OFFSET $2
        '''
        rows = await conn.fetch(query, limit, offset)
        count_query = f"SELECT COUNT(*) FROM products p {where_clause}"
        total = await conn.fetchval(count_query)
        products = []
        for row in rows:
            product = row_to_dict(row)
            cost_price = float(product.get('base_price') or 0)
            if not product.get('calculated_sale_price'):
                product['calculated_sale_price'] = calculate_sale_price(cost_price, markup)
            product['cost_price'] = cost_price
            product['markup_percentage'] = markup
            errors = []
            has_category_mapping = product.get('mapped_odoo_category_id') or product.get('mapped_lightspeed_category_id')
            if not has_category_mapping: errors.append("Missing category mapping")
            if not product.get('images_count') or product['images_count'] == 0: errors.append("No images")
            if cost_price <= 0: errors.append("Invalid price")
            product['validation_errors'] = errors
            product['is_valid'] = len(errors) == 0
            product['status'] = 'ready' if len(errors) == 0 else 'invalid'
            products.append(product)
        return {"products": products, "total": total, "page": page, "limit": limit, "markup_percentage": markup}


@router.get("/preprocessing/summary")
async def get_preprocessing_summary(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        total_products = await conn.fetchval("SELECT COUNT(*) FROM products")
        total_variants = await conn.fetchval("SELECT COUNT(*) FROM product_variants")
        mapped_count = await conn.fetchval('SELECT COUNT(DISTINCT p.id) FROM products p INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name WHERE cm.odoo_category_id IS NOT NULL OR cm.lightspeed_category_id IS NOT NULL')
        unmapped_count = await conn.fetchval('SELECT COUNT(*) FROM products p LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name WHERE (cm.odoo_category_id IS NULL AND cm.lightspeed_category_id IS NULL) OR p.category IS NULL OR p.category = \'\'')
        with_images = await conn.fetchval('SELECT COUNT(DISTINCT product_id) FROM product_media')
        with_price = await conn.fetchval("SELECT COUNT(*) FROM products WHERE base_price > 0")
        synced = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'synced'")
        pending = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'pending' OR odoo_sync_status IS NULL")
        failed = await conn.fetchval("SELECT COUNT(*) FROM products WHERE odoo_sync_status = 'failed'")
        ready_for_sync = await conn.fetchval("SELECT COUNT(DISTINCT p.id) FROM products p INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name WHERE (cm.odoo_category_id IS NOT NULL OR cm.lightspeed_category_id IS NOT NULL) AND p.base_price > 0 AND p.odoo_sync_status != 'synced'")
        return {
            "total_products": total_products, "total_variants": total_variants,
            "category_mapping": {"mapped": mapped_count, "unmapped": unmapped_count},
            "images": {"with_images": with_images, "without_images": total_products - with_images},
            "pricing": {"with_price": with_price, "without_price": total_products - with_price},
            "sync_status": {"synced": synced, "pending": pending, "failed": failed, "ready": ready_for_sync}
        }


@router.post("/preprocessing/recalculate-prices")
async def recalculate_all_prices(user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        products = await conn.fetch("SELECT id, base_price FROM products WHERE base_price > 0")
        updated = 0
        for p in products:
            cost = float(p['base_price']); sale_price = calculate_sale_price(cost, markup)
            await conn.execute('INSERT INTO product_sync_status (id, product_id, cost_price, sale_price, updated_at) VALUES ($1,$2,$3,$4,NOW()) ON CONFLICT (product_id) DO UPDATE SET cost_price=EXCLUDED.cost_price, sale_price=EXCLUDED.sale_price, updated_at=NOW()',
                new_id(), p['id'], cost, sale_price)
            updated += 1
        return {"success": True, "updated": updated, "markup_percentage": markup}


@router.post("/preprocessing/validate-products")
async def validate_products_for_sync(data: dict = None, user: dict = Depends(get_current_user)):
    product_ids = data.get('product_ids', []) if data else []
    async with deps.pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        products = await conn.fetch("SELECT * FROM products WHERE id = ANY($1)", product_ids) if product_ids else await conn.fetch("SELECT * FROM products")
        validated = 0; invalid = 0
        for p in products:
            product = row_to_dict(p); errors = []
            mapping = await conn.fetchrow('SELECT cm.odoo_category_id, cm.lightspeed_category_id FROM category_mapping cm WHERE cm.supplier_category_name = $1 AND (cm.odoo_category_id IS NOT NULL OR cm.lightspeed_category_id IS NOT NULL)', product.get('category', ''))
            if not mapping: errors.append("Missing category mapping")
            cost = float(product.get('base_price') or 0)
            if cost <= 0: errors.append("Invalid or missing price")
            images_count = await conn.fetchval("SELECT COUNT(*) FROM product_media WHERE product_id = $1", product['id'])
            if images_count == 0: errors.append("No product images")
            sale_price = calculate_sale_price(cost, markup) if cost > 0 else 0
            status = 'ready' if len(errors) == 0 else 'invalid'
            await conn.execute('INSERT INTO product_sync_status (id, product_id, supplier_id, cost_price, sale_price, mapped_category_id, images_count, validation_errors, sync_status, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW()) ON CONFLICT (product_id) DO UPDATE SET cost_price=EXCLUDED.cost_price, sale_price=EXCLUDED.sale_price, mapped_category_id=EXCLUDED.mapped_category_id, images_count=EXCLUDED.images_count, validation_errors=EXCLUDED.validation_errors, sync_status=EXCLUDED.sync_status, updated_at=NOW()',
                new_id(), product['id'], product.get('supplier_id'), cost, sale_price, mapping['odoo_category_id'] if mapping else None, images_count, json.dumps(errors), status)
            if len(errors) == 0: validated += 1
            else: invalid += 1
        return {"success": True, "total": len(products), "validated": validated, "invalid": invalid}


@router.post("/preprocessing/sync-to-odoo")
async def sync_preprocessed_to_odoo(data: dict = None, user: dict = Depends(get_current_user)):
    from odoo_service import OdooService
    product_ids = data.get('product_ids', []) if data else []
    sync_all = data.get('sync_all', False) if data else False
    async with deps.pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row: raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)
        odoo = OdooService(settings.get('odoo_url'), settings.get('odoo_db'), settings.get('odoo_username'), settings.get('odoo_api_key'))
        conn_test = odoo.test_connection()
        if not conn_test.get('connected'): raise HTTPException(400, f"Odoo connection failed: {conn_test.get('message')}")
        if sync_all:
            products = await conn.fetch('SELECT p.*, cm.odoo_category_id, pss.sale_price FROM products p INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name LEFT JOIN product_sync_status pss ON p.id = pss.product_id WHERE cm.odoo_category_id IS NOT NULL AND p.base_price > 0 AND (p.odoo_sync_status != \'synced\' OR p.odoo_sync_status IS NULL)')
        elif product_ids:
            products = await conn.fetch('SELECT p.*, cm.odoo_category_id, pss.sale_price FROM products p LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name LEFT JOIN product_sync_status pss ON p.id = pss.product_id WHERE p.id = ANY($1)', product_ids)
        else:
            return {"success": False, "error": "No products specified"}
        synced = 0; failed = 0; errors = []
        for p in products:
            product = row_to_dict(p)
            try:
                cost = float(product.get('base_price') or 0)
                sale_price = product.get('sale_price') or calculate_sale_price(cost, markup)
                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])
                odoo_data = {
                    'product_name': product.get('product_name'), 'supplier_sku': product.get('supplier_sku'),
                    'description': product.get('description'), 'base_price': sale_price, 'cost_price': cost,
                    'category_id': product.get('odoo_category_id'), 'default_category': 'SanMar Apparel',
                    'variants': [row_to_dict(v) for v in variants], 'images': [row_to_dict(i) for i in images],
                }
                result = odoo.create_or_update_product(odoo_data)
                if result.get('success'):
                    await conn.execute('UPDATE products SET odoo_sync_status=\'synced\', odoo_product_id=$1, calculated_sale_price=$2, updated_at=NOW() WHERE id=$3',
                        str(result.get('odoo_id','')), sale_price, product['id'])
                    await conn.execute('UPDATE product_sync_status SET sync_status=\'synced\', odoo_product_id=$1, last_sync_date=NOW(), updated_at=NOW() WHERE product_id=$2',
                        str(result.get('odoo_id','')), product['id'])
                    synced += 1
                else:
                    await conn.execute('UPDATE products SET odoo_sync_status=\'failed\', updated_at=NOW() WHERE id=$1', product['id'])
                    failed += 1; errors.append({'product_id': product['id'], 'sku': product.get('supplier_sku'), 'error': result.get('error')})
            except Exception as e:
                logger.error(f"Error syncing {product.get('supplier_sku')}: {e}")
                failed += 1; errors.append({'product_id': product['id'], 'sku': product.get('supplier_sku'), 'error': str(e)})
        return {"success": True, "total": len(products), "synced": synced, "failed": failed, "errors": errors[:10]}


@router.post("/preprocessing/sync-to-lightspeed")
async def sync_preprocessed_to_lightspeed(data: dict = None, user: dict = Depends(get_current_user)):
    from lightspeed_service import LightspeedService
    product_ids = data.get('product_ids', []) if data else []
    sync_all = data.get('sync_all', False) if data else False
    async with deps.pool.acquire() as conn:
        settings_row = await conn.fetchrow("SELECT * FROM settings WHERE id = 'system_settings'")
        if not settings_row: raise HTTPException(400, "Settings not configured")
        settings = row_to_dict(settings_row)
        markup = float(settings.get('markup_percentage') or 40)

        ls = LightspeedService(
            domain_prefix=settings.get('lightspeed_store_id', ''),
            personal_token=settings.get('lightspeed_secret_token', ''),
            access_token=settings.get('lightspeed_access_token', ''),
            client_id=settings.get('lightspeed_client_id', ''),
            client_secret=settings.get('lightspeed_client_secret', ''),
            refresh_token=settings.get('lightspeed_refresh_token', ''),
            token_expires_at=settings.get('lightspeed_token_expires_at'),
        )
        conn_test = ls.test_connection()
        if not conn_test.get('connected'): raise HTTPException(400, f"Lightspeed connection failed: {conn_test.get('message')}")

        if sync_all:
            products = await conn.fetch('''
                SELECT p.*, cm.lightspeed_category_id, s.supplier_name, pss.sale_price
                FROM products p
                INNER JOIN category_mapping cm ON p.category = cm.supplier_category_name
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                LEFT JOIN product_sync_status pss ON p.id = pss.product_id
                WHERE cm.lightspeed_category_id IS NOT NULL AND p.base_price > 0
                AND (p.lightspeed_sync_status != 'synced' OR p.lightspeed_sync_status IS NULL)
            ''')
        elif product_ids:
            products = await conn.fetch('''
                SELECT p.*, cm.lightspeed_category_id, s.supplier_name, pss.sale_price
                FROM products p
                LEFT JOIN category_mapping cm ON p.category = cm.supplier_category_name
                LEFT JOIN suppliers s ON p.supplier_id = s.id
                LEFT JOIN product_sync_status pss ON p.id = pss.product_id
                WHERE p.id = ANY($1)
            ''', product_ids)
        else:
            return {"success": False, "error": "No products specified"}

        synced = 0; failed = 0; errors = []
        for p in products:
            product = row_to_dict(p)
            try:
                cost = float(product.get('base_price') or 0)
                sale_price = product.get('sale_price') or calculate_sale_price(cost, markup)
                supplier_name = product.get('supplier_name', '')

                variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1", product['id'])
                images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product['id'])

                ls_data = {
                    'product_name': product.get('product_name'),
                    'supplier_sku': product.get('supplier_sku'),
                    'description': product.get('description'),
                    'product_id': product['id'],
                    # Brand
                    'brand_name': product.get('brand'),

                    # Pricing
                    'base_price': float(sale_price),
                    'cost_price': cost,
                    'calculated_sale_price': float(sale_price),
                    'sale_price': float(sale_price),
                    'retail_price': float(sale_price),

                    # ONLY use manually mapped Lightspeed category
                    'category_id': product.get('lightspeed_category_id'),

                    # Supplier from SupplierHub
                    'supplier_name': supplier_name,

                    # Variants + media
                    'variants': [row_to_dict(v) for v in variants],
                    'images': [row_to_dict(i) for i in images],
                }
                result = await ls.create_or_update_product(ls_data)
                if result.get('success'):
                    await conn.execute(
                        "UPDATE products SET lightspeed_sync_status='synced', lightspeed_product_id=$1, updated_at=NOW() WHERE id=$2",
                        str(result.get('lightspeed_id', '')), product['id'])
                    await conn.execute("""
                        INSERT INTO product_sync_status (id, product_id, sync_status, last_sync_date, updated_at)
                        VALUES ($1, $2, 'synced', NOW(), NOW())
                        ON CONFLICT (product_id) DO UPDATE SET sync_status='synced', last_sync_date=NOW(), updated_at=NOW()
                    """, new_id(), product['id'])
                    synced += 1
                else:
                    await conn.execute("UPDATE products SET lightspeed_sync_status='failed', updated_at=NOW() WHERE id=$1", product['id'])
                    failed += 1; errors.append({'product_id': product['id'], 'sku': product.get('supplier_sku'), 'error': result.get('error')})
            except Exception as e:
                logger.error(f"Error syncing {product.get('supplier_sku')} to Lightspeed: {e}")
                failed += 1; errors.append({'product_id': product['id'], 'sku': product.get('supplier_sku'), 'error': str(e)})

        # Persist refreshed token if applicable
        if ls.token_was_refreshed:
            await conn.execute("""
                UPDATE settings SET lightspeed_access_token = $1, lightspeed_token_expires_at = $2, updated_at = NOW()
                WHERE id = 'system_settings'
            """, ls.access_token, ls.token_expires_at)

    return {"success": True, "total": len(products), "synced": synced, "failed": failed, "errors": errors[:10]}



@router.get("/preprocessing/product/{product_id}/preview")
async def preview_product_for_odoo(product_id: str, user: dict = Depends(get_current_user)):
    async with deps.pool.acquire() as conn:
        settings = await conn.fetchrow("SELECT markup_percentage FROM settings WHERE id = 'system_settings'")
        markup = float(settings['markup_percentage']) if settings else 40.0
        product = await conn.fetchrow("SELECT * FROM products WHERE id = $1", product_id)
        if not product: raise HTTPException(404, "Product not found")
        product = row_to_dict(product)
        mapping = await conn.fetchrow('SELECT cm.*, oc.category_name as odoo_category_name FROM category_mapping cm LEFT JOIN odoo_categories oc ON cm.odoo_category_id = oc.odoo_category_id WHERE cm.supplier_category_name = $1', product.get('category',''))
        variants = await conn.fetch("SELECT * FROM product_variants WHERE product_id = $1 ORDER BY color, size", product_id)
        images = await conn.fetch("SELECT * FROM product_media WHERE product_id = $1", product_id)
        cost_price = float(product.get('base_price') or 0); sale_price = calculate_sale_price(cost_price, markup)
        preview = {
            "product_template": {
                "name": product.get('product_name'), "default_code": product.get('supplier_sku'),
                "description": product.get('description'), "list_price": sale_price, "standard_price": cost_price,
                "categ_id": mapping['odoo_category_id'] if mapping else None,
                "category_name": mapping['odoo_category_name'] if mapping else "Not Mapped",
                "type": "product", "sale_ok": True, "purchase_ok": True,
            },
            "attributes": {
                "colors": list(set(v['color'] for v in variants if v.get('color'))),
                "sizes": list(set(v['size'] for v in variants if v.get('size'))),
            },
            "variants": [{"sku": v['variant_sku'], "color": v.get('color'), "size": v.get('size'), "price": float(v.get('price') or sale_price), "inventory": v.get('inventory',0)} for v in variants],
            "images": [{"url": img['url'], "type": img.get('media_type','image'), "is_primary": img.get('is_primary',False)} for img in images],
            "validation": {"is_valid": bool(mapping and cost_price > 0), "errors": []}
        }
        if not mapping: preview["validation"]["errors"].append("Category not mapped")
        if cost_price <= 0: preview["validation"]["errors"].append("Invalid price")
        if len(images) == 0: preview["validation"]["errors"].append("No images")
        return preview
