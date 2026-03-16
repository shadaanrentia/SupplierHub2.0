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
            cost_price = float(product.get('cost_price', 0) or 0)
            sale_price = float(product.get('base_price', 0) or 0)
            
            logger.info(f"Syncing product {sku}: Cost={cost_price}, Sale={sale_price}")
            
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
                'list_price': sale_price,  # Sale price
                'standard_price': cost_price,  # Cost price
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
            
            # Handle variants if provided (creates the variant combinations)
            variants = product.get('variants', [])
            if variants:
                self._sync_variants(models, odoo_id, variants)
            
            # Update cost price on product variants AFTER they've been created
            # This is more reliable in Odoo 16+ where standard_price on template may not propagate
            if cost_price > 0:
                self._update_variant_costs(models, odoo_id, cost_price)
            
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

    def _update_variant_costs(self, models, template_id: int, cost_price: float):
        """Update cost price on all product variants (product.product records)."""
        try:
            # Get all variants for this template
            variants = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.product', 'search',
                [[['product_tmpl_id', '=', template_id]]]
            )
            
            if variants:
                # Update standard_price on all variants
                models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'product.product', 'write',
                    [variants, {'standard_price': cost_price}]
                )
                logger.info(f"Updated cost price to {cost_price} for {len(variants)} variants of template {template_id}")
        except Exception as e:
            logger.warning(f"Error updating variant costs: {e}")

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
        """Sync product variants with attributes (Size, Color) and inventory."""
        try:
            if not variants:
                logger.info(f"No variants to sync for template {template_id}")
                return
            
            logger.info(f"Syncing {len(variants)} variants for template {template_id}")
            
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
            
            logger.info(f"Found {len(sizes)} unique sizes and {len(colors)} unique colors")
            
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
                logger.info(f"Added Size attribute line with {len(sizes)} values")
            
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
                logger.info(f"Added Color attribute line with {len(colors)} values")
            
            # Get all product variants for this template
            product_variants = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.product', 'search_read',
                [[['product_tmpl_id', '=', template_id]]],
                {'fields': ['id', 'product_template_attribute_value_ids', 'default_code']}
            )
            
            logger.info(f"Found {len(product_variants)} Odoo variants for template {template_id}")
            
            # Get default warehouse/location for inventory
            warehouse = self._get_default_warehouse(models)
            stock_location_id = warehouse.get('lot_stock_id', [False, ''])[0] if warehouse else False
            
            if not stock_location_id:
                logger.warning("No stock location found - inventory will not be updated")
            else:
                logger.info(f"Using stock location ID: {stock_location_id}")
            
            # Calculate total inventory from variants
            total_inventory = 0
            inventory_updated = 0
            
            # Map and update variants with SKU and inventory
            for variant in variants:
                variant_sku = variant.get('variant_sku', '')
                # Get inventory from multiple possible field names
                variant_qty = int(variant.get('inventory', 0) or variant.get('inventory_quantity', 0) or 0)
                total_inventory += variant_qty
                
                # Try to find or assign variant
                for pv in product_variants:
                    if pv.get('default_code') == variant_sku:
                        # Found matching variant, update inventory
                        if stock_location_id:
                            self._update_inventory(models, pv['id'], stock_location_id, variant_qty)
                            inventory_updated += 1
                        break
                    elif not pv.get('default_code'):
                        # Assign SKU to first available variant without SKU
                        models.execute_kw(
                            self.db_name, self.uid, self.api_key,
                            'product.product', 'write',
                            [[pv['id']], {'default_code': variant_sku}]
                        )
                        logger.debug(f"Assigned SKU {variant_sku} to variant {pv['id']}")
                        # Update inventory for this variant
                        if stock_location_id:
                            self._update_inventory(models, pv['id'], stock_location_id, variant_qty)
                            inventory_updated += 1
                        product_variants.remove(pv)  # Don't reuse this variant
                        break
            
            logger.info(f"Synced {len(variants)} variants for template {template_id}. Total inventory: {total_inventory}, Updated: {inventory_updated}")
            
        except Exception as e:
            logger.error(f"Error syncing variants: {e}", exc_info=True)

    def _get_default_warehouse(self, models) -> dict:
        """Get the default warehouse."""
        try:
            warehouses = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'stock.warehouse', 'search_read',
                [[]],
                {'fields': ['id', 'name', 'lot_stock_id'], 'limit': 1}
            )
            return warehouses[0] if warehouses else None
        except Exception as e:
            logger.error(f"Error getting warehouse: {e}")
            return None

    def _update_inventory(self, models, product_id: int, location_id: int, quantity: int):
        """Update inventory (Units on Hand) for a product variant.
        
        Uses multiple approaches for compatibility with different Odoo versions:
        1. Try stock.quant direct update (Odoo 14+)
        2. Fallback to inventory_quantity field on stock.quant
        3. Fallback to stock.change.product.qty wizard
        """
        try:
            logger.info(f"Updating inventory for product {product_id} at location {location_id}: {quantity} units")
            
            # Method 1: Try updating stock.quant directly
            existing_quant = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'stock.quant', 'search_read',
                [[['product_id', '=', product_id], ['location_id', '=', location_id]]],
                {'fields': ['id', 'quantity', 'inventory_quantity'], 'limit': 1}
            )
            
            if existing_quant:
                quant_id = existing_quant[0]['id']
                try:
                    # Try direct quantity update first
                    models.execute_kw(
                        self.db_name, self.uid, self.api_key,
                        'stock.quant', 'write',
                        [[quant_id], {'inventory_quantity': quantity}]
                    )
                    # Apply the inventory adjustment
                    try:
                        models.execute_kw(
                            self.db_name, self.uid, self.api_key,
                            'stock.quant', 'action_apply_inventory',
                            [[quant_id]]
                        )
                    except Exception:
                        # If action_apply_inventory doesn't exist, try setting quantity directly
                        models.execute_kw(
                            self.db_name, self.uid, self.api_key,
                            'stock.quant', 'write',
                            [[quant_id], {'quantity': quantity}]
                        )
                    logger.info(f"Updated existing quant {quant_id} for product {product_id}: {quantity} units")
                    return
                except Exception as e:
                    logger.warning(f"Direct quant update failed: {e}, trying alternative method")
            
            # Method 2: Create new quant record
            try:
                quant_vals = {
                    'product_id': product_id,
                    'location_id': location_id,
                    'inventory_quantity': quantity,
                }
                new_quant_id = models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'stock.quant', 'create',
                    [quant_vals]
                )
                # Try to apply inventory
                try:
                    models.execute_kw(
                        self.db_name, self.uid, self.api_key,
                        'stock.quant', 'action_apply_inventory',
                        [[new_quant_id]]
                    )
                except Exception:
                    # If apply fails, set quantity directly
                    models.execute_kw(
                        self.db_name, self.uid, self.api_key,
                        'stock.quant', 'write',
                        [[new_quant_id], {'quantity': quantity}]
                    )
                logger.info(f"Created new quant {new_quant_id} for product {product_id}: {quantity} units")
                return
            except Exception as e:
                logger.warning(f"Quant creation failed: {e}, trying wizard method")
            
            # Method 3: Use stock.change.product.qty wizard (older Odoo versions)
            try:
                wizard_id = models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'stock.change.product.qty', 'create',
                    [{
                        'product_id': product_id,
                        'new_quantity': quantity,
                        'location_id': location_id,
                    }]
                )
                models.execute_kw(
                    self.db_name, self.uid, self.api_key,
                    'stock.change.product.qty', 'change_product_qty',
                    [[wizard_id]]
                )
                logger.info(f"Used wizard to set inventory for product {product_id}: {quantity} units")
            except Exception as e:
                logger.error(f"All inventory update methods failed for product {product_id}: {e}")
            
        except Exception as e:
            logger.error(f"Error updating inventory for product {product_id}: {e}", exc_info=True)

    def _sync_images(self, models, template_id: int, images: list):
        """Sync product images to Odoo.
        
        Downloads images from supplier URLs and uploads them to Odoo.
        First image becomes the main product image (image_1920),
        additional images go to product.image records.
        
        Note: SanMar CDN (media.sanmarcanada.com) blocks server requests.
        Contact SanMar to whitelist your server IP for image downloads.
        """
        import base64
        import requests
        import os
        
        try:
            if not images:
                logger.info(f"No images to sync for template {template_id}")
                return
            
            logger.info(f"Starting image sync for template {template_id}: {len(images)} images available")
            
            synced_count = 0
            failed_urls = []
            blocked_domains = []
            
            # Sort images to prioritize primary images first
            sorted_images = sorted(images, key=lambda x: not x.get('is_primary', False))
            
            for i, img in enumerate(sorted_images[:5]):  # Limit to 5 images
                img_url = img.get('url', '')
                img_base64 = img.get('image_base64', '')  # Allow pre-encoded base64 data
                img_path = img.get('local_path', '')  # Allow local file path
                
                # Option 1: Use pre-encoded base64 if provided
                if img_base64:
                    try:
                        if synced_count == 0:
                            models.execute_kw(
                                self.db_name, self.uid, self.api_key,
                                'product.template', 'write',
                                [[template_id], {'image_1920': img_base64}]
                            )
                            logger.info(f"Set main image for template {template_id} from base64 data")
                            synced_count += 1
                        else:
                            img_name = img.get('description', '') or f'Image {synced_count + 1}'
                            models.execute_kw(
                                self.db_name, self.uid, self.api_key,
                                'product.image', 'create',
                                [{
                                    'product_tmpl_id': template_id,
                                    'name': img_name,
                                    'image_1920': img_base64,
                                }]
                            )
                            synced_count += 1
                        continue
                    except Exception as e:
                        logger.warning(f"Failed to upload base64 image: {e}")
                
                # Option 2: Read from local file if provided
                if img_path and os.path.exists(img_path):
                    try:
                        with open(img_path, 'rb') as f:
                            img_data = base64.b64encode(f.read()).decode('utf-8')
                        if synced_count == 0:
                            models.execute_kw(
                                self.db_name, self.uid, self.api_key,
                                'product.template', 'write',
                                [[template_id], {'image_1920': img_data}]
                            )
                            logger.info(f"Set main image for template {template_id} from local file")
                            synced_count += 1
                        else:
                            img_name = img.get('description', '') or f'Image {synced_count + 1}'
                            models.execute_kw(
                                self.db_name, self.uid, self.api_key,
                                'product.image', 'create',
                                [{
                                    'product_tmpl_id': template_id,
                                    'name': img_name,
                                    'image_1920': img_data,
                                }]
                            )
                            synced_count += 1
                        continue
                    except Exception as e:
                        logger.warning(f"Failed to read local image {img_path}: {e}")
                
                # Option 3: Download from URL
                if not img_url:
                    logger.warning(f"Image {i} has no URL, skipping")
                    continue
                
                logger.info(f"Processing image {i+1}/{min(len(sorted_images), 5)}: {img_url[:100]}...")
                
                try:
                    # Download image with better headers to bypass CDN restrictions
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                    }
                    
                    # Try to extract referer from URL
                    try:
                        url_parts = img_url.split('/')
                        if len(url_parts) >= 3:
                            headers['Referer'] = f"{url_parts[0]}//{url_parts[2]}/"
                    except Exception:
                        pass
                    
                    response = requests.get(img_url, headers=headers, timeout=30, allow_redirects=True)
                    
                    content_type = response.headers.get('content-type', '').lower()
                    content_length = len(response.content) if response.content else 0
                    
                    logger.debug(f"Response: status={response.status_code}, content-type={content_type}, size={content_length}")
                    
                    # Check if we got an actual image
                    is_image = False
                    if response.status_code == 200 and content_length > 1000:  # At least 1KB
                        # Check content type
                        if 'image' in content_type:
                            is_image = True
                        # Check magic bytes for common image formats
                        elif response.content:
                            magic = response.content[:8]
                            if (magic.startswith(b'\xff\xd8\xff') or  # JPEG
                                magic.startswith(b'\x89PNG') or       # PNG
                                magic.startswith(b'GIF8') or          # GIF
                                magic.startswith(b'RIFF') or          # WebP
                                magic.startswith(b'<svg')):           # SVG (will likely fail in Odoo)
                                is_image = True
                    
                    if is_image:
                        img_base64 = base64.b64encode(response.content).decode('utf-8')
                        
                        if synced_count == 0:
                            # First successful image is the main product image
                            models.execute_kw(
                                self.db_name, self.uid, self.api_key,
                                'product.template', 'write',
                                [[template_id], {'image_1920': img_base64}]
                            )
                            logger.info(f"Set main image for template {template_id} ({content_length} bytes)")
                            synced_count += 1
                        else:
                            # Additional images go to product.image
                            try:
                                img_name = img.get('description', '') or f'Image {synced_count + 1}'
                                models.execute_kw(
                                    self.db_name, self.uid, self.api_key,
                                    'product.image', 'create',
                                    [{
                                        'product_tmpl_id': template_id,
                                        'name': img_name,
                                        'image_1920': img_base64,
                                    }]
                                )
                                logger.info(f"Added extra image '{img_name}' for template {template_id}")
                                synced_count += 1
                            except Exception as img_err:
                                logger.warning(f"Could not add extra image to Odoo: {img_err}")
                    else:
                        failed_urls.append(img_url)
                        # Extract domain for reporting
                        try:
                            domain = img_url.split('/')[2]
                            if domain not in blocked_domains:
                                blocked_domains.append(domain)
                        except:
                            pass
                        
                        if response.status_code == 403:
                            logger.warning(f"Access denied (HTTP 403) for image from {domain} - server IP may need whitelisting")
                        elif response.status_code != 200:
                            logger.warning(f"Failed to download image: HTTP {response.status_code}")
                        elif content_length <= 1000:
                            logger.warning(f"Response too small ({content_length} bytes), likely CAPTCHA or error page")
                        else:
                            logger.warning(f"Response doesn't appear to be an image (content-type: {content_type})")
                        
                except requests.Timeout:
                    logger.warning(f"Timeout downloading image: {img_url[:100]}")
                    failed_urls.append(img_url)
                except requests.RequestException as e:
                    logger.warning(f"Error downloading image {img_url[:100]}: {e}")
                    failed_urls.append(img_url)
            
            if synced_count > 0:
                logger.info(f"Successfully synced {synced_count} images for template {template_id}")
            else:
                logger.warning(f"No images could be synced for template {template_id}. Failed URLs: {len(failed_urls)}")
                if blocked_domains:
                    logger.warning(f"BLOCKED DOMAINS: {', '.join(blocked_domains)} - Contact supplier to whitelist server IP for image access")
            
            if failed_urls:
                logger.debug(f"Failed image URLs: {failed_urls[:3]}...")  # Log first 3 failed URLs
            
            return {'synced': synced_count, 'failed': len(failed_urls), 'blocked_domains': blocked_domains}
            
        except Exception as e:
            logger.error(f"Error syncing images for template {template_id}: {e}", exc_info=True)
            return {'synced': 0, 'failed': 0, 'error': str(e)}

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

