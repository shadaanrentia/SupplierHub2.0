"""
Lightspeed eSeries (Ecwid) API integration service.
Uses the Ecwid REST API v3 with Store ID + Secret Token (Bearer auth).
Base URL: https://app.ecwid.com/api/v3/{storeId}/
Docs: https://api-docs.ecwid.com/reference
"""
import logging
import requests
import base64
import time
import os

logger = logging.getLogger(__name__)

ECWID_API_BASE = "https://app.ecwid.com/api/v3"


class LightspeedService:
    """Lightspeed eSeries (Ecwid) integration via REST API v3."""

    def __init__(self, store_id: str = '', secret_token: str = ''):
        self.store_id = (store_id or '').strip()
        self.secret_token = (secret_token or '').strip()
        self.mock_mode = not all([self.store_id, self.secret_token])
        self._last_request_time = 0

        if self.mock_mode:
            logger.info("Ecwid connector: MOCK mode (no credentials)")

    def _url(self, resource: str) -> str:
        return f"{ECWID_API_BASE}/{self.store_id}/{resource}"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _throttle(self):
        """Simple throttle to stay within Ecwid rate limits (~600 req/min)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.12:
            time.sleep(0.12 - elapsed)
        self._last_request_time = time.time()

    def _get(self, resource: str, params: dict = None) -> dict:
        self._throttle()
        resp = requests.get(self._url(resource), headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, resource: str, data: dict) -> dict:
        self._throttle()
        resp = requests.post(self._url(resource), headers=self._headers(), json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _put(self, resource: str, data: dict) -> dict:
        self._throttle()
        resp = requests.put(self._url(resource), headers=self._headers(), json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, resource: str):
        self._throttle()
        resp = requests.delete(self._url(resource), headers=self._headers(), timeout=30)
        if resp.status_code != 204:
            resp.raise_for_status()

    # ==================== CONNECTION ====================
    def test_connection(self) -> dict:
        if self.mock_mode:
            return {
                'success': False,
                'connected': False,
                'message': 'Lightspeed eSeries (Ecwid) not configured. Set Store ID and Secret Token in Settings.',
                'mock_mode': True
            }
        try:
            data = self._get("profile")
            store_name = data.get("generalInfo", {}).get("storeUrl", "")
            account_name = data.get("account", {}).get("accountName", "")
            return {
                'success': True,
                'connected': True,
                'message': f'Connected to Ecwid store. Account: {account_name or store_name or self.store_id}',
                'mock_mode': False,
                'store_id': self.store_id,
            }
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 403:
                msg = 'Authentication failed. Check your Store ID and Secret Token.'
            elif status == 404:
                msg = f'Store not found. Verify your Store ID ({self.store_id}).'
            else:
                msg = f'HTTP error {status}: {str(e)}'
            return {'success': False, 'connected': False, 'message': msg, 'mock_mode': False}
        except Exception as e:
            return {'success': False, 'connected': False, 'message': f'Connection failed: {str(e)}', 'mock_mode': False}

    # ==================== CATEGORIES ====================
    def get_categories(self) -> dict:
        """Fetch all categories from Ecwid store."""
        if self.mock_mode:
            return {'success': False, 'error': 'Ecwid not configured', 'categories': []}
        try:
            all_categories = []
            offset = 0
            limit = 100
            while True:
                data = self._get("categories", params={"offset": offset, "limit": limit})
                items = data.get("items", [])
                if not items:
                    break
                all_categories.extend(items)
                total = data.get("total", 0)
                offset += limit
                if offset >= total:
                    break

            result = []
            for cat in all_categories:
                result.append({
                    'lightspeed_category_id': cat.get('id'),
                    'category_name': cat.get('name', ''),
                    'parent_id': cat.get('parentId'),
                    'parent_category': None,
                    'url': cat.get('url', ''),
                    'is_visible': cat.get('enabled', True),
                    'product_count': cat.get('productCount', 0),
                })

            logger.info(f"Fetched {len(result)} categories from Ecwid")
            return {'success': True, 'categories': result}

        except Exception as e:
            logger.error(f"Error fetching Ecwid categories: {e}")
            return {'success': False, 'error': str(e), 'categories': []}

    def create_category(self, name: str, parent_id: int = None) -> dict:
        """Create a category in Ecwid."""
        if self.mock_mode:
            return {'success': False, 'error': 'Ecwid not configured'}
        try:
            payload = {
                'name': name,
                'enabled': True,
            }
            if parent_id:
                payload['parentId'] = parent_id

            data = self._post("categories", payload)
            cat_id = data.get('id')
            return {'success': True, 'id': cat_id, 'title': name}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ==================== PRODUCTS ====================
    def create_or_update_product(self, product: dict) -> dict:
        """Create or update a product in Ecwid with variants and images."""
        if self.mock_mode:
            import random
            mock_id = random.randint(1000, 9999)
            logger.info(f"[MOCK] Pushed '{product.get('product_name')}' -> Ecwid ID mock_{mock_id}")
            return {'success': True, 'lightspeed_id': f'mock_{mock_id}', 'created': True, 'mock_mode': True}

        try:
            sku = product.get('supplier_sku', '')
            cost_price = float(product.get('cost_price', 0) or 0)
            sale_price = float(product.get('base_price', 0) or 0)

            logger.info(f"Syncing product {sku} to Ecwid: Cost={cost_price}, Sale={sale_price}")

            # Check if product exists by SKU search
            existing_product_id = self._find_product_by_sku(sku)

            product_data = {
                'name': product.get('product_name', ''),
                'sku': sku,
                'price': sale_price,
                'costPrice': cost_price,
                'description': product.get('description', '') or '',
                'enabled': True,
            }

            # Assign category
            category_id = product.get('category_id')
            if category_id:
                product_data['categoryIds'] = [int(category_id)]

            if existing_product_id:
                # Update existing product
                self._put(f"products/{existing_product_id}", product_data)
                ls_id = existing_product_id
                logger.info(f"Updated product {sku} (Ecwid ID: {ls_id})")
            else:
                # Create new product
                data = self._post("products", product_data)
                ls_id = data.get('id')
                logger.info(f"Created product {sku} (Ecwid ID: {ls_id})")

            if not ls_id:
                return {'success': False, 'error': 'Failed to get product ID from Ecwid'}

            # Sync variants (combinations in Ecwid)
            variants = product.get('variants', [])
            if variants:
                self._sync_combinations(ls_id, variants, cost_price, sale_price)

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
            logger.error(f"Ecwid API error {status}: {body}")
            return {'success': False, 'error': f'Ecwid API error {status}: {body}'}
        except Exception as e:
            logger.error(f"Ecwid push error: {e}")
            return {'success': False, 'error': str(e)}

    def _find_product_by_sku(self, sku: str):
        """Find a product ID by searching by SKU."""
        try:
            data = self._get("products", params={"keyword": sku, "limit": 10})
            items = data.get("items", [])
            for item in items:
                if item.get("sku") == sku:
                    return item.get("id")
        except Exception:
            pass
        return None

    def _sync_combinations(self, product_id: int, variants: list, cost_price: float, sale_price: float):
        """Sync product combinations (variants) in Ecwid."""
        try:
            # Get existing combinations
            existing = []
            try:
                data = self._get(f"products/{product_id}/combinations")
                existing = data if isinstance(data, list) else []
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 404:
                    existing = []
                else:
                    raise

            existing_by_sku = {}
            for combo in existing:
                if combo.get('sku'):
                    existing_by_sku[combo['sku']] = combo

            for v in variants:
                v_sku = v.get('variant_sku', '') or v.get('sku', '')
                v_qty = int(v.get('inventory', 0) or v.get('inventory_quantity', 0) or 0)
                v_price = float(v.get('price', 0) or sale_price)
                v_cost = float(v.get('cost_price', 0) or cost_price)
                color = v.get('color', '')
                size = v.get('size', '')

                options = []
                if color:
                    options.append({'name': 'Color', 'value': color})
                if size:
                    options.append({'name': 'Size', 'value': size})
                if not options:
                    options.append({'name': 'Variant', 'value': v_sku or 'Default'})

                combo_data = {
                    'sku': v_sku,
                    'price': v_price - sale_price,  # Ecwid uses price modifier
                    'costPrice': v_cost,
                    'quantity': v_qty,
                    'options': options,
                }

                if v_sku in existing_by_sku:
                    combo_id = existing_by_sku[v_sku].get('id')
                    try:
                        self._put(f"products/{product_id}/combinations/{combo_id}", combo_data)
                    except Exception as e:
                        logger.warning(f"Failed to update combination {v_sku}: {e}")
                else:
                    try:
                        self._post(f"products/{product_id}/combinations", combo_data)
                    except Exception as e:
                        logger.warning(f"Failed to create combination {v_sku}: {e}")

        except Exception as e:
            logger.error(f"Error syncing combinations for product {product_id}: {e}")

    def _sync_images(self, product_id: int, images: list):
        """Upload product images to Ecwid. Uses the image upload endpoint."""
        try:
            synced = 0
            for i, img in enumerate(images[:5]):
                img_url = img.get('url', '')
                img_path = img.get('local_path', '')
                img_base64 = img.get('image_base64', '')

                image_bytes = None

                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        image_bytes = f.read()
                elif img_base64:
                    image_bytes = base64.b64decode(img_base64)
                elif img_url:
                    try:
                        resp = requests.get(img_url, timeout=20, headers={
                            'User-Agent': 'Mozilla/5.0'
                        })
                        if resp.status_code == 200 and len(resp.content) > 1000:
                            content_type = resp.headers.get('content-type', '').lower()
                            if 'image' in content_type or resp.content[:4] in (b'\xff\xd8\xff\xe0', b'\x89PNG', b'GIF8'):
                                image_bytes = resp.content
                    except Exception as e:
                        logger.warning(f"Failed to download image from {img_url[:80]}: {e}")

                if image_bytes:
                    try:
                        self._throttle()
                        # Ecwid image upload uses binary body with content-type
                        url = self._url(f"products/{product_id}/image")
                        headers = {
                            "Authorization": f"Bearer {self.secret_token}",
                            "Content-Type": "image/jpeg",
                        }
                        resp = requests.post(url, headers=headers, data=image_bytes, timeout=30)
                        resp.raise_for_status()
                        synced += 1
                    except Exception as e:
                        logger.warning(f"Failed to upload image to Ecwid: {e}")

            if synced > 0:
                logger.info(f"Synced {synced} images for Ecwid product {product_id}")

        except Exception as e:
            logger.error(f"Error syncing images for product {product_id}: {e}")

    # ==================== INVENTORY (standalone) ====================
    def update_product_inventory(self, product_id: int, quantity: int):
        """Update inventory for a product."""
        if self.mock_mode:
            return {'success': False, 'error': 'Not configured'}
        try:
            self._put(f"products/{product_id}", {"quantity": quantity})
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def update_combination_inventory(self, product_id: int, combination_id: int, quantity: int):
        """Update inventory for a specific combination (variant)."""
        if self.mock_mode:
            return {'success': False, 'error': 'Not configured'}
        try:
            self._put(f"products/{product_id}/combinations/{combination_id}", {"quantity": quantity})
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
