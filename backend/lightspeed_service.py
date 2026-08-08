"""
Lightspeed Retail (X-Series) API integration service.
Supports both Personal Token and OAuth 2.0 (Private App) authentication.
Base URL: https://{domain_prefix}.retail.lightspeed.app/api/{version}
API Version: Date-based (2026-07). Docs: https://x-series-api.lightspeedhq.com/docs/introduction

Reference implementation based on user's sample lightspeed-product app.
"""
import logging
import requests
import base64
import time
import os
import io
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

API_VERSION = "2026-07"


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
        self._variant_attr_cache = {}

        has_oauth = bool(self.access_token and self.domain_prefix)
        has_personal = bool(self.personal_token and self.domain_prefix)
        self.mock_mode = not (has_oauth or has_personal)

        if self.mock_mode:
            logger.info("Lightspeed X-Series: MOCK mode (no credentials)")
        elif has_oauth:
            logger.info("Lightspeed X-Series: OAuth mode")
            self._maybe_refresh_token()
        else:
            logger.info("Lightspeed X-Series: Personal Token mode")

    def _maybe_refresh_token(self):
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return
        if not isinstance(self.token_expires_at, datetime):
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if now < (self.token_expires_at - timedelta(minutes=5)):
            return
        logger.info("Lightspeed token expiring, refreshing...")
        try:
            resp = requests.post(
                f"https://{self.domain_prefix}.retail.lightspeed.app/api/1.0/token",
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': self.refresh_token,
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                }, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get('access_token', '')
                if data.get('refresh_token'):
                    self.refresh_token = data['refresh_token']
                expires_in = int(data.get('expires_in', 86400))
                self.token_expires_at = now + timedelta(seconds=expires_in)
                self.token_was_refreshed = True
                logger.info(f"Token refreshed (expires in {expires_in}s)")
            else:
                logger.error(f"Token refresh failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Token refresh error: {e}")

    # ==================== HTTP HELPERS ====================
    def _base_url(self) -> str:
        return f"https://{self.domain_prefix}.retail.lightspeed.app/api/{API_VERSION}"

    def _url(self, resource: str) -> str:
        return f"{self._base_url()}/{resource.lstrip('/')}"

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
                logger.warning(f"Rate limit low ({remaining}), sleeping {wait}s")
                time.sleep(min(wait, 30))

    def _handle_response(self, resp):
        """Validate and parse response. Matches reference app pattern."""
        if resp.ok:
            try:
                return resp.json()
            except ValueError:
                return {"success": True, "status_code": resp.status_code, "body": resp.text}
        logger.error(f"Lightspeed API Error ({resp.status_code}): {resp.text[:300]}")
        resp.raise_for_status()

    def _get(self, endpoint: str, params: dict = None) -> dict:
        self._throttle()
        resp = requests.get(self._url(endpoint), headers=self._headers(), params=params, timeout=120)
        self._handle_rate_limit(resp)
        return self._handle_response(resp)

    def _post(self, endpoint: str, data: dict) -> dict:
        self._throttle()
        resp = requests.post(self._url(endpoint), headers=self._headers(), json=data, timeout=120)
        self._handle_rate_limit(resp)
        return self._handle_response(resp)

    def _put(self, endpoint: str, data: dict) -> dict:
        self._throttle()
        resp = requests.put(self._url(endpoint), headers=self._headers(), json=data, timeout=120)
        self._handle_rate_limit(resp)
        return self._handle_response(resp)

    def _delete(self, endpoint: str):
        self._throttle()
        resp = requests.delete(self._url(endpoint), headers=self._headers(), timeout=120)
        self._handle_rate_limit(resp)
        if resp.status_code not in (200, 204):
            return self._handle_response(resp)

    def _upload(self, endpoint: str, image_bytes: bytes, filename: str) -> dict:
        """Upload image via multipart/form-data (no Content-Type header)."""
        self._throttle()
        headers = {
            "Authorization": f"Bearer {self._active_token()}",
            "Accept": "application/json",
        }
        files = {'image': (filename, io.BytesIO(image_bytes), 'image/jpeg')}
        resp = requests.post(self._url(endpoint), headers=headers, files=files, timeout=120)
        self._handle_rate_limit(resp)
        return self._handle_response(resp)

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
            data = self._get("products", params={"page": 1, "limit": 1})
            auth_mode = "OAuth" if self.access_token else "Personal Token"
            return {
                'success': True, 'connected': True,
                'message': f'Connected to Lightspeed Retail ({self.domain_prefix}) via {auth_mode}. API v{API_VERSION}.',
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
                msg = 'Authentication failed. Check your token or reconnect OAuth.'
            elif status == 403:
                msg = 'Access forbidden. Token may lack required scopes.'
            elif status == 404:
                msg = f'Store not found. Verify Domain Prefix ({self.domain_prefix}).'
            else:
                msg = f'HTTP error {status}: {body}'
            return {'success': False, 'connected': False, 'message': msg, 'mock_mode': False}
        except requests.ConnectionError:
            return {
                'success': False, 'connected': False,
                'message': f'Cannot connect to {self.domain_prefix}.retail.lightspeed.app.',
                'mock_mode': False
            }
        except Exception as e:
            return {'success': False, 'connected': False, 'message': str(e), 'mock_mode': False}

    # ==================== VARIANT ATTRIBUTES ====================
    def _ensure_variant_attributes(self, needed: list) -> dict:
        """Ensure variant attributes exist. Returns {name: id} mapping."""
        if not needed:
            return {}
        if not self._variant_attr_cache:
            try:
                data = self._get("variant_attributes")
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
        """Fetch all product categories. Response: data.data.categories[]"""
        if self.mock_mode:
            return {'success': False, 'error': 'Lightspeed not configured', 'categories': []}
        try:
            all_categories = []
            page = 1
            while True:
                data = self._get("product_categories", params={"page": page, "limit": 200})
                # 2026-07 response: {data: {page_info: {...}, data: {categories: [...]}}}
                inner = data.get("data", {})
                cats_data = inner.get("data", {}).get("categories", [])
                if not cats_data:
                    # Fallback for older format: data: [...]
                    if isinstance(inner, list):
                        cats_data = inner
                    else:
                        break
                all_categories.extend(cats_data)
                page_info = inner.get("page_info", {})
                if page_info.get("has_next"):
                    page += 1
                else:
                    break

            result = []
            for cat in all_categories:
                result.append({
                    'lightspeed_category_id': cat.get('id'),
                    'category_name': cat.get('name', ''),
                    'parent_id': cat.get('parent_category_id'),
                    'root_category_id': cat.get('root_category_id'),
                    'leaf_category': cat.get('leaf_category', False),
                    'category_path': cat.get('category_path', []),
                    'is_visible': True,
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

    # ==================== SUPPLIERS ====================
    def _get_or_create_supplier(self, supplier_name: str) -> str:
        """Find or create a supplier in Lightspeed. Returns supplier_id or None."""
        if not supplier_name:
            return None
        try:
            # Search by name
            data = self._get("suppliers", params={"name": supplier_name})
            items = data.get("data", [])
            if isinstance(items, list) and items:
                return items[0].get("id")
        except Exception:
            pass
        # Create new
        try:
            resp = self._post("suppliers", {"name": supplier_name})
            supplier = resp.get("data", resp)
            if isinstance(supplier, dict) and supplier.get("id"):
                logger.info(f"Created Lightspeed supplier '{supplier_name}' (ID: {supplier['id']})")
                return supplier["id"]
        except Exception as e:
            logger.warning(f"Failed to create supplier '{supplier_name}': {e}")
        return None

    # ==================== PRODUCTS ====================
    def create_or_update_product(self, product: dict) -> dict:
        """Create or update a product in Lightspeed with variants and images."""
        if self.mock_mode:
            import random
            mock_id = random.randint(1000, 9999)
            return {'success': True, 'lightspeed_id': f'mock_{mock_id}', 'created': True, 'mock_mode': True}

        try:
            sku = product.get('supplier_sku', '')
            cost_price = float(product.get('cost_price', 0) or 0)
            sale_price = float(product.get('base_price', 0) or 0)
            variants = product.get('variants', [])
            supplier_name = product.get('supplier_name', '')

            logger.info(f"Syncing product {sku}: SupplierPrice={cost_price}, RetailPrice={sale_price}, Variants={len(variants)}, Images={len(product.get('images', []))}")

            # Get or create supplier in Lightspeed
            ls_supplier_id = None
            if supplier_name:
                ls_supplier_id = self._get_or_create_supplier(supplier_name)

            # Check if product exists by SKU
            existing_product_id = self._find_product_by_sku(sku)

            if existing_product_id:
                update_data = {
                    'name': product.get('product_name', ''),
                    'description': product.get('description', '') or '',
                    'supply_price': cost_price,
                    'price_excluding_tax': sale_price,
                }
                if product.get('category_id'):
                    update_data['product_category_id'] = str(product['category_id'])
                if ls_supplier_id:
                    update_data['supplier_id'] = ls_supplier_id
                data = self._put(f"products/{existing_product_id}", update_data)
                ls_product = data.get('data', data)
                ls_id = ls_product.get('id', existing_product_id) if isinstance(ls_product, dict) else existing_product_id
                logger.info(f"Updated product {sku} (ID: {ls_id})")
            else:
                # Create new product
                ls_id = self._create_product(product, variants, cost_price, sale_price, ls_supplier_id)

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
            return {'success': False, 'error': f'API error {status}: {body}'}
        except Exception as e:
            logger.error(f"Lightspeed push error: {e}")
            return {'success': False, 'error': str(e)}

    def _create_product(self, product: dict, variants: list, cost_price: float, sale_price: float, supplier_id: str = None) -> str:
        """Create a product, with or without variants."""
        product_name = product.get('product_name', '')
        description = product.get('description', '') or ''
        sku = product.get('supplier_sku', '')
        category_id = product.get('category_id')

        # Determine if we need variant attributes
        attr_names = set()
        for v in variants:
            if v.get('color'):
                attr_names.add('Color')
            if v.get('size'):
                attr_names.add('Size')

        if variants and len(variants) > 1 and attr_names:
            # Variant product
            attr_map = self._ensure_variant_attributes(list(attr_names))
            if not attr_map:
                logger.warning("No variant attributes, creating simple product")
                return self._create_simple_product(product_name, description, sku, cost_price, sale_price, category_id, supplier_id)

            variant_list = []
            for v in variants:
                definitions = []
                color = v.get('color', '')
                size = v.get('size', '')
                if color and 'Color' in attr_map:
                    definitions.append({'attribute_id': attr_map['Color'], 'value': color})
                if size and 'Size' in attr_map:
                    definitions.append({'attribute_id': attr_map['Size'], 'value': size})
                if not definitions:
                    continue

                v_sku = v.get('variant_sku', '') or v.get('sku', '')
                v_price = float(v.get('price', 0) or sale_price)

                variant_list.append({
                    'sku': v_sku,
                    'price_excluding_tax': v_price,
                    'enabled': True,
                    'variant_definitions': definitions,
                })

            if not variant_list:
                return self._create_simple_product(product_name, description, sku, cost_price, sale_price, category_id, supplier_id)

            payload = {
                'name': product_name,
                'description': description,
                'supply_price': cost_price,
                'price_excluding_tax': sale_price,
                'status': 'ACTIVE',
                'variants': variant_list,
            }
            if category_id:
                payload['product_category_id'] = str(category_id)
            if supplier_id:
                payload['supplier_id'] = supplier_id

            response = self._post("products", payload)
            return self._extract_product_id(response, product_name)
        else:
            return self._create_simple_product(product_name, description, sku, cost_price, sale_price, category_id, supplier_id)

    def _create_simple_product(self, name, description, sku, cost_price, sale_price, category_id, supplier_id=None) -> str:
        """Create a simple product without variants."""
        payload = {
            'name': name,
            'description': description,
            'sku': sku,
            'supply_price': cost_price,
            'price_excluding_tax': sale_price,
            'status': 'ACTIVE',
            'is_active': True,
        }
        if category_id:
            payload['product_category_id'] = str(category_id)
        if supplier_id:
            payload['supplier_id'] = supplier_id

        response = self._post("products", payload)
        return self._extract_product_id(response, name)

    def _extract_product_id(self, response: dict, product_name: str) -> str:
        """Extract product ID from creation response. Handles both new and 'already exists' cases."""
        if isinstance(response, dict) and response.get("data"):
            data = response["data"]
            # Variant creation returns list of IDs
            if isinstance(data, list) and data:
                logger.info(f"Created variant product '{product_name}' ({len(data)} variants)")
                return data[0]
            # Simple product returns dict
            if isinstance(data, dict) and data.get("id"):
                logger.info(f"Created simple product '{product_name}' (ID: {data['id']})")
                return data["id"]

        # Product already exists - Lightspeed returns existing ID
        if isinstance(response, dict) and response.get("fields", {}).get("name_existing_id"):
            existing_id = response["fields"]["name_existing_id"]
            logger.info(f"Product '{product_name}' already exists (ID: {existing_id})")
            return existing_id

        logger.warning(f"Could not extract product ID for '{product_name}': {str(response)[:200]}")
        return None

    def _find_product_by_sku(self, sku: str):
        """Find a product ID by SKU lookup."""
        try:
            data = self._get("products", params={"sku": sku})
            items = data.get("data", [])
            if isinstance(items, list) and items:
                return items[0].get("id")
        except Exception:
            pass
        return None

    def _upload_images(self, product_id: str, images: list):
        """Upload product images via the image_upload action endpoint."""
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
                    resp = requests.get(img_url, timeout=20, headers={'User-Agent': 'Mozilla/5.0'})
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        ct = resp.headers.get('content-type', '').lower()
                        if 'image' in ct or resp.content[:4] in (b'\xff\xd8\xff\xe0', b'\x89PNG', b'GIF8'):
                            image_bytes = resp.content
                except Exception as e:
                    logger.warning(f"Image download failed: {img_url[:80]}: {e}")

            if image_bytes:
                try:
                    self._upload(f"products/{product_id}/actions/image_upload", image_bytes, filename)
                    synced += 1
                except Exception as e:
                    logger.warning(f"Image upload failed for product {product_id}: {e}")

        if synced > 0:
            logger.info(f"Uploaded {synced} images for product {product_id}")

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
