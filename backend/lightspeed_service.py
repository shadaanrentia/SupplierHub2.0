"""
Lightspeed Retail (X-Series) API integration service.
Supports both Personal Token and OAuth 2.0 (Private App) authentication.
Base URL: https://{domain_prefix}.retail.lightspeed.app/api/{version}
API Version: Date-based (2026-01). Docs: https://x-series-api.lightspeedhq.com/docs/introduction
"""
import logging
import requests
import base64
import time
import os
import io
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

API_VERSION = "2026-01"


class LightspeedService:
    """Lightspeed Retail (X-Series) integration via REST API (date-based versioning)."""

    def __init__(self, domain_prefix: str = '', personal_token: str = '',
                 access_token: str = '', client_id: str = '', client_secret: str = '',
                 refresh_token: str = '', token_expires_at=None):
        self.domain_prefix = (domain_prefix or '').strip()
        self.personal_token = (personal_token or '').strip()
        self.access_token = (access_token or '').strip()
        self.client_id = (client_id or '').strip()
        self.client_secret = (client_secret or '').strip()
        self.refresh_token = (refresh_token or '').strip()
        self.token_expires_at = token_expires_at
        self.token_was_refreshed = False
        self._last_request_time = 0
        self._variant_attr_cache = {}  # {"Color": "attr-id-123", "Size": "attr-id-456"}

        has_oauth = bool(self.access_token and self.domain_prefix)
        has_personal = bool(self.personal_token and self.domain_prefix)
        self.mock_mode = not (has_oauth or has_personal)

        if self.mock_mode:
            logger.info("Lightspeed X-Series connector: MOCK mode (no credentials)")
        elif has_oauth:
            logger.info("Lightspeed X-Series connector: OAuth mode")
            self._maybe_refresh_token()
        else:
            logger.info("Lightspeed X-Series connector: Personal Token mode")

    def _maybe_refresh_token(self):
        """Refresh the OAuth token if it's expired or about to expire."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return
        if self.token_expires_at is None:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if isinstance(self.token_expires_at, datetime):
            expires = self.token_expires_at
        else:
            return
        if now < (expires - timedelta(minutes=5)):
            return
        logger.info("Lightspeed access token expired or expiring soon, refreshing...")
        try:
            token_url = f"https://{self.domain_prefix}.retail.lightspeed.app/api/1.0/token"
            resp = requests.post(token_url, data={
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
            }, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get('access_token', '')
                new_refresh = data.get('refresh_token', '')
                if new_refresh:
                    self.refresh_token = new_refresh
                expires_in = int(data.get('expires_in', 86400))
                self.token_expires_at = now + timedelta(seconds=expires_in)
                self.token_was_refreshed = True
                logger.info(f"Lightspeed token refreshed (expires in {expires_in}s)")
            else:
                logger.error(f"Token refresh failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Token refresh error: {e}")

    def _base_url(self) -> str:
        return f"https://{self.domain_prefix}.retail.lightspeed.app/api/{API_VERSION}"

    def _url(self, resource: str) -> str:
        return f"{self._base_url()}/{resource}"

    def _active_token(self) -> str:
        return self.access_token or self.personal_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._active_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.12:
            time.sleep(0.12 - elapsed)
        self._last_request_time = time.time()

    def _handle_rate_limit(self, resp):
        remaining = resp.headers.get('X-RateLimit-Remaining')
        if remaining is not None and int(remaining) < 10:
            reset_at = resp.headers.get('X-RateLimit-Reset')
            if reset_at:
                wait = max(int(reset_at) - int(time.time()), 1)
                logger.warning(f"Lightspeed rate limit low ({remaining}), sleeping {wait}s")
                time.sleep(min(wait, 30))

    def _get(self, resource: str, params: dict = None) -> dict:
        self._throttle()
        resp = requests.get(self._url(resource), headers=self._headers(), params=params, timeout=30)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _post(self, resource: str, data: dict) -> dict:
        self._throttle()
        resp = requests.post(self._url(resource), headers=self._headers(), json=data, timeout=30)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _put(self, resource: str, data: dict) -> dict:
        self._throttle()
        resp = requests.put(self._url(resource), headers=self._headers(), json=data, timeout=30)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, resource: str):
        self._throttle()
        resp = requests.delete(self._url(resource), headers=self._headers(), timeout=30)
        self._handle_rate_limit(resp)
        if resp.status_code not in (200, 204):
            resp.raise_for_status()

    # ==================== CONNECTION ====================
    def test_connection(self) -> dict:
        if self.mock_mode:
            if self.client_id and self.domain_prefix and not self.access_token:
                return {
                    'success': False, 'connected': False,
                    'message': 'OAuth credentials saved. Click "Connect to Lightspeed" to authorize.',
                    'mock_mode': False, 'needs_oauth': True,
                }
            return {
                'success': False, 'connected': False,
                'message': 'Lightspeed not configured. Set Domain Prefix and credentials in Settings.',
                'mock_mode': True
            }
        try:
            data = self._get("products", params={"page_size": 1})
            auth_mode = "OAuth" if self.access_token else "Personal Token"
            return {
                'success': True, 'connected': True,
                'message': f'Connected to Lightspeed Retail ({self.domain_prefix}) via {auth_mode}. API version {API_VERSION}.',
                'mock_mode': False, 'domain_prefix': self.domain_prefix, 'auth_mode': auth_mode,
            }
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            body = ''
            try:
                body = e.response.text[:300]
            except Exception:
                pass
            if status == 401:
                if self.access_token and self.refresh_token:
                    msg = 'OAuth token expired or invalid. Try disconnecting and reconnecting.'
                else:
                    msg = 'Authentication failed. Check your Personal Token.'
            elif status == 403:
                msg = 'Access forbidden. Your token may lack required scopes.'
            elif status == 404:
                msg = f'Store not found. Verify your Domain Prefix ({self.domain_prefix}).'
            else:
                msg = f'HTTP error {status}: {body}'
            return {'success': False, 'connected': False, 'message': msg, 'mock_mode': False}
        except requests.ConnectionError:
            return {
                'success': False, 'connected': False,
                'message': f'Cannot connect to {self.domain_prefix}.retail.lightspeed.app. Check your Domain Prefix.',
                'mock_mode': False
            }
        except Exception as e:
            return {'success': False, 'connected': False, 'message': f'Connection failed: {str(e)}', 'mock_mode': False}

    # ==================== VARIANT ATTRIBUTES ====================
    def _ensure_variant_attributes(self, needed: list) -> dict:
        """Ensure variant attributes (e.g., 'Color', 'Size') exist. Returns {name: id} mapping."""
        if not needed:
            return {}
        # Fetch existing attributes
        if not self._variant_attr_cache:
            try:
                data = self._get("variant_attributes", params={"page_size": 200})
                for attr in data.get('data', []):
                    self._variant_attr_cache[attr['name']] = attr['id']
            except Exception as e:
                logger.warning(f"Failed to fetch variant attributes: {e}")

        result = {}
        for name in needed:
            if name in self._variant_attr_cache:
                result[name] = self._variant_attr_cache[name]
            else:
                try:
                    resp = self._post("variant_attributes", {"name": name})
                    attr = resp.get('data', resp)
                    attr_id = attr.get('id')
                    if attr_id:
                        self._variant_attr_cache[name] = attr_id
                        result[name] = attr_id
                        logger.info(f"Created variant attribute '{name}' -> {attr_id}")
                except Exception as e:
                    logger.warning(f"Failed to create variant attribute '{name}': {e}")
        return result

    # ==================== CATEGORIES ====================
    def get_categories(self) -> dict:
        if self.mock_mode:
            return {'success': False, 'error': 'Lightspeed not configured', 'categories': []}
        try:
            all_categories = []
            after = None
            while True:
                params = {"page_size": 200}
                if after:
                    params["after"] = after
                data = self._get("product_categories", params=params)
                items = data.get("data", [])
                if not items:
                    break
                all_categories.extend(items)
                version = data.get("version", {}).get("max")
                if version and len(items) >= 200:
                    after = version
                else:
                    break
            result = []
            for cat in all_categories:
                result.append({
                    'lightspeed_category_id': cat.get('id'),
                    'category_name': cat.get('name', ''),
                    'parent_id': cat.get('parent_id'),
                    'parent_category': None,
                    'is_visible': not cat.get('deleted_at'),
                })
            logger.info(f"Fetched {len(result)} categories from Lightspeed")
            return {'success': True, 'categories': result}
        except Exception as e:
            logger.error(f"Error fetching Lightspeed categories: {e}")
            return {'success': False, 'error': str(e), 'categories': []}

    def create_category(self, name: str) -> dict:
        if self.mock_mode:
            return {'success': False, 'error': 'Lightspeed not configured'}
        try:
            data = self._post("product_categories", {'name': name})
            cat = data.get('data', data)
            return {'success': True, 'id': cat.get('id'), 'title': cat.get('name', name)}
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
            variants = product.get('variants', [])

            logger.info(f"Syncing product {sku} to Lightspeed: Cost={cost_price}, Sale={sale_price}, Variants={len(variants)}")

            existing_product_id = self._find_product_by_sku(sku)

            if existing_product_id:
                # Update existing product
                update_data = {
                    'name': product.get('product_name', ''),
                    'description': product.get('description', '') or '',
                    'supply_price': cost_price,
                    'price_excluding_tax': sale_price,
                    'is_active': True,
                }
                category_id = product.get('category_id')
                if category_id:
                    update_data['product_type_id'] = str(category_id)

                data = self._put(f"products/{existing_product_id}", update_data)
                ls_product = data.get('data', data)
                ls_id = ls_product.get('id', existing_product_id)
                logger.info(f"Updated product {sku} (Lightspeed ID: {ls_id})")
            else:
                # Create new product
                if variants and len(variants) > 1:
                    ls_id = self._create_variant_product(product, variants, cost_price, sale_price)
                else:
                    ls_id = self._create_simple_product(product, cost_price, sale_price)

            if not ls_id:
                return {'success': False, 'error': 'Failed to get product ID from Lightspeed'}

            # Upload images
            images = product.get('images', [])
            if images:
                self._upload_images(ls_id, images)

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

    def _create_simple_product(self, product: dict, cost_price: float, sale_price: float) -> str:
        """Create a simple product (no variants or single variant)."""
        product_data = {
            'name': product.get('product_name', ''),
            'description': product.get('description', '') or '',
            'sku': product.get('supplier_sku', ''),
            'supply_price': cost_price,
            'price_excluding_tax': sale_price,
            'is_active': True,
        }
        category_id = product.get('category_id')
        if category_id:
            product_data['product_type_id'] = str(category_id)

        data = self._post("products", product_data)
        ls_product = data.get('data', data)
        ls_id = ls_product.get('id') if isinstance(ls_product, dict) else None
        # If response is a list (variant creation returns list of IDs), take first
        if isinstance(ls_product, list) and ls_product:
            ls_id = ls_product[0]
        logger.info(f"Created simple product '{product.get('product_name')}' (Lightspeed ID: {ls_id})")
        return ls_id

    def _create_variant_product(self, product: dict, variants: list, cost_price: float, sale_price: float) -> str:
        """Create a product with multiple variants using variant_definitions."""
        # Determine which variant attributes are needed
        attr_names = set()
        for v in variants:
            if v.get('color'):
                attr_names.add('Color')
            if v.get('size'):
                attr_names.add('Size')
        if not attr_names:
            # No variant attributes found, create as simple product
            return self._create_simple_product(product, cost_price, sale_price)

        # Ensure variant attributes exist
        attr_map = self._ensure_variant_attributes(list(attr_names))
        if not attr_map:
            logger.warning("Could not create variant attributes, falling back to simple product")
            return self._create_simple_product(product, cost_price, sale_price)

        # Build variant definitions
        variant_list = []
        for v in variants:
            definitions = []
            color = v.get('color', '')
            size = v.get('size', '')
            if color and 'Color' in attr_map:
                definitions.append({'attribute_id': attr_map['Color'], 'value': color})
            if size and 'Size' in attr_map:
                definitions.append({'attribute_id': attr_map['Size'], 'value': size})
            if definitions:
                variant_list.append({'variant_definitions': definitions})

        if not variant_list:
            return self._create_simple_product(product, cost_price, sale_price)

        product_data = {
            'name': product.get('product_name', ''),
            'description': product.get('description', '') or '',
            'supply_price': cost_price,
            'price_excluding_tax': sale_price,
            'is_active': True,
            'variants': variant_list,
        }
        category_id = product.get('category_id')
        if category_id:
            product_data['product_type_id'] = str(category_id)

        data = self._post("products", product_data)
        ls_result = data.get('data', data)

        # Response for variant creation is a list of IDs
        if isinstance(ls_result, list):
            parent_id = ls_result[0] if ls_result else None
            logger.info(f"Created variant product '{product.get('product_name')}' with {len(ls_result)} variants (parent: {parent_id})")

            # Update individual variants with SKU and pricing
            self._update_variant_details(ls_result, variants, cost_price, sale_price)
            return parent_id
        elif isinstance(ls_result, dict):
            ls_id = ls_result.get('id')
            logger.info(f"Created product '{product.get('product_name')}' (Lightspeed ID: {ls_id})")
            return ls_id

        return None

    def _update_variant_details(self, variant_ids: list, variants: list, default_cost: float, default_sale: float):
        """Update individual variant products with SKU and pricing after creation."""
        for i, vid in enumerate(variant_ids):
            if i >= len(variants):
                break
            v = variants[i]
            v_sku = v.get('variant_sku', '') or v.get('sku', '')
            v_price = float(v.get('price', 0) or default_sale)
            v_cost = float(v.get('cost_price', 0) or default_cost)

            update_data = {}
            if v_sku:
                update_data['sku'] = v_sku
            if v_cost > 0:
                update_data['supply_price'] = v_cost
            if v_price > 0:
                update_data['price_excluding_tax'] = v_price

            if update_data:
                try:
                    self._put(f"products/{vid}", update_data)
                except Exception as e:
                    logger.warning(f"Failed to update variant {vid} details: {e}")

    def _find_product_by_sku(self, sku: str):
        """Find a product ID by SKU lookup."""
        try:
            data = self._get("products", params={"sku": sku})
            items = data.get("data", [])
            if items:
                return items[0].get("id")
        except Exception:
            pass
        return None

    def _upload_images(self, product_id: str, images: list):
        """Upload product images via the image_upload action endpoint."""
        try:
            synced = 0
            for i, img in enumerate(images[:5]):
                img_url = img.get('url', '')
                img_path = img.get('local_path', '')
                img_base64 = img.get('image_base64', '')

                image_bytes = None
                filename = f'product_{product_id}_img_{i+1}.jpg'

                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        image_bytes = f.read()
                    filename = os.path.basename(img_path)
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
                        url = self._url(f"products/{product_id}/actions/image_upload")
                        headers = {"Authorization": f"Bearer {self._active_token()}"}
                        files = {'image': (filename, io.BytesIO(image_bytes), 'image/jpeg')}
                        resp = requests.post(url, headers=headers, files=files, timeout=30)
                        self._handle_rate_limit(resp)
                        resp.raise_for_status()
                        synced += 1
                    except Exception as e:
                        logger.warning(f"Failed to upload image to Lightspeed: {e}")

            if synced > 0:
                logger.info(f"Synced {synced} images for Lightspeed product {product_id}")

        except Exception as e:
            logger.error(f"Error syncing images for product {product_id}: {e}")

    # ==================== INVENTORY ====================
    def update_product_inventory(self, product_id: str, outlet_id: str, count: int):
        if self.mock_mode:
            return {'success': False, 'error': 'Not configured'}
        try:
            self._put(f"products/{product_id}", {
                'inventory': [{'outlet_id': outlet_id, 'count': count}]
            })
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
