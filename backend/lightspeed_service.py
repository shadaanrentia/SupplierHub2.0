"""
Lightspeed eCom API integration service.
Handles products, categories, variants, images, and inventory sync.
Uses HTTP Basic Auth with api_key:api_secret.

Clusters:
  EU1: https://api.webshopapp.com
  US1: https://api.shoplightspeed.com
"""
import logging
import requests
import base64
import time

logger = logging.getLogger(__name__)

CLUSTERS = {
    "us1": "https://api.shoplightspeed.com",
    "eu1": "https://api.webshopapp.com",
}


class LightspeedService:
    """Lightspeed eCom integration via REST API."""

    def __init__(self, api_key: str = '', api_secret: str = '', cluster: str = 'us1', language: str = 'en'):
        self.api_key = api_key or ''
        self.api_secret = api_secret or ''
        self.cluster = cluster or 'us1'
        self.language = language or 'en'
        self.base_url = CLUSTERS.get(self.cluster, CLUSTERS['us1'])
        self.mock_mode = not all([self.api_key, self.api_secret])
        self._rate_limit_remaining = 300
        self._rate_limit_reset = 0

        if self.mock_mode:
            logger.info("Lightspeed connector: MOCK mode (no credentials)")

    def _url(self, resource: str) -> str:
        return f"{self.base_url}/{self.language}/{resource}.json"

    def _auth(self):
        return (self.api_key, self.api_secret)

    def _handle_rate_limit(self, resp):
        """Track rate limits from response headers."""
        remaining = resp.headers.get('X-RateLimit-Remaining')
        reset = resp.headers.get('X-RateLimit-Reset')
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)
        if reset is not None:
            self._rate_limit_reset = int(reset)
        if self._rate_limit_remaining < 10:
            wait = max(self._rate_limit_reset, 1)
            logger.warning(f"Lightspeed rate limit low ({self._rate_limit_remaining}), sleeping {wait}s")
            time.sleep(wait)

    def _get(self, resource: str, params: dict = None) -> dict:
        resp = requests.get(self._url(resource), auth=self._auth(), params=params, timeout=30)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _post(self, resource: str, data: dict) -> dict:
        resp = requests.post(self._url(resource), auth=self._auth(), json=data, timeout=30)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _put(self, resource: str, data: dict) -> dict:
        resp = requests.put(self._url(resource), auth=self._auth(), json=data, timeout=30)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, resource: str):
        resp = requests.delete(self._url(resource), auth=self._auth(), timeout=30)
        self._handle_rate_limit(resp)
        if resp.status_code != 204:
            resp.raise_for_status()

    # ==================== CONNECTION ====================
    def test_connection(self) -> dict:
        if self.mock_mode:
            return {
                'success': False,
                'connected': False,
                'message': 'Lightspeed not configured. Set API Key, Secret, and Cluster in Settings.',
                'mock_mode': True
            }
        try:
            data = self._get('products/count')
            count = data.get('count', 0)
            return {
                'success': True,
                'connected': True,
                'message': f'Connected to Lightspeed eCom ({self.cluster.upper()}). {count} products in store.',
                'mock_mode': False,
                'product_count': count
            }
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 401:
                msg = 'Authentication failed. Check your API key and secret.'
            elif status == 403:
                msg = 'Access forbidden. Your API key may lack permissions.'
            else:
                msg = f'HTTP error {status}: {str(e)}'
            return {'success': False, 'connected': False, 'message': msg, 'mock_mode': False}
        except Exception as e:
            return {'success': False, 'connected': False, 'message': f'Connection failed: {str(e)}', 'mock_mode': False}

    # ==================== CATEGORIES ====================
    def get_categories(self) -> dict:
        """Fetch all categories from Lightspeed store."""
        if self.mock_mode:
            return {'success': False, 'error': 'Lightspeed not configured', 'categories': []}
        try:
            all_categories = []
            page = 1
            while True:
                data = self._get('categories', params={'limit': 250, 'page': page})
                cats = data.get('categories', [])
                if not cats:
                    break
                all_categories.extend(cats)
                if len(cats) < 250:
                    break
                page += 1

            result = []
            for cat in all_categories:
                parent_id = None
                parent_name = None
                if cat.get('parent') and isinstance(cat['parent'], dict):
                    res = cat['parent'].get('resource', {})
                    parent_id = res.get('id') if res.get('id') else None

                result.append({
                    'lightspeed_category_id': cat['id'],
                    'category_name': cat.get('title', ''),
                    'parent_id': parent_id,
                    'parent_category': parent_name,
                    'depth': cat.get('depth', 1),
                    'url': cat.get('url', ''),
                    'is_visible': cat.get('isVisible', True),
                })

            logger.info(f"Fetched {len(result)} categories from Lightspeed")
            return {'success': True, 'categories': result}

        except Exception as e:
            logger.error(f"Error fetching Lightspeed categories: {e}")
            return {'success': False, 'error': str(e), 'categories': []}

    def create_category(self, title: str, parent_id: int = None) -> dict:
        """Create a category in Lightspeed."""
        if self.mock_mode:
            return {'success': False, 'error': 'Lightspeed not configured'}
        try:
            payload = {
                'category': {
                    'title': title,
                    'fulltitle': title,
                    'isVisible': True,
                    'type': 'category',
                }
            }
            if parent_id:
                payload['category']['parent'] = parent_id

            data = self._post('categories', payload)
            cat = data.get('category', {})
            return {'success': True, 'id': cat.get('id'), 'title': cat.get('title')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ==================== PRODUCTS ====================
    def create_or_update_product(self, product: dict) -> dict:
        """Create or update a product in Lightspeed with variants and images."""
        if self.mock_mode:
            import random
            mock_id = random.randint(1000, 9999)
            logger.info(f"[MOCK] Pushed '{product.get('product_name')}' -> Lightspeed ID mock_{mock_id}")
            return {'success': True, 'lightspeed_id': f'mock_{mock_id}', 'created': True, 'mock_mode': True}

        try:
            sku = product.get('supplier_sku', '')
            cost_price = float(product.get('cost_price', 0) or 0)
            sale_price = float(product.get('base_price', 0) or 0)

            logger.info(f"Syncing product {sku} to Lightspeed: Cost={cost_price}, Sale={sale_price}")

            # Check if product exists by searching variants by SKU
            existing_product_id = self._find_product_by_sku(sku)

            product_data = {
                'product': {
                    'title': product.get('product_name', ''),
                    'fulltitle': product.get('product_name', ''),
                    'description': (product.get('description', '') or '')[:255],
                    'content': product.get('description', '') or '',
                    'visibility': 'visible',
                }
            }

            if existing_product_id:
                # Update existing product
                data = self._put(f'products/{existing_product_id}', product_data)
                ls_product = data.get('product', {})
                ls_id = ls_product.get('id', existing_product_id)
                logger.info(f"Updated product {sku} (Lightspeed ID: {ls_id})")
            else:
                # Create new product
                data = self._post('products', product_data)
                ls_product = data.get('product', {})
                ls_id = ls_product.get('id')
                logger.info(f"Created product {sku} (Lightspeed ID: {ls_id})")

            if not ls_id:
                return {'success': False, 'error': 'Failed to get product ID from Lightspeed'}

            # Sync variants
            variants = product.get('variants', [])
            self._sync_variants(ls_id, sku, variants, cost_price, sale_price)

            # Sync category assignment
            category_id = product.get('category_id')
            if category_id:
                self._assign_category(ls_id, category_id)

            # Sync images
            images = product.get('images', [])
            if images:
                self._sync_images(ls_id, images)

            return {'success': True, 'lightspeed_id': str(ls_id), 'created': not existing_product_id}

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            body = ''
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            logger.error(f"Lightspeed API error {status}: {body}")
            return {'success': False, 'error': f'Lightspeed API error {status}: {body}'}
        except Exception as e:
            logger.error(f"Lightspeed push error: {e}")
            return {'success': False, 'error': str(e)}

    def _find_product_by_sku(self, sku: str):
        """Find a product ID by searching variant SKU."""
        try:
            data = self._get('variants', params={'sku': sku, 'limit': 1})
            variants = data.get('variants', [])
            if variants:
                product_res = variants[0].get('product', {}).get('resource', {})
                return product_res.get('id')
        except Exception:
            pass
        # Also try articleCode
        try:
            data = self._get('variants', params={'article_code': sku, 'limit': 1})
            variants = data.get('variants', [])
            if variants:
                product_res = variants[0].get('product', {}).get('resource', {})
                return product_res.get('id')
        except Exception:
            pass
        return None

    def _sync_variants(self, product_id: int, parent_sku: str, variants: list, cost_price: float, sale_price: float):
        """Sync variants for a product. Sets SKU, price, stock on default or creates new variants."""
        try:
            # Get existing variants for this product
            existing = self._get('variants', params={'product': product_id, 'limit': 250})
            existing_variants = existing.get('variants', [])

            if not variants:
                # No supplier variants — update the default variant with pricing/SKU
                if existing_variants:
                    default_v = existing_variants[0]
                    self._put(f'variants/{default_v["id"]}', {
                        'variant': {
                            'sku': parent_sku,
                            'articleCode': parent_sku,
                            'priceExcl': sale_price,
                            'priceCost': cost_price,
                            'stockTracking': 'indicator',
                        }
                    })
                return

            # Map existing variants by SKU
            existing_by_sku = {}
            for ev in existing_variants:
                if ev.get('sku'):
                    existing_by_sku[ev['sku']] = ev
                if ev.get('articleCode'):
                    existing_by_sku[ev['articleCode']] = ev

            for v in variants:
                v_sku = v.get('variant_sku', '') or v.get('sku', '')
                v_qty = int(v.get('inventory', 0) or v.get('inventory_quantity', 0) or 0)
                v_price = float(v.get('price', 0) or sale_price)
                v_cost = float(v.get('cost_price', 0) or cost_price)
                v_title = f"{v.get('color', '')} {v.get('size', '')}".strip() or 'Default'

                if v_sku in existing_by_sku:
                    # Update existing variant
                    ev = existing_by_sku[v_sku]
                    self._put(f'variants/{ev["id"]}', {
                        'variant': {
                            'priceExcl': v_price,
                            'priceCost': v_cost,
                            'stockLevel': v_qty,
                            'stockTracking': 'indicator',
                            'title': v_title,
                        }
                    })
                else:
                    # Create new variant
                    self._post('variants', {
                        'variant': {
                            'product': product_id,
                            'sku': v_sku,
                            'articleCode': v_sku,
                            'title': v_title,
                            'priceExcl': v_price,
                            'priceCost': v_cost,
                            'stockLevel': v_qty,
                            'stockTracking': 'indicator',
                        }
                    })

        except Exception as e:
            logger.error(f"Error syncing variants for product {product_id}: {e}")

    def _assign_category(self, product_id: int, category_id: int):
        """Assign a product to a category via the categories/products resource."""
        try:
            self._post('categories/products', {
                'categoriesProduct': {
                    'product': product_id,
                    'category': category_id,
                }
            })
        except requests.HTTPError as e:
            # 422 likely means already assigned — ignore
            if e.response is not None and e.response.status_code == 422:
                pass
            else:
                logger.warning(f"Error assigning category {category_id} to product {product_id}: {e}")
        except Exception as e:
            logger.warning(f"Error assigning category: {e}")

    def _sync_images(self, product_id: int, images: list):
        """Sync product images to Lightspeed. Uploads base64-encoded images."""
        try:
            synced = 0
            for i, img in enumerate(images[:5]):
                img_base64 = img.get('image_base64', '')
                img_url = img.get('url', '')
                img_path = img.get('local_path', '')

                attachment = None
                filename = f'product_{product_id}_img_{i+1}.jpg'

                if img_base64:
                    attachment = img_base64
                elif img_path:
                    import os
                    if os.path.exists(img_path):
                        with open(img_path, 'rb') as f:
                            attachment = base64.b64encode(f.read()).decode('utf-8')
                elif img_url:
                    try:
                        resp = requests.get(img_url, timeout=20, headers={
                            'User-Agent': 'Mozilla/5.0'
                        })
                        if resp.status_code == 200 and len(resp.content) > 1000:
                            content_type = resp.headers.get('content-type', '').lower()
                            if 'image' in content_type or resp.content[:4] in (b'\xff\xd8\xff\xe0', b'\x89PNG', b'GIF8'):
                                attachment = base64.b64encode(resp.content).decode('utf-8')
                                ext = 'jpg'
                                if b'\x89PNG' in resp.content[:8]:
                                    ext = 'png'
                                filename = f'product_{product_id}_img_{i+1}.{ext}'
                    except Exception as e:
                        logger.warning(f"Failed to download image from {img_url[:80]}: {e}")

                if attachment:
                    try:
                        self._post(f'products/{product_id}/images', {
                            'productImage': {
                                'attachment': attachment,
                                'filename': filename,
                            }
                        })
                        synced += 1
                    except Exception as e:
                        logger.warning(f"Failed to upload image to Lightspeed: {e}")

            if synced > 0:
                logger.info(f"Synced {synced} images for Lightspeed product {product_id}")

        except Exception as e:
            logger.error(f"Error syncing images for product {product_id}: {e}")

    # ==================== INVENTORY (standalone) ====================
    def update_variant_stock(self, variant_id: int, stock_level: int):
        """Update stock level for a specific variant."""
        if self.mock_mode:
            return {'success': False, 'error': 'Not configured'}
        try:
            self._put(f'variants/{variant_id}', {
                'variant': {'stockLevel': stock_level}
            })
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def bulk_update_variants(self, updates: list) -> dict:
        """Bulk update variants (max 100 per call). Each item: {id, stockLevel, priceExcl, priceCost}."""
        if self.mock_mode:
            return {'success': False, 'error': 'Not configured'}
        try:
            data = self._put('variants/bulk', {'variant': updates})
            return {'success': True, 'updated': len(data.get('variants', [])), 'errors': data.get('errors', [])}
        except Exception as e:
            return {'success': False, 'error': str(e)}
