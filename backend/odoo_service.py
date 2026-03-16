import logging
import xmlrpc.client

logger = logging.getLogger(__name__)


class OdooService:
    """Odoo ERP integration via XML-RPC. Mock mode when no credentials."""

    def __init__(self, url: str = '', db_name: str = '', username: str = '', api_key: str = ''):
        self.url = url or ''
        self.db_name = db_name or ''
        self.username = username or ''
        self.api_key = api_key or ''
        self.uid = None
        self.mock_mode = not all([self.url, self.db_name, self.username, self.api_key])
        if self.mock_mode:
            logger.info("Odoo connector: MOCK mode (no credentials)")

    def test_connection(self) -> dict:
        if self.mock_mode:
            return {
                'success': False,
                'connected': False,
                'message': 'Odoo not configured. Set URL, database, username, and API key in Settings.',
                'mock_mode': True
            }
        try:
            # Ensure URL doesn't have trailing slash
            url = self.url.rstrip('/')
            
            logger.info(f"Testing Odoo connection to {url}, db={self.db_name}, user={self.username}")
            
            common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
            
            # Get version first to verify connectivity
            try:
                version = common.version()
                logger.info(f"Odoo version: {version}")
            except Exception as e:
                return {
                    'success': False,
                    'connected': False, 
                    'message': f'Cannot reach Odoo server at {url}. Error: {str(e)}',
                    'mock_mode': False
                }
            
            # Try authentication - Odoo accepts password OR API key in this field
            uid = common.authenticate(self.db_name, self.username, self.api_key, {})
            
            logger.info(f"Authentication result: uid={uid}")
            
            if uid:
                self.uid = uid
                return {
                    'success': True,
                    'connected': True,
                    'message': f'Connected to Odoo {version.get("server_version", "?")}',
                    'mock_mode': False
                }
            
            # Authentication failed - provide helpful message
            return {
                'success': False, 
                'connected': False, 
                'message': f'Authentication failed. Please verify: 1) Username is your login email (not "Administrator"), 2) Use your Odoo password or API key, 3) Database name "{self.db_name}" is correct',
                'mock_mode': False
            }
            
        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo XML-RPC fault: {e.faultCode} - {e.faultString}")
            return {'success': False, 'connected': False, 'message': f'Odoo error: {e.faultString}', 'mock_mode': False}
        except Exception as e:
            logger.error(f"Odoo connection error: {str(e)}")
            return {'success': False, 'connected': False, 'message': f'Connection failed: {str(e)}', 'mock_mode': False}

    def create_or_update_product(self, product: dict) -> dict:
        """Create or update a product in Odoo with full details including variants, images, and categories."""
        if self.mock_mode:
            import random
            mock_id = random.randint(1000, 9999)
            logger.info(f"[MOCK] Pushed '{product.get('product_name')}' -> Odoo ID mock_{mock_id}")
            return {'success': True, 'odoo_id': f'mock_{mock_id}', 'created': True, 'mock_mode': True}

        try:
            if not self.uid:
                conn = self.test_connection()
                if not conn.get('connected'):
                    return {'success': False, 'error': 'Cannot connect to Odoo'}

            url = self.url.rstrip('/')
            models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
            
            sku = product.get('supplier_sku', '')
            
            # Search for existing product by SKU
            existing = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.template', 'search_read',
                [[['default_code', '=', sku]]],
                {'fields': ['id'], 'limit': 1}
            )
            
            # Get or create the default inventory category "SanMar Apparel"
            default_category_name = product.get('default_category', 'SanMar Apparel')
            categ_id = self._get_or_create_category(models, default_category_name)
            
            # Get e-commerce category if mapped
            ecommerce_categ_id = product.get('category_id')  # This is the mapped Odoo e-commerce category ID
            
            # Prepare product values
            vals = {
                'name': product.get('product_name', ''),
                'default_code': sku,
                'description': product.get('description', ''),  # Internal description
                'description_sale': product.get('description', ''),  # Sales description (shown to customers)
                'list_price': float(product.get('base_price', 0) or 0),  # Sale price
                'standard_price': float(product.get('cost_price', 0) or 0),  # Cost price
                'type': 'product',  # Storable product
                'sale_ok': True,
                'purchase_ok': True,
                'invoice_policy': 'order',  # Invoice on ordered quantities
                'is_published': True,  # Publish on website
            }
            
            # Add inventory category
            if categ_id:
                vals['categ_id'] = categ_id
            
            # Add e-commerce category
            if ecommerce_categ_id:
                vals['public_categ_ids'] = [(6, 0, [ecommerce_categ_id])]  # Replace with this category
            
            if existing:
                # Update existing product
                odoo_id = existing[0]['id']
                models.execute_kw(self.db_name, self.uid, self.api_key, 'product.template', 'write', [[odoo_id], vals])
                logger.info(f"Updated product {sku} (Odoo ID: {odoo_id})")
            else:
                # Create new product
                odoo_id = models.execute_kw(self.db_name, self.uid, self.api_key, 'product.template', 'create', [vals])
                logger.info(f"Created product {sku} (Odoo ID: {odoo_id})")
            
            # Handle variants if provided
            variants = product.get('variants', [])
            if variants:
                self._sync_variants(models, odoo_id, variants)
            
            # Handle images if provided
            images = product.get('images', [])
            if images:
                self._sync_images(models, odoo_id, images)
            
            return {'success': True, 'odoo_id': str(odoo_id), 'created': not existing}
                
        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo API error: {e.faultString}")
            return {'success': False, 'error': f'Odoo API error: {e.faultString}'}
        except Exception as e:
            logger.error(f"Odoo push error: {e}")
            return {'success': False, 'error': str(e)}

    def _get_or_create_category(self, models, category_name: str) -> int:
        """Get or create an inventory product category."""
        try:
            # Search for existing category
            existing = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.category', 'search_read',
                [[['name', '=', category_name]]],
                {'fields': ['id'], 'limit': 1}
            )
            
            if existing:
                return existing[0]['id']
            
            # Create new category
            categ_id = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.category', 'create',
                [{'name': category_name}]
            )
            logger.info(f"Created product category '{category_name}' (ID: {categ_id})")
            return categ_id
            
        except Exception as e:
            logger.error(f"Error getting/creating category: {e}")
            return None

    def _get_or_create_attribute(self, models, attr_name: str) -> int:
        """Get or create a product attribute (e.g., Color, Size)."""
        try:
            existing = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.attribute', 'search_read',
                [[['name', '=', attr_name]]],
                {'fields': ['id'], 'limit': 1}
            )
            
            if existing:
                return existing[0]['id']
            
            attr_id = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.attribute', 'create',
                [{'name': attr_name, 'create_variant': 'always'}]
            )
            logger.info(f"Created attribute '{attr_name}' (ID: {attr_id})")
            return attr_id
            
        except Exception as e:
            logger.error(f"Error getting/creating attribute: {e}")
            return None

    def _get_or_create_attribute_value(self, models, attr_id: int, value_name: str) -> int:
        """Get or create an attribute value."""
        try:
            if not value_name:
                return None
                
            existing = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.attribute.value', 'search_read',
                [[['attribute_id', '=', attr_id], ['name', '=', value_name]]],
                {'fields': ['id'], 'limit': 1}
            )
            
            if existing:
                return existing[0]['id']
            
            value_id = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.attribute.value', 'create',
                [{'attribute_id': attr_id, 'name': value_name}]
            )
            return value_id
            
        except Exception as e:
            logger.error(f"Error getting/creating attribute value: {e}")
            return None

    def _sync_variants(self, models, template_id: int, variants: list):
        """Sync product variants with attributes (Size, Color)."""
        try:
            if not variants:
                return
            
            # Get or create Size and Color attributes
            size_attr_id = self._get_or_create_attribute(models, 'Size')
            color_attr_id = self._get_or_create_attribute(models, 'Color')
            
            # Collect unique sizes and colors
            sizes = set()
            colors = set()
            for v in variants:
                if v.get('size'):
                    sizes.add(v['size'])
                if v.get('color'):
                    colors.add(v['color'])
            
            # Create attribute values
            size_value_ids = {}
            color_value_ids = {}
            
            for size in sizes:
                val_id = self._get_or_create_attribute_value(models, size_attr_id, size)
                if val_id:
                    size_value_ids[size] = val_id
            
            for color in colors:
                val_id = self._get_or_create_attribute_value(models, color_attr_id, color)
                if val_id:
                    color_value_ids[color] = val_id
            
            # Add attribute lines to product template
            # First, check existing attribute lines
            existing_lines = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.template.attribute.line', 'search_read',
                [[['product_tmpl_id', '=', template_id]]],
                {'fields': ['id', 'attribute_id']}
            )
            existing_attr_ids = [line['attribute_id'][0] for line in existing_lines]
            
            # Add Size attribute line if has sizes and not already added
            if sizes and size_attr_id not in existing_attr_ids:
                models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'product.template.attribute.line', 'create',
                    [{
                        'product_tmpl_id': template_id,
                        'attribute_id': size_attr_id,
                        'value_ids': [(6, 0, list(size_value_ids.values()))]
                    }]
                )
            
            # Add Color attribute line if has colors and not already added
            if colors and color_attr_id not in existing_attr_ids:
                models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'product.template.attribute.line', 'create',
                    [{
                        'product_tmpl_id': template_id,
                        'attribute_id': color_attr_id,
                        'value_ids': [(6, 0, list(color_value_ids.values()))]
                    }]
                )
            
            # Update variant SKUs and inventory
            # Get all product variants for this template
            product_variants = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.product', 'search_read',
                [[['product_tmpl_id', '=', template_id]]],
                {'fields': ['id', 'product_template_attribute_value_ids', 'default_code']}
            )
            
            # Map variants by their attribute combination
            for variant in variants:
                variant_sku = variant.get('variant_sku', '')
                variant_color = variant.get('color', '')
                variant_size = variant.get('size', '')
                variant_qty = variant.get('inventory', 0) or variant.get('inventory_quantity', 0)
                
                # Find matching Odoo variant (this is complex - simplified approach: update by SKU if exists)
                for pv in product_variants:
                    if not pv.get('default_code'):
                        # Set SKU on first available variant
                        models.execute_kw(
                            self.db_name, self.uid, self.api_key,
                            'product.product', 'write',
                            [[pv['id']], {'default_code': variant_sku}]
                        )
                        break
            
            logger.info(f"Synced {len(variants)} variants for template {template_id}")
            
        except Exception as e:
            logger.error(f"Error syncing variants: {e}")

    def _sync_images(self, models, template_id: int, images: list):
        """Sync product images to Odoo."""
        import base64
        import requests
        
        try:
            if not images:
                return
            
            for i, img in enumerate(images):
                img_url = img.get('url', '')
                if not img_url:
                    continue
                
                try:
                    # Download image
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'image/*,*/*;q=0.8',
                    }
                    response = requests.get(img_url, headers=headers, timeout=30)
                    
                    if response.status_code == 200 and 'image' in response.headers.get('content-type', ''):
                        img_base64 = base64.b64encode(response.content).decode('utf-8')
                        
                        if i == 0:
                            # First image is the main product image
                            models.execute_kw(
                                self.db_name, self.uid, self.api_key,
                                'product.template', 'write',
                                [[template_id], {'image_1920': img_base64}]
                            )
                            logger.info(f"Set main image for template {template_id}")
                        else:
                            # Additional images go to product.image
                            try:
                                models.execute_kw(
                                    self.db_name, self.uid, self.api_key,
                                    'product.image', 'create',
                                    [{
                                        'product_tmpl_id': template_id,
                                        'name': f'Image {i+1}',
                                        'image_1920': img_base64,
                                    }]
                                )
                            except Exception as img_err:
                                logger.warning(f"Could not add extra image: {img_err}")
                    else:
                        logger.warning(f"Failed to download image {img_url}: HTTP {response.status_code}")
                        
                except requests.RequestException as e:
                    logger.warning(f"Error downloading image {img_url}: {e}")
                    continue
            
            logger.info(f"Synced {len(images)} images for template {template_id}")
            
        except Exception as e:
            logger.error(f"Error syncing images: {e}")

    def get_ecommerce_categories(self) -> dict:
        """Fetch all e-commerce product categories from Odoo."""
        if self.mock_mode:
            return {
                'success': False,
                'error': 'Odoo not configured',
                'categories': []
            }
        
        try:
            if not self.uid:
                conn = self.test_connection()
                if not conn.get('connected'):
                    return {'success': False, 'error': 'Cannot connect to Odoo', 'categories': []}
            
            models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            
            # Fetch public categories (e-commerce categories)
            # Try 'product.public.category' first (Odoo e-commerce module)
            try:
                categories = models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'product.public.category', 'search_read',
                    [[]],
                    {'fields': ['id', 'name', 'parent_id', 'sequence']}
                )
                logger.info(f"Fetched {len(categories)} e-commerce categories from Odoo")
            except xmlrpc.client.Fault as e:
                # Fallback to product.category if e-commerce module not installed
                logger.warning(f"product.public.category not found, trying product.category: {e.faultString}")
                categories = models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'product.category', 'search_read',
                    [[]],
                    {'fields': ['id', 'name', 'parent_id']}
                )
                logger.info(f"Fetched {len(categories)} product categories from Odoo")
            
            # Process categories to extract parent names
            cat_dict = {c['id']: c for c in categories}
            result = []
            for cat in categories:
                parent_name = None
                parent_id = None
                if cat.get('parent_id'):
                    parent_id = cat['parent_id'][0] if isinstance(cat['parent_id'], (list, tuple)) else cat['parent_id']
                    parent_name = cat['parent_id'][1] if isinstance(cat['parent_id'], (list, tuple)) else cat_dict.get(parent_id, {}).get('name')
                
                result.append({
                    'odoo_category_id': cat['id'],
                    'category_name': cat['name'],
                    'parent_id': parent_id,
                    'parent_category': parent_name
                })
            
            return {'success': True, 'categories': result}
            
        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo API error fetching categories: {e.faultString}")
            return {'success': False, 'error': f'Odoo API error: {e.faultString}', 'categories': []}
        except Exception as e:
            logger.error(f"Error fetching Odoo categories: {e}")
            return {'success': False, 'error': str(e), 'categories': []}

