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
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import deps
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
        self._supplier_cache = {}
        self._brand_cache = {}
        self._product_sku_cache = {}

        self._supplier_catalog_loaded = False
        self._brand_catalog_loaded = False

        self._supplier_catalog_lock = threading.Lock()
        self._brand_catalog_lock = threading.Lock()

        self._outlet_id_cache = None
        self._markup_cache = None
        self._variant_sync_semaphore = asyncio.Semaphore(5)
        self._throttle_lock = threading.Lock()
        self._image_executor = ThreadPoolExecutor(max_workers=5)
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
        with self._throttle_lock:
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
        """Validate and parse response while preserving Lightspeed validation details."""
        if resp.ok:
            try:
                return resp.json()
            except ValueError:
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "body": resp.text
                }
        try:
            error_data = resp.json()
        except ValueError:
            error_data = {
                "error": resp.text[:500]
            }
        if resp.status_code == 422:
            logger.warning(
                f"Lightspeed validation error (422): {str(error_data)[:1000]}"
            )
            return {
                "_lightspeed_validation_error": True,
                "status_code": 422,
                **error_data
            }
        logger.error(
            f"Lightspeed API Error ({resp.status_code}): {resp.text[:500]}"
        )
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

    def _patch_2026_10(self, endpoint: str, data: dict) -> dict:
        """PATCH request to Lightspeed 2026-10 API."""
        self._throttle()

        url = (
            f"https://{self.domain_prefix}.retail.lightspeed.app"
            f"/api/2026-10/{endpoint.lstrip('/')}"
        )

        resp = requests.patch(
            url,
            headers=self._headers(),
            json=data,
            timeout=120
        )

        self._handle_rate_limit(resp)
        return self._handle_response(resp)

    def _delete(self, endpoint: str):
        self._throttle()
        resp = requests.delete(self._url(endpoint), headers=self._headers(), timeout=120)
        self._handle_rate_limit(resp)
        if resp.status_code not in (200, 204):
            return self._handle_response(resp)

    def _upload(
        self,
        endpoint: str,
        image_bytes: bytes,
        filename: str,
        content_type: str = "image/jpeg"
    ) -> dict:
        """Upload image via multipart/form-data."""
        self._throttle()

        headers = {
            "Authorization": f"Bearer {self._active_token()}",
            "Accept": "application/json",
        }

        files = {
            "image": (
                filename,
                io.BytesIO(image_bytes),
                content_type
            )
        }

        resp = requests.post(
            self._url(endpoint),
            headers=headers,
            files=files,
            timeout=120
        )

        self._handle_rate_limit(resp)

        return self._handle_response(resp)

    def _put_legacy_21(self, endpoint: str, data: dict) -> dict:
        """PUT request to Lightspeed legacy 2.1 product API."""
        self._throttle()

        url = (
            f"https://{self.domain_prefix}.retail.lightspeed.app"
            f"/api/2.1/{endpoint.lstrip('/')}"
        )

        resp = requests.put(
            url,
            headers=self._headers(),
            json=data,
            timeout=120
        )

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

    # ==================== BRANDS ====================

    def _get_or_create_brand(self, brand_name: str) -> str:
        """
        Resolve a Lightspeed brand by name.

        Strategy:
        1. Check local cache.
        2. Load the complete brand catalog using pagination.
        3. Match brand name case-insensitively.
        4. If not found, create the brand.
        5. Cache the resolved ID.
        """

        if not brand_name:
            return None

        brand_name = str(brand_name).strip()

        if not brand_name:
            return None

        cache_key = brand_name.casefold()

        # 1. FAST CACHE LOOKUP
        cached_id = self._brand_cache.get(cache_key)

        if cached_id:
            return str(cached_id)

        # 2. LOAD COMPLETE BRAND CATALOG
        with self._brand_catalog_lock:

            cached_id = self._brand_cache.get(cache_key)

            if cached_id:
                return str(cached_id)

            if not self._brand_catalog_loaded:

                try:

                    page = 1
                    total_loaded = 0

                    while True:

                        response = self._get(
                            "brands",
                            params={
                                "page_size": 200,
                                "page": page
                            }
                        )
                        

                        data = response.get("data", response)

                        # Handle possible response wrappers.
                        items = []

                        if isinstance(data, list):

                            items = data

                        elif isinstance(data, dict):

                            items = (
                                data.get("brands")
                                or data.get("data")
                                or data.get("items")
                                or []
                            )

                        if not isinstance(items, list):
                            items = []

                        if not items:
                            break

                        for brand in items:

                            if not isinstance(brand, dict):
                                continue

                            brand_id = (
                                brand.get("id")
                                or brand.get("brand_id")
                            )

                            name = str(
                                brand.get("name")
                                or brand.get("brand_name")
                                or ""
                            ).strip()

                            if not brand_id or not name:
                                continue

                            self._brand_cache[
                                name.casefold()
                            ] = str(brand_id)

                            total_loaded += 1

                        # Check pagination information

                        page_info = {}

                        if isinstance(data, dict):

                            page_info = (
                                data.get("page_info")
                                or data.get("pagination")
                                or {}
                            )

                        has_next = False

                        if isinstance(page_info, dict):

                            has_next = bool(
                                page_info.get("has_next")
                                or page_info.get("hasNext")
                            )

                        if not has_next:
                            break

                        page += 1

                    self._brand_catalog_loaded = True

                    logger.info(
                        f"Loaded {len(self._brand_cache)} "
                        f"Lightspeed brands into cache "
                        f"(API records processed={total_loaded})"
                    )

                except Exception as e:

                    logger.warning(
                        f"Failed to load Lightspeed brand catalog: {e}",
                        exc_info=True
                    )

            # 3. TRY CACHE AGAIN
            cached_id = self._brand_cache.get(cache_key)

            if cached_id:

                logger.info(
                    f"Found Lightspeed brand "
                    f"'{brand_name}' -> {cached_id}"
                )

                return str(cached_id)

        # 4. BRAND DOES NOT EXIST — CREATE IT
        try:

            logger.info(
                f"Lightspeed brand '{brand_name}' "
                f"not found. Creating brand."
            )

            response = self._post(
                "brands",
                {
                    "name": brand_name
                }
            )

            if (
                isinstance(response, dict)
                and response.get("_lightspeed_validation_error")
            ):

                logger.error(
                    f"Lightspeed rejected brand creation "
                    f"'{brand_name}': {response}"
                )

                return None

            brand = response.get("data", response)

            if isinstance(brand, str):
                brand_id = brand.strip()
            elif isinstance(brand, dict):
                brand_id = (
                    brand.get("id")
                    or brand.get("brand_id")
                )
                if not brand_id and isinstance(brand.get("data"), dict):
                    nested = brand["data"]
                    brand_id = (
                        nested.get("id")
                        or nested.get("brand_id")
                    )
            else:
                brand_id = None

            if brand_id:
                brand_id = str(brand_id)

                self._brand_cache[cache_key] = brand_id

                logger.info(
                    f"Created Lightspeed brand "
                    f"'{brand_name}' -> {brand_id}"
                )

                return brand_id

            logger.warning(
                f"Lightspeed brand creation returned "
                f"no ID for '{brand_name}': {response}"
            )

        except Exception as e:

            logger.error(
                f"Failed to create Lightspeed brand "
                f"'{brand_name}': {e}",
                exc_info=True
            )

        return None

    # ==================== SUPPLIERS ====================
    def _get_or_create_supplier(self, supplier_name: str) -> str:
        """Resolve a Lightspeed supplier using a one-time catalog load."""
        if not supplier_name:
            return None

        supplier_name = str(supplier_name).strip()
        if not supplier_name:
            return None

        cache_key = supplier_name.casefold()

        # Fast local lookup
        cached_id = self._supplier_cache.get(cache_key)
        if cached_id:
            return cached_id

        # Load the supplier catalog only once.
        with self._supplier_catalog_lock:
            # Check again after acquiring the lock because another
            # worker may have populated the cache while we waited.
            cached_id = self._supplier_cache.get(cache_key)
            if cached_id:
                return cached_id

            if not self._supplier_catalog_loaded:
                try:
                    response = self._get(
                        "suppliers",
                        params={"page_size": 200}
                    )

                    items = response.get("data", [])

                    if isinstance(items, dict):
                        items = (
                            items.get("suppliers")
                            or items.get("data")
                            or items.get("items")
                            or []
                        )

                    if isinstance(items, list):
                        for supplier in items:
                            if not isinstance(supplier, dict):
                                continue

                            supplier_id = supplier.get("id")
                            name = str(
                                supplier.get("name", "")
                            ).strip()

                            if supplier_id and name:
                                self._supplier_cache[
                                    name.casefold()
                                ] = str(supplier_id)

                    self._supplier_catalog_loaded = True

                    logger.info(
                        f"Loaded {len(self._supplier_cache)} "
                        f"Lightspeed suppliers into cache"
                    )

                except Exception as e:
                    logger.warning(
                        f"Failed to load Lightspeed supplier catalog: {e}"
                    )

            # Try requested supplier after catalog loading.
            cached_id = self._supplier_cache.get(cache_key)
            if cached_id:
                return cached_id

        # Supplier was not found. Create it outside the lock.
        try:
            response = self._post(
                "suppliers",
                {"name": supplier_name}
            )

            supplier = response.get("data", response)

            if isinstance(supplier, dict) and supplier.get("id"):
                supplier_id = str(supplier["id"])

                self._supplier_cache[cache_key] = supplier_id

                logger.info(
                    f"Created Lightspeed supplier "
                    f"'{supplier_name}' -> {supplier_id}"
                )

                return supplier_id

        except Exception as e:
            logger.warning(
                f"Failed to create Lightspeed supplier "
                f"'{supplier_name}': {e}"
            )

        return None

    # ==================== PRODUCTS ====================
    async def create_or_update_product(self, product: dict) -> dict:
        """Create or update a product in Lightspeed with variants and images."""
        if self.mock_mode:
            import random
            mock_id = random.randint(1000, 9999)
            return {
                "success": True,
                "lightspeed_id": f"mock_{mock_id}",
                "created": True,
                "mock_mode": True
            }
        try:
            sku = product.get("supplier_sku", "")
            if not sku:
                return {
                    "success": False,
                    "error": "SupplierHub product is missing supplier_sku"
                }
            cost_price = float(product.get("cost_price", 0) or 0)
            sale_price = float(
                product.get("retail_price")
                or product.get("calculated_sale_price")
                or product.get("sale_price")
                or product.get("base_price")
                or 0
            )
            variants = product.get("variants", [])
            supplier_name = product.get("supplier_name", "")
            images = product.get("images", [])
            logger.info(
                f"Syncing product {sku}: "
                f"SupplierPrice={cost_price}, "
                f"RetailPrice={sale_price}, "
                f"Variants={len(variants)}, "
                f"Images={len(images)}"
            )
            ls_supplier_id = None
            if supplier_name:
                ls_supplier_id = await asyncio.to_thread(
                    self._get_or_create_supplier,
                    supplier_name
                )
            brand_name = (
                product.get("brand_name")
                or product.get("brand")
                or ""
            ).strip()
            ls_brand_id = None
            if brand_name:
                ls_brand_id = await asyncio.to_thread(
                    self._get_or_create_brand,
                    brand_name
                )
            logger.info(
                f"Lightspeed metadata for {sku}: "
                f"Supplier={supplier_name} (ID={ls_supplier_id}), "
                f"Brand={brand_name} (ID={ls_brand_id})"
            )
            existing_product_id = await asyncio.to_thread(self._find_product_by_sku, sku)

            if existing_product_id:
                logger.info(
                    f"Found existing Lightspeed product by SKU: "
                    f"{sku} -> {existing_product_id}"
                )
                ls_id = await self._update_existing_product(
                    product_id=existing_product_id,
                    product=product,
                    cost_price=cost_price,
                    sale_price=sale_price,
                    supplier_id=ls_supplier_id,
                    brand_id=ls_brand_id
                )
                created = False
            else:
                logger.info(
                    f"No existing Lightspeed product found for SKU {sku}. "
                    f"Attempting creation."
                )
                create_result = await self._create_product(
                    product,
                    variants,
                    cost_price,
                    sale_price,
                    ls_supplier_id,
                    ls_brand_id
                )
                if isinstance(create_result, dict):
                    if create_result.get("_existing_product_id"):
                        ls_id = create_result["_existing_product_id"]
                        created = False
                        logger.info(
                            f"Lightspeed product already existed. "
                            f"Using existing ID {ls_id}"
                        )
                        ls_id = await self._update_existing_product(
                            product_id=ls_id,
                            product=product,
                            cost_price=cost_price,
                            sale_price=sale_price,
                            supplier_id=ls_supplier_id,
                            brand_id=ls_brand_id
                        )
                    elif create_result.get("id"):
                        ls_id = create_result["id"]
                        created = True
                        self._product_sku_cache[sku.casefold()] = str(ls_id)
                    else:
                        ls_id = None
                        created = False
                else:
                    ls_id = create_result
                    created = bool(ls_id)
            if ls_id:
                self._product_sku_cache[sku.casefold()] = str(ls_id)
            if not ls_id:
                return {
                    "success": False,
                    "error": "Failed to get product ID from Lightspeed"
                }
            if variants and created:
                await self._sync_existing_variants(
                    product_id=ls_id,
                    supplier_variants=variants,
                    retail_price=sale_price,
                    product_name=product.get("product_name", ""),
                    supplier_id=ls_supplier_id,
                    enable_inventory_tracking=True
                )
            if created:
                activated = await asyncio.to_thread(
                    self._activate_online_store_product,
                    ls_id
                )

                if not activated:
                    logger.error(
                        f"Failed to activate POS + Online Store "
                        f"for Lightspeed product {ls_id}"
                    )
            if images and created:
                self._image_executor.submit(
                    self._upload_images,
                    ls_id,
                    images
                )

                logger.info(
                    f"Image sync queued for newly created "
                    f"Lightspeed product {ls_id}: "
                    f"{len(images)} images"
                )

            elif images:
                logger.info(
                    f"Skipping image upload for existing "
                    f"Lightspeed product {ls_id}"
                )
            return {
                "success": True,
                "lightspeed_id": str(ls_id),
                "created": created
            }
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            body = ""
            try:
                body = e.response.text[:500]
            except Exception:
                pass
            logger.error(
                f"Lightspeed API error {status}: {body}"
            )
            return {
                "success": False,
                "error": f"API error {status}: {body}"
            }
        except Exception as e:
            logger.error(
                f"Lightspeed push error: {e}",
                exc_info=True
            )
            return {
                "success": False,
                "error": str(e)
            }

    async def _get_markup_percentage(self) -> float:
        if self._markup_cache is not None:
            return self._markup_cache
        try:
            async with deps.pool.acquire() as conn:
                markup = await conn.fetchval("""
                    SELECT markup_percentage
                    FROM settings
                    WHERE id = 'system_settings'
                """)
            self._markup_cache = float(markup) if markup is not None else 0.0
            logger.info(f"Using configured markup percentage: {self._markup_cache}%")
            return self._markup_cache
        except Exception as e:
            logger.error(f"Failed to load markup percentage: {e}")
            self._markup_cache = 0.0
            return 0.0

    async def _sync_existing_variants(
        self,
        product_id: str,
        supplier_variants: list,
        retail_price: float,
        product_name: str = "",
        supplier_id: str = None,
        enable_inventory_tracking: bool = False
    ):
        """
        Sync SupplierHub variants to Lightspeed.

        For each variant:
        - Match Lightspeed variant by SKU
        - Use variant-specific retail price when available
        - Fall back to product retail price
        - Read inventory from SupplierHub
        - Enable inventory tracking at the Lightspeed product-family level
        - Update price and inventory for each Lightspeed variant
        """
        # Load markup configured in SupplierHub Settings
        markup_percentage = await self._get_markup_percentage()

        logger.info(
            f"Variant sync using markup: {markup_percentage}%"
        )

        try:
            # =========================================================
            # 1. GET PRODUCT NAME
            # =========================================================

            if not product_name:
                response = self._get(
                    f"products/{product_id}"
                )

                ls_product = response.get(
                    "data",
                    response
                )

                if isinstance(ls_product, dict):
                    product_name = (
                        ls_product.get("name")
                        or ls_product.get("product_name")
                        or ""
                    )

            if not product_name:
                logger.warning(
                    f"Unable to determine Lightspeed product name "
                    f"for {product_id}"
                )
                return

            logger.info(
                f"Loading Lightspeed variant family for "
                f"'{product_name}'"
            )

            # =========================================================
            # 2. GET ALL LIGHTSPEED FAMILY MEMBERS
            # =========================================================

            family_response = self._get(
                "products",
                params={
                    "name": product_name,
                    "page_size": 200
                }
            )

            family_items = family_response.get(
                "data",
                []
            )

            if isinstance(family_items, dict):
                family_items = (
                    family_items.get("products")
                    or family_items.get("data")
                    or family_items.get("items")
                    or []
                )

            if not isinstance(family_items, list):
                family_items = []

            if not family_items:
                logger.warning(
                    f"No Lightspeed family members found for "
                    f"'{product_name}'"
                )
                return

            logger.info(
                f"Found {len(family_items)} Lightspeed variants "
                f"for '{product_name}'"
            )

            # =========================================================
            # 3. BUILD LIGHTSPEED SKU -> PRODUCT MAP
            # =========================================================

            lightspeed_by_sku = {}

            for item in family_items:

                if not isinstance(item, dict):
                    continue

                ls_id = item.get("id")

                if not ls_id:
                    continue

                variant_sku = str(
                    item.get("sku")
                    or item.get("product_code")
                    or item.get("primary_sku_code")
                    or ""
                ).strip()

                if not variant_sku:
                    continue

                lightspeed_by_sku[
                    variant_sku.casefold()
                ] = item

            logger.info(
                f"Mapped {len(lightspeed_by_sku)} Lightspeed "
                f"variants by SKU"
            )

            # =========================================================
            # 4. RESOLVE LIGHTSPEED INVENTORY OUTLET
            # =========================================================

            outlet_id = self._get_inventory_outlet_id()

            if not outlet_id:
                logger.error(
                    "No Lightspeed inventory outlet could be resolved. "
                    "Inventory synchronization aborted."
                )
                return

            logger.info(
                f"Using Lightspeed inventory outlet: {outlet_id}"
            )

            # =========================================================
            # 5. BUILD SUPPLIERHUB SKU MAP
            # =========================================================

            supplier_by_sku = {}

            for variant in supplier_variants:

                if not isinstance(variant, dict):
                    continue

                sku = str(
                    variant.get("variant_sku")
                    or variant.get("sku")
                    or ""
                ).strip()

                sku = str(sku).strip()

                if not sku:
                    continue

                supplier_by_sku[
                    sku.casefold()
                ] = variant

            logger.info(
                f"Mapped {len(supplier_by_sku)} SupplierHub "
                f"variants by SKU"
            )

            # =========================================================
            # 6. ENABLE INVENTORY TRACKING
            #
            # IMPORTANT:
            # track_inventory is a COMMON / FAMILY-level field.
            # Do NOT put it inside "details".
            # =========================================================

            inventory_tracking_enabled = True

            if enable_inventory_tracking:

                enable_inventory_payload = {
                    "common": {
                        "track_inventory": True
                    }
                }

                logger.info(
                    f"Enabling inventory tracking for Lightspeed "
                    f"product family '{product_name}' "
                    f"(Product ID: {product_id})"
                )

                enable_result = self._put_legacy_21(
                    f"products/{product_id}",
                    enable_inventory_payload
                )

                inventory_tracking_enabled = not (
                    isinstance(enable_result, dict)
                    and enable_result.get("_lightspeed_validation_error")
                )

                if not inventory_tracking_enabled:
                    logger.error(
                        f"Failed to enable inventory tracking for "
                        f"Lightspeed product family "
                        f"'{product_name}' "
                        f"(ID: {product_id}): "
                        f"{enable_result}"
                    )
                else:
                    logger.info(
                        f"Inventory tracking enabled for "
                        f"Lightspeed product family "
                        f"'{product_name}'"
                    )

            # =========================================================
            # 7. BUILD VARIANT UPDATE TASKS
            # =========================================================
            tasks = []
            not_found = 0
            skipped = 0

            for source_sku, supplier_variant in supplier_by_sku.items():
                target = lightspeed_by_sku.get(source_sku)
                if not target:
                    not_found += 1
                    logger.warning(
                        f"Lightspeed variant not found for SupplierHub SKU "
                        f"{supplier_variant.get('variant_sku')}"
                    )
                    continue

                ls_variant_id = str(target.get("id") or "").strip()
                if not ls_variant_id:
                    not_found += 1
                    continue

                inventory = (
                    supplier_variant.get("inventory")
                    or supplier_variant.get("inventory_count")
                    or supplier_variant.get("quantity")
                    or supplier_variant.get("stock")
                    or 0
                )

                try:
                    inventory = max(0, int(float(inventory)))
                except (TypeError, ValueError):
                    inventory = 0

                supplier_variant_price = float(
                    supplier_variant.get("price")
                    or supplier_variant.get("supplier_price")
                    or supplier_variant.get("cost_price")
                    or 0
                )

                variant_price = round(
                    supplier_variant_price * (1 + markup_percentage / 100),
                    2
                )

                try:
                    variant_price = float(variant_price)
                except (TypeError, ValueError):
                    variant_price = float(retail_price)

                variant_sku = str(
                    supplier_variant.get("variant_sku")
                    or supplier_variant.get("sku")
                    or ""
                ).strip()

                if not variant_sku:
                    skipped += 1
                    continue

                update_payload = {
                    "details": {
                        "price_excluding_tax": variant_price,
                        "is_active": True,
                        "inventory": [
                            {
                                "outlet_id": str(outlet_id),
                                "current_amount": inventory,
                                "reorder_amount": 0,
                                "reorder_point": 0
                            }
                        ]
                    }
                }

                if supplier_id:
                    update_payload["details"]["product_suppliers"] = [
                        {
                            "supplier_id": str(supplier_id),
                            "code": variant_sku,
                            "price": supplier_variant_price
                        }
                    ]

                tasks.append(
                    self._sync_single_variant(
                        ls_variant_id,
                        variant_sku,
                        update_payload
                    )
                )

            # =========================================================
            # 8. EXECUTE VARIANT UPDATES CONCURRENTLY
            # =========================================================
            results = await asyncio.gather(*tasks, return_exceptions=True)

            synced = 0
            failed = 0

            for result in results:
                if isinstance(result, Exception):
                    failed += 1
                    logger.error(
                        f"Unexpected variant synchronization error: {result}",
                        exc_info=True
                    )
                    continue

                if result.get("success"):
                    synced += 1
                else:
                    failed += 1
                    logger.error(
                        f"Variant synchronization failed for "
                        f"{result.get('sku')}: {result.get('error')}"
                    )

            logger.info(
                f"Concurrent variant synchronization completed for "
                f"'{product_name}': "
                f"Synced={synced}, "
                f"NotFound={not_found}, "
                f"Skipped={skipped}, "
                f"Failed={failed}, "
                f"TotalSupplierVariants={len(supplier_by_sku)}, "
                f"InventoryTrackingEnabled={inventory_tracking_enabled}"
            )

        except Exception as e:

            logger.error(
                f"Variant synchronization failed for "
                f"{product_id}: {e}",
                exc_info=True
            )

    async def _sync_single_variant(self, ls_variant_id: str, variant_sku: str, update_payload: dict):
        async with self._variant_sync_semaphore:
            try:
                result = await asyncio.to_thread(
                    self._put_legacy_21,
                    f"products/{ls_variant_id}",
                    update_payload
                )
                if (
                    isinstance(result, dict)
                    and result.get("_lightspeed_validation_error")
                ):
                    return {
                        "success": False,
                        "sku": variant_sku,
                        "error": result
                    }
                return {
                    "success": True,
                    "sku": variant_sku,
                    "result": result
                }
            except Exception as e:
                logger.error(
                    f"Variant update failed for {variant_sku}: {e}",
                    exc_info=True
                )
                return {
                    "success": False,
                    "sku": variant_sku,
                    "error": str(e)
                }

    def _get_inventory_outlet_id(self):
        configured_id = os.getenv("LIGHTSPEED_OUTLET_ID", "").strip()
        if configured_id:
            return configured_id
        if self._outlet_id_cache:
            return self._outlet_id_cache
        outlet_name = os.getenv("LIGHTSPEED_OUTLET_NAME", "Red Leafs Sports - Mississauga").strip()
        try:
            response = self._get("outlets", params={"name": outlet_name, "limit": 100})
            items = response.get("data", [])
            if isinstance(items, dict):
                items = items.get("outlets") or items.get("data") or []
            for outlet in items if isinstance(items, list) else []:
                if str(outlet.get("name", "")).strip().casefold() == outlet_name.casefold():
                    outlet_id = outlet.get("id")
                    if outlet_id:
                        self._outlet_id_cache = str(outlet_id)
                        logger.info(f"Using Lightspeed outlet '{outlet_name}' ({outlet_id})")
                        return self._outlet_id_cache
            logger.warning(f"Lightspeed outlet '{outlet_name}' was not found")
        except Exception as e:
            logger.error(f"Failed to resolve Lightspeed outlet '{outlet_name}': {e}")
        return None

    async def _update_existing_product(
        self,
        product_id: str,
        product: dict,
        cost_price: float,
        sale_price: float,
        supplier_id: str = None,
        brand_id: str = None
    ) -> str:
        """
        Efficiently synchronize an existing Lightspeed product.

        Existing product sync:
        - Update variant prices
        - Update supplier costs
        - Update inventory
        - Enable inventory tracking
        - Keep product available in POS + Online Store

        Images are skipped for existing products.
        """

        try:
            product_name = str(
                product.get("product_name") or ""
            ).strip()

            variants = product.get("variants") or []

            logger.info(
                f"Updating existing Lightspeed product "
                f"'{product_name}' (ID: {product_id})"
            )

            # Sync existing variants:
            # prices, supplier costs and inventory
            if variants:
                await self._sync_existing_variants(
                    product_id=product_id,
                    supplier_variants=variants,
                    retail_price=sale_price,
                    product_name=product_name,
                    supplier_id=supplier_id
                )

            logger.info(
                f"Existing Lightspeed product synchronization completed "
                f"for '{product_name}'"
            )

            return product_id

        except Exception as e:
            logger.error(
                f"Lightspeed existing product sync failed "
                f"(ID: {product_id}): {e}",
                exc_info=True
            )

            return product_id

    async def _create_product(self, product: dict, variants: list, cost_price: float, sale_price: float, supplier_id: str = None, brand_id: str = None) -> str:
        """Create a product, handling Lightspeed duplicate-product responses."""
        product_name = product.get("product_name", "")
        description = product.get("description", "") or ""
        sku = product.get("supplier_sku", "")
        category_id = product.get("category_id")
        attr_names = set()
        markup_percentage = await self._get_markup_percentage()
        for v in variants:
            if v.get("color"):
                attr_names.add("Color")
            if v.get("size"):
                attr_names.add("Size")
        if variants and len(variants) > 1 and attr_names:
            attr_map = self._ensure_variant_attributes(
                list(attr_names)
            )
            if not attr_map:
                logger.warning(
                    "No variant attributes, creating simple product"
                )
                return self._create_simple_product(
                    product_name,
                    description,
                    sku,
                    cost_price,
                    sale_price,
                    category_id,
                    supplier_id,
                    brand_id
                )
            variant_list = []
            for v in variants:
                definitions = []
                color = v.get("color", "")
                size = v.get("size", "")
                if color and "Color" in attr_map:
                    definitions.append({
                        "attribute_id": attr_map["Color"],
                        "value": color
                    })
                if size and "Size" in attr_map:
                    definitions.append({
                        "attribute_id": attr_map["Size"],
                        "value": size
                    })
                if not definitions:
                    continue
                v_sku = str(
                    v.get("variant_sku")
                    or v.get("sku")
                    or ""
                ).strip()

                if not v_sku:
                    logger.error(
                        f"Skipping variant for '{product_name}': missing variant SKU"
                    )
                    continue
                supplier_variant_price = float(
                    v.get("price")
                    or v.get("supplier_price")
                    or v.get("cost_price")
                    or 0
                )

                v_price = round(
                    supplier_variant_price * (1 + markup_percentage / 100),
                    2
                )

                try:
                    v_price = float(v_price)
                except (TypeError, ValueError):
                    v_price = float(sale_price)
                variant_payload = {
                    "sku": v_sku,
                    "price_excluding_tax": v_price,
                    "is_active": True,
                    "product_suppliers": (
                        [
                            {
                                "supplier_id": str(supplier_id),
                                "code": v_sku,
                                "price": float(supplier_variant_price)
                            }
                        ]
                        if supplier_id
                        else []
                    ),
                    "variant_definitions": definitions
                }

                # Add the main SupplierHub product SKU as an additional
                # searchable product code on the first variant.
                if len(variant_list) == 0 and sku:
                    variant_payload["product_codes"] = [
                        {
                            "code": sku,
                            "type": "CUSTOM"
                        }
                    ]

                variant_list.append(variant_payload)
            if not variant_list:
                return self._create_simple_product(
                    product_name,
                    description,
                    sku,
                    cost_price,
                    sale_price,
                    category_id,
                    supplier_id,
                    brand_id
                )
            payload = {
                "name": product_name,
                "description": description,
                "sku": sku,
                "supply_price": cost_price,
                "price_excluding_tax": sale_price,
                "status": "ACTIVE",
                "has_inventory": True,
                "is_active": True,
                "variants": variant_list
            }
            if category_id:
                payload["product_category_id"] = str(
                    category_id
                )

            if supplier_id:
                payload["supplier_id"] = str(
                    supplier_id
                )

            if brand_id:
                payload["brand_id"] = str(
                    brand_id
                )

            response = self._post(
                "products",
                payload
            )
            if response.get(
                "_lightspeed_validation_error"
            ):
                return self._handle_existing_product_error(
                    response,
                    product_name,
                    sku
                )
            return self._extract_product_id(
                response,
                product_name
            )
        return self._create_simple_product(
            product_name,
            description,
            sku,
            cost_price,
            sale_price,
            category_id,
            supplier_id,
            brand_id
        )

    def _handle_existing_product_error(
        self,
        response: dict,
        product_name: str,
        sku: str
    ):
        """Extract existing Lightspeed product ID from a 422 duplicate response."""
        fields = response.get("fields", {}) or {}
        existing_id = (
            fields.get("name_existing_id")
            or fields.get("sku_existing_id")
        )
        if existing_id:
            logger.info(
                f"Product '{product_name}' "
                f"(SKU: {sku}) already exists in Lightspeed. "
                f"Using existing ID: {existing_id}"
            )
            return {
                "_existing_product_id": existing_id
            }
        logger.error(
            f"Lightspeed validation error for '{product_name}': "
            f"{response}"
        )
        return {
            "error": str(response)
        }

    def _create_simple_product(
        self,
        name,
        description,
        sku,
        cost_price,
        sale_price,
        category_id,
        supplier_id=None,
        brand_id=None
    ):
        """Create a simple product without variants."""
        payload = {
            "name": name,
            "description": description,
            "sku": sku,
            "supply_price": cost_price,
            "price_excluding_tax": sale_price,
            "status": "ACTIVE",
            "is_active": True
        }
        if category_id:
            payload["product_category_id"] = str(
                category_id
            )
        if brand_id:
            payload["brand_id"] = str(brand_id)
        if supplier_id:
            payload["supplier_id"] = supplier_id
        response = self._post(
            "products",
            payload
        )
        if response.get(
            "_lightspeed_validation_error"
        ):
            return self._handle_existing_product_error(
                response,
                name,
                sku
            )
        return self._extract_product_id(
            response,
            name
        )

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
        """Find a Lightspeed product by SKU or product code."""

        sku = str(sku or "").strip()

        if not sku:
            return None

        try:
            logger.info(
                f"Searching Lightspeed for product SKU: {sku}"
            )

            response = self._get(
                "products",
                params={
                    "sku": sku,
                    "limit": 100
                }
            )

            if not isinstance(response, dict):
                logger.warning(
                    f"Invalid Lightspeed SKU search response "
                    f"for {sku}"
                )
                return None

            data = response.get("data")

            # Convert a single product object into a list
            if isinstance(data, dict):

                # Direct product response
                if data.get("id"):
                    items = [data]

                # Nested collection response
                else:
                    items = (
                        data.get("products")
                        or data.get("items")
                        or data.get("data")
                        or []
                    )

            elif isinstance(data, list):
                items = data

            else:
                items = []

            if not isinstance(items, list):
                items = []

            logger.info(
                f"Lightspeed SKU search returned "
                f"{len(items)} result(s) for {sku}"
            )

            for item in items:

                if not isinstance(item, dict):
                    continue

                product_id = item.get("id")

                if not product_id:
                    continue

                # Check primary SKU
                primary_sku = str(
                    item.get("sku") or ""
                ).strip()

                if primary_sku.casefold() == sku.casefold():

                    logger.info(
                        f"Found Lightspeed product by primary SKU "
                        f"{sku} -> {product_id}"
                    )

                    return str(product_id)

                # Check additional product codes
                product_codes = (
                    item.get("product_codes")
                    or []
                )

                for code_data in product_codes:

                    if not isinstance(code_data, dict):
                        continue

                    product_code = str(
                        code_data.get("code") or ""
                    ).strip()

                    if product_code.casefold() == sku.casefold():

                        logger.info(
                            f"Found Lightspeed product by product code "
                            f"{sku} -> {product_id}"
                        )

                        return str(product_id)

            logger.info(
                f"No exact Lightspeed product found for SKU {sku}"
            )

        except Exception as e:

            logger.warning(
                f"Failed to find Lightspeed product "
                f"by SKU {sku}: {e}",
                exc_info=True
            )

        return None

    def _upload_images(self, product_id: str, images: list):
        """Upload product images concurrently with reliable error handling."""

        if not images:
            return {
                "uploaded": 0,
                "failed": 0,
                "total": 0
            }

        total = len(images)

        logger.info(
            f"Starting concurrent background image sync for "
            f"product {product_id}: {total} images"
        )

        def upload_single_image(index: int, img: dict):
            """Download and upload one image."""

            try:
                if not isinstance(img, dict):
                    return {
                        "success": False,
                        "index": index,
                        "filename": "",
                        "error": "Invalid image object"
                    }

                img_url = str(
                    img.get("url") or ""
                ).strip()

                img_path = str(
                    img.get("local_path") or ""
                ).strip()

                img_base64 = img.get("image_base64")

                image_bytes = None
                filename = f"product_{product_id}_img_{index}.jpg"
                content_type = "image/jpeg"

                # 1. LOCAL FILE

                if img_path and os.path.exists(img_path):

                    try:
                        with open(img_path, "rb") as f:
                            image_bytes = f.read()

                        filename = os.path.basename(img_path)

                    except Exception as e:

                        logger.warning(
                            f"Could not read image #{index}: {e}"
                        )
                # 2. BASE64 IMAGE

                elif img_base64:

                    try:
                        raw = img_base64

                        if isinstance(raw, bytes):
                            image_bytes = raw

                        else:
                            raw = str(raw)

                            if raw.startswith("data:") and "," in raw:
                                raw = raw.split(",", 1)[1]

                            image_bytes = base64.b64decode(
                                raw.strip(),
                                validate=False
                            )

                    except Exception as e:

                        logger.warning(
                            f"Could not decode image #{index}: {e}"
                        )

                # 3. REMOTE URL

                elif img_url:

                    try:
                        resp = requests.get(
                            img_url,
                            timeout=30,
                            headers={
                                "User-Agent": "Mozilla/5.0"
                            }
                        )

                        if (
                            resp.status_code == 200
                            and len(resp.content) > 1000
                        ):

                            image_bytes = resp.content

                            response_type = (
                                resp.headers
                                .get("content-type", "")
                                .lower()
                            )

                            if response_type.startswith("image/"):
                                content_type = response_type

                            filename_from_url = (
                                img_url
                                .split("?")[0]
                                .rstrip("/")
                                .split("/")[-1]
                            )

                            if "." in filename_from_url:
                                filename = filename_from_url

                        else:

                            return {
                                "success": False,
                                "index": index,
                                "filename": filename,
                                "error": (
                                    f"Image download returned "
                                    f"HTTP {resp.status_code}"
                                )
                            }

                    except Exception as e:

                        return {
                            "success": False,
                            "index": index,
                            "filename": filename,
                            "error": f"Image download failed: {e}"
                        }

                # 4. VALIDATE IMAGE DATA

                if not image_bytes:

                    return {
                        "success": False,
                        "index": index,
                        "filename": filename,
                        "error": "No usable image data"
                    }

                # 5. UPLOAD TO LIGHTSPEED
                result = self._upload(
                    f"products/{product_id}/actions/image_upload",
                    image_bytes,
                    filename,
                    content_type
                )

                if (
                    isinstance(result, dict)
                    and result.get("_lightspeed_validation_error")
                ):

                    return {
                        "success": False,
                        "index": index,
                        "filename": filename,
                        "error": result
                    }

                return {
                    "success": True,
                    "index": index,
                    "filename": filename
                }

            except Exception as e:

                logger.warning(
                    f"Image upload failed #{index}/{total} "
                    f"for product {product_id}: {e}"
                )

                return {
                    "success": False,
                    "index": index,
                    "filename": "",
                    "error": str(e)
                }

        # ================================================================
        # RUN IMAGE UPLOADS CONCURRENTLY
        # ================================================================

        uploaded = 0
        failed = 0

        # Use the existing image executor.
        # It should be configured with max_workers=5.
        futures = []

        for index, img in enumerate(images, start=1):

            future = self._image_executor.submit(
                upload_single_image,
                index,
                img
            )

            futures.append(future)

        # ================================================================
        # COLLECT RESULTS
        # ================================================================

        for future in as_completed(futures):

            try:
                result = future.result()

                index = result.get("index")
                filename = result.get("filename", "")

                if result.get("success"):

                    uploaded += 1

                    logger.info(
                        f"Uploaded image #{index}/{total} "
                        f"for product {product_id}: {filename} "
                        f"({uploaded}/{total} completed)"
                    )

                else:

                    failed += 1

                    logger.warning(
                        f"Image #{index}/{total} failed for "
                        f"product {product_id}: "
                        f"{result.get('error')}"
                    )

            except Exception as e:

                failed += 1

                logger.warning(
                    f"Image worker failed for product "
                    f"{product_id}: {e}",
                    exc_info=True
                )

        # ================================================================
        # FINAL RESULT
        # ================================================================

        logger.info(
            f"Concurrent image sync completed for "
            f"product {product_id}: "
            f"Uploaded={uploaded}, "
            f"Failed={failed}, "
            f"Total={total}"
        )

        return {
            "uploaded": uploaded,
            "failed": failed,
            "total": total
        }

    # ==================== INVENTORY ====================
    def update_product_inventory(self, product_id: str, outlet_id: str, count: int):
        if self.mock_mode:
            return {'success': False, 'error': 'Not configured'}
        try:
            self._put(
                f"products/{product_id}",
                {
                    "has_inventory": True,
                    "inventory": [
                        {
                            "outlet_id": outlet_id,
                            "count": int(count)
                        }
                    ]
                }
            )
            logger.info(
    "LIGHTSPEED OUTLETS: %s",
    [
        {
            "id": o.get("id"),
            "name": o.get("name")
        }
        for o in self._get_outlets()
    ]
)
            return {
                'success': True,
                'product_id': product_id,
                'outlet_id': outlet_id,
                'count': int(count)
            }
        except Exception as e:
            logger.error(
                f"Inventory update failed for "
                f"{product_id}: {e}"
            )
            return {
                'success': False,
                'error': str(e)
            }

    def _activate_online_store_product(self, product_id: str) -> bool:
        """
        Automatically enable the product for:
        - Lightspeed POS / In-Store
        - Lightspeed eCom / Online Store
        """

        if not product_id:
            return False

        try:
            logger.info(
                f"Enabling POS + Online Store for Lightspeed product "
                f"{product_id}"
            )

            payload = {
                "active": {
                    "in_store": True,
                    "ecwid": True
                }
            }

            result = self._patch_2026_10(
                f"products/{product_id}",
                payload
            )

            if (
                isinstance(result, dict)
                and result.get("_lightspeed_validation_error")
            ):
                logger.error(
                    f"Failed to enable POS + Online Store for "
                    f"product {product_id}: {result}"
                )
                return False

            logger.info(
                f"POS + Online Store enabled successfully "
                f"for product {product_id}"
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to activate POS + Online Store for "
                f"product {product_id}: {e}",
                exc_info=True
            )
            return False