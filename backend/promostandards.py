import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

try:
    from zeep import Client
    from zeep.transports import Transport
    from requests import Session
    ZEEP_AVAILABLE = True
except ImportError:
    ZEEP_AVAILABLE = False
    logger.warning("Zeep not installed. SOAP calls disabled.")


class PromoStandardsConnector:
    """Connector for PromoStandards SOAP APIs"""

    def __init__(self, supplier_config: dict):
        self.supplier_id = supplier_config.get('id', '')
        self.account_id = supplier_config.get('account_number', '')
        self.password = supplier_config.get('password', '')
        self.services = supplier_config.get('services', {})
        self.clients = {}
        if ZEEP_AVAILABLE:
            self._init_clients()

    def _init_clients(self):
        session = Session()
        session.verify = True
        transport = Transport(session=session, timeout=30, operation_timeout=30)
        for name, wsdl in self.services.items():
            if not wsdl:
                continue
            try:
                self.clients[name] = Client(wsdl, transport=transport)
                logger.info(f"SOAP client ready: {name}")
            except Exception as e:
                logger.error(f"SOAP client init failed [{name}]: {e}")

    def get_sellable_products(self) -> dict:
        if not ZEEP_AVAILABLE:
            return {'success': False, 'error': 'Zeep not installed'}
        client = self.clients.get('product_data')
        if not client:
            return {'success': False, 'error': 'Product Data client not initialized'}
        try:
            response = client.service.GetProductSellable(
                wsVersion='2.0.0',
                id=str(self.account_id),
                password=self.password,
                localizationCountry='CA',
                localizationLanguage='en',
                productId='ALL',
                isSellable=True
            )
            products = []
            if hasattr(response, 'ProductSellableArray') and response.ProductSellableArray:
                arr = response.ProductSellableArray
                if hasattr(arr, 'ProductSellable'):
                    for item in arr.ProductSellable:
                        pid = getattr(item, 'productId', None)
                        if pid:
                            products.append({
                                'product_id': str(pid),
                                'part_id': str(getattr(item, 'partId', '')) if getattr(item, 'partId', None) else None
                            })
            logger.info(f"Got {len(products)} sellable products")
            return {'success': True, 'products': products}
        except Exception as e:
            logger.error(f"GetProductSellable error: {e}")
            return {'success': False, 'error': str(e)}

    def get_product(self, product_id: str) -> dict:
        if not ZEEP_AVAILABLE:
            return {'success': False, 'error': 'Zeep not installed'}
        client = self.clients.get('product_data')
        if not client:
            return {'success': False, 'error': 'Product Data client not initialized'}
        try:
            response = client.service.GetProduct(
                wsVersion='2.0.0',
                id=str(self.account_id),
                password=self.password,
                localizationCountry='CA',
                localizationLanguage='en',
                productId=product_id
            )
            product = {
                'supplier_sku': product_id,
                'product_name': '', 'description': '', 'brand': '', 'category': '',
                'variants': [], 'fob_points': [], 'is_closeout': False
            }
            if hasattr(response, 'Product') and response.Product:
                p = response.Product
                product['product_name'] = str(getattr(p, 'productName', '') or '')
                product['description'] = str(getattr(p, 'description', '') or '').strip()
                product['brand'] = str(getattr(p, 'productBrand', '') or '')
                product['is_closeout'] = bool(getattr(p, 'isCloseout', False))
                # Category
                if hasattr(p, 'ProductCategoryArray') and p.ProductCategoryArray:
                    try:
                        cats = [str(getattr(c, 'category', '')) for c in p.ProductCategoryArray.ProductCategory if getattr(c, 'category', '')]
                        product['category'] = ', '.join(cats)
                    except Exception:
                        pass
                # Variants
                if hasattr(p, 'productPartArray') and p.productPartArray:
                    try:
                        parts = p.productPartArray.ProductPart if hasattr(p.productPartArray, 'ProductPart') else []
                        for part in parts:
                            v = {
                                'variant_sku': str(getattr(part, 'partId', '') or ''),
                                'color': str(getattr(part, 'colorName', '') or ''),
                                'size': str(getattr(part, 'labelSize', '') or ''),
                                'country_of_origin': str(getattr(part, 'countryOfOrigin', '') or ''),
                                'lead_time': str(getattr(part, 'leadTime', '') or ''),
                            }
                            product['variants'].append(v)
                    except Exception as e:
                        logger.error(f"Variant parse error: {e}")
            return {'success': True, 'product': product}
        except Exception as e:
            logger.error(f"GetProduct error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}

    def get_inventory(self, product_id: str) -> dict:
        if not ZEEP_AVAILABLE:
            return {'success': False, 'error': 'Zeep not installed'}
        client = self.clients.get('inventory')
        if not client:
            return {'success': False, 'error': 'Inventory client not initialized'}
        try:
            response = client.service.getInventoryLevels(
                wsVersion='2.0.0',
                id=str(self.account_id),
                password=self.password,
                productId=product_id
            )
            inventory = []
            if hasattr(response, 'Inventory') and response.Inventory:
                inv = response.Inventory
                if hasattr(inv, 'PartInventoryArray') and inv.PartInventoryArray:
                    for part in inv.PartInventoryArray.PartInventory:
                        item = {
                            'part_id': str(getattr(part, 'partId', '')),
                            'part_color': str(getattr(part, 'partColor', '')),
                            'label_size': str(getattr(part, 'labelSize', '')),
                            'quantity_available': 0,
                            'warehouses': []
                        }
                        if hasattr(part, 'quantityAvailable') and part.quantityAvailable:
                            try:
                                item['quantity_available'] = int(getattr(part.quantityAvailable, 'Quantity', 0) or 0)
                            except Exception:
                                pass
                        if hasattr(part, 'InventoryLocationArray') and part.InventoryLocationArray:
                            try:
                                for loc in part.InventoryLocationArray.InventoryLocation:
                                    wh = {
                                        'id': str(getattr(loc, 'inventoryLocationId', '')),
                                        'name': str(getattr(loc, 'inventoryLocationName', '')),
                                        'quantity': 0
                                    }
                                    if hasattr(loc, 'inventoryLocationQuantity') and loc.inventoryLocationQuantity:
                                        try:
                                            wh['quantity'] = int(getattr(loc.inventoryLocationQuantity, 'Quantity', 0) or 0)
                                        except Exception:
                                            pass
                                    item['warehouses'].append(wh)
                            except Exception:
                                pass
                        inventory.append(item)
            return {'success': True, 'inventory': inventory}
        except Exception as e:
            logger.error(f"getInventoryLevels error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}

    def get_pricing(self, product_id: str) -> dict:
        if not ZEEP_AVAILABLE:
            return {'success': False, 'error': 'Zeep not installed'}
        client = self.clients.get('pricing')
        if not client:
            return {'success': False, 'error': 'Pricing client not initialized'}
        try:
            response = client.service.GetConfigurationAndPricing(
                wsVersion='1.0.0',
                id=str(self.account_id),
                password=self.password,
                productId=product_id,
                currency='CAD',
                fobId='',
                priceType='Net',
                localizationCountry='CA',
                localizationLanguage='en',
                configurationType='Blank'
            )
            pricing = []
            if hasattr(response, 'Configuration') and response.Configuration:
                config = response.Configuration
                if hasattr(config, 'PartArray') and config.PartArray:
                    for part in config.PartArray.Part:
                        pi = {'part_id': str(getattr(part, 'partId', '')), 'prices': []}
                        if hasattr(part, 'PartPriceArray') and part.PartPriceArray:
                            for price in part.PartPriceArray.PartPrice:
                                pi['prices'].append({
                                    'min_quantity': int(getattr(price, 'minQuantity', 0) or 0),
                                    'price': float(getattr(price, 'price', 0) or 0),
                                    'uom': str(getattr(price, 'priceUom', '') or ''),
                                })
                        pricing.append(pi)
            return {'success': True, 'pricing': pricing}
        except Exception as e:
            logger.error(f"GetConfigurationAndPricing error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}

    def get_media(self, product_id: str) -> dict:
        if not ZEEP_AVAILABLE:
            return {'success': False, 'error': 'Zeep not installed'}
        client = self.clients.get('media')
        if not client:
            return {'success': False, 'error': 'Media client not initialized'}
        try:
            response = client.service.getMediaContent(
                wsVersion='1.1.0',
                Id=str(self.account_id),
                Password=self.password,
                mediaType='Image',
                productId=product_id
            )
            media = []
            if hasattr(response, 'MediaContentArray') and response.MediaContentArray:
                for item in response.MediaContentArray.MediaContent:
                    media.append({
                        'url': str(getattr(item, 'url', '')),
                        'media_type': str(getattr(item, 'mediaType', 'Image')),
                        'width': getattr(item, 'width', None),
                        'height': getattr(item, 'height', None),
                        'color': str(getattr(item, 'color', '') or ''),
                        'description': str(getattr(item, 'description', '') or '')
                    })
            return {'success': True, 'media': media}
        except Exception as e:
            logger.error(f"getMediaContent error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}
