"""
PromoStandards SOAP Connector - Raw XML approach.
Works with ANY PromoStandards-compliant supplier without WSDL fetching.
Uses standardized XML namespaces and operation names.
"""
import logging
import requests
from lxml import etree
from typing import Dict, List, Optional
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)

# Standard PromoStandards XML Namespaces
NS = {
    'soap': 'http://schemas.xmlsoap.org/soap/envelope/',
    'pd': 'http://www.promostandards.org/WSDL/ProductDataService/2.0.0/',
    'pd_so': 'http://www.promostandards.org/WSDL/ProductDataService/2.0.0/SharedObjects/',
    'inv': 'http://www.promostandards.org/WSDL/Inventory/2.0.0/',
    'inv_so': 'http://www.promostandards.org/WSDL/Inventory/2.0.0/SharedObjects/',
    'ppc': 'http://www.promostandards.org/WSDL/PricingAndConfiguration/1.0.0/',
    'ppc_so': 'http://www.promostandards.org/WSDL/PricingAndConfiguration/1.0.0/SharedObjects/',
    'mc': 'http://www.promostandards.org/WSDL/MediaService/1.0.0/',
    'mc_so': 'http://www.promostandards.org/WSDL/MediaService/1.0.0/SharedObjects/',
    'bd': 'https://edi.atc-apparel.com/bulk-data/',
}

# Known supplier endpoint patterns (service endpoints, NOT WSDLs)
SUPPLIER_PATTERNS = {
    "ss": {
        "label": "S&S Activewear",
        "product_data": "{base}/ProductData/v2/ProductDataServicev2.svc",
        "inventory": "{base}/Inventory/v2/InventoryService.svc",
        "pricing": "{base}/PricingAndConfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/MediaContent/v1/MediaContentService.svc",
        "bulk_data": "{base}/BulkData/v1/BulkDataService.svc",
    },
    "atc": {
        "label": "ATC / SanMar",
        "product_data": "{base}/pstd/productdata2.0/ProductDataServiceV2.php",
        "inventory": "{base}/pstd/inventory2.0/InventoryServiceV2.php",
        "pricing": "{base}/pstd/productpricingconfiguration/PricingAndConfigurationService.php",
        "media": "{base}/pstd/mediacontent1.1/MediaContentService.php",
        "bulk_data": "{base}/bulk-data/BulkDataService.php",
    },
    "alphabroder": {
        "label": "alphabroder",
        "product_data": "{base}/promostandards/ProductDataService/v2.0.0/ProductDataService.svc",
        "inventory": "{base}/promostandards/InventoryService/v2.0.0/InventoryService.svc",
        "pricing": "{base}/promostandards/PricingAndConfigurationService/v1.0.0/PricingAndConfigurationService.svc",
        "media": "{base}/promostandards/MediaContentService/v1.1.0/MediaContentService.svc",
        "bulk_data": "{base}/promostandards/BulkDataService/v1.0.0/BulkDataService.svc",
    },
    "generic": {
        "label": "Generic PromoStandards",
        "product_data": "{base}/productdata/v2/ProductDataService.svc",
        "inventory": "{base}/inventory/v2/InventoryService.svc",
        "pricing": "{base}/pricingandconfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/mediacontent/v1/MediaContentService.svc",
        "bulk_data": "{base}/bulkdata/v1/BulkDataService.svc",
    }
}


def generate_endpoints(base_url: str, style: str) -> Dict[str, str]:
    """Generate service endpoints from base URL and style."""
    base = base_url.rstrip('/')
    pattern = SUPPLIER_PATTERNS.get(style, SUPPLIER_PATTERNS['generic'])
    return {k: v.format(base=base) for k, v in pattern.items() if k != 'label'}


def _soap_call(endpoint: str, action: str, body_xml: str, timeout: int = 30) -> Optional[etree._Element]:
    """Execute a raw SOAP call and return parsed XML response body."""
    envelope = f'''<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    {body_xml}
  </soap:Body>
</soap:Envelope>'''

    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': action,
        'User-Agent': 'SupplierHub/1.0 PromoStandards Client',
    }

    resp = requests.post(endpoint, data=envelope.encode('utf-8'), headers=headers, timeout=timeout)

    if resp.status_code == 403:
        raise ConnectionError("Access denied (HTTP 403). The supplier's server is blocking requests from this IP address. Contact the supplier to whitelist your server IP, or deploy the middleware from a different network.")
    if resp.status_code == 404:
        raise ConnectionError(f"Endpoint not found (HTTP 404). Verify the service URL: {endpoint}")
    if resp.status_code >= 400:
        raise ConnectionError(f"HTTP {resp.status_code} from {endpoint}: {resp.text[:200]}")

    root = etree.fromstring(resp.content)
    body = root.find('.//soap:Body', NS)
    if body is None:
        body = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}Body')
    return body


def _get_text(el, path, namespaces=None, default=''):
    """Safely extract text from XML element."""
    if el is None:
        return default
    found = el.find(path, namespaces) if namespaces else el.find(path)
    if found is not None and found.text:
        return found.text.strip()
    return default


def _get_int(el, path, namespaces=None, default=0):
    """Safely extract int from XML element."""
    text = _get_text(el, path, namespaces, '')
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return default


def _get_float(el, path, namespaces=None, default=0.0):
    """Safely extract float from XML element."""
    text = _get_text(el, path, namespaces, '')
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


class PromoStandardsConnector:
    """Multi-supplier PromoStandards connector using raw SOAP XML."""

    def __init__(self, supplier_config: dict):
        self.supplier_id = supplier_config.get('id', '')
        self.account_id = str(supplier_config.get('account_number', ''))
        self.password = supplier_config.get('password', '')
        self.media_password = supplier_config.get('media_password', '') or self.password
        self.services = supplier_config.get('services', {})
        self.endpoint_style = supplier_config.get('endpoint_style', '')
        self.base_url = supplier_config.get('api_base_url', '')
        
        # XML-escaped versions for use in SOAP requests
        self._safe_account_id = xml_escape(self.account_id)
        self._safe_password = xml_escape(self.password)
        self._safe_media_password = xml_escape(self.media_password)

        # Auto-detect endpoint style from base URL if not set
        if not self.endpoint_style and self.base_url:
            base_lower = self.base_url.lower()
            if 'atc-apparel' in base_lower or 'sanmar' in base_lower:
                self.endpoint_style = 'atc'
            elif 'ssactivewear' in base_lower:
                self.endpoint_style = 'ss'
            elif 'alphabroder' in base_lower:
                self.endpoint_style = 'alphabroder'
            else:
                self.endpoint_style = 'generic'
            logger.debug(f"Auto-detected endpoint style: {self.endpoint_style}")

        # Auto-generate endpoints if not explicitly set
        if not self.services and self.base_url and self.endpoint_style:
            self.services = generate_endpoints(self.base_url, self.endpoint_style)
            logger.info(f"Auto-generated endpoints for {self.endpoint_style}: {list(self.services.keys())}")

        # Strip ?wsdl from endpoints (we need service endpoints, not WSDL URLs)
        for key in list(self.services.keys()):
            url = self.services[key]
            if url.endswith('?wsdl') or url.endswith('?WSDL'):
                self.services[key] = url.rsplit('?', 1)[0]

    def _get_endpoint(self, service_name: str) -> str:
        url = self.services.get(service_name)
        if not url:
            raise ValueError(f"No endpoint configured for '{service_name}'. Configure service URLs in Supplier settings.")
        return url

    def test_connection(self) -> dict:
        """Test connectivity to the product data endpoint."""
        try:
            endpoint = self._get_endpoint('product_data')
            body_xml = f'''<ns:GetProductSellableRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:localizationCountry>US</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>ALL</ns:productId>
              <ns:isSellable>true</ns:isSellable>
            </ns:GetProductSellableRequest>'''
            body = _soap_call(endpoint, 'getProductSellable', body_xml, timeout=15)

            # Check for error in response
            err_el = body.find('.//{http://www.promostandards.org/WSDL/ProductDataService/2.0.0/}ErrorMessage')
            if err_el is not None:
                code = _get_text(err_el, '{http://www.promostandards.org/WSDL/ProductDataService/2.0.0/SharedObjects/}code')
                desc = _get_text(err_el, '{http://www.promostandards.org/WSDL/ProductDataService/2.0.0/SharedObjects/}description')
                if code and code != '0':
                    return {'success': False, 'connected': True, 'message': f'API Error {code}: {desc}'}

            return {'success': True, 'connected': True, 'message': 'Connection successful'}
        except ConnectionError as e:
            return {'success': False, 'connected': False, 'message': str(e)}
        except ValueError as e:
            return {'success': False, 'connected': False, 'message': str(e)}
        except Exception as e:
            return {'success': False, 'connected': False, 'message': f'Connection failed: {str(e)}'}

    def get_sellable_products(self) -> dict:
        try:
            endpoint = self._get_endpoint('product_data')
            body_xml = f'''<ns:GetProductSellableRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:localizationCountry>US</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>ALL</ns:productId>
              <ns:isSellable>true</ns:isSellable>
            </ns:GetProductSellableRequest>'''

            body = _soap_call(endpoint, 'getProductSellable', body_xml)
            products = []

            # Parse response - try both namespaced and unnamespaced
            for ps in body.iter():
                if 'ProductSellable' in ps.tag and 'Array' not in ps.tag and 'Request' not in ps.tag and 'Response' not in ps.tag:
                    pid = None
                    part_id = None
                    for child in ps:
                        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if tag == 'productId' and child.text:
                            raw_pid = child.text.strip()
                            # Extract base product ID - some APIs return "SKU(Color,Size,X)" format
                            # We need just "SKU" for getProduct calls
                            if '(' in raw_pid:
                                pid = raw_pid.split('(')[0]
                            else:
                                pid = raw_pid
                        elif tag == 'partId' and child.text:
                            part_id = child.text.strip()
                    if pid:
                        products.append({'product_id': pid, 'part_id': part_id})

            logger.info(f"Got {len(products)} sellable items")
            return {'success': True, 'products': products}
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"getProductSellable error: {e}")
            return {'success': False, 'error': str(e)}

    def get_product(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('product_data')
            safe_product_id = xml_escape(product_id)
            body_xml = f'''<ns:GetProductRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:localizationCountry>US</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>{safe_product_id}</ns:productId>
            </ns:GetProductRequest>'''

            body = _soap_call(endpoint, 'getProduct', body_xml)

            product = {
                'supplier_sku': product_id,
                'product_name': '', 'description': '', 'brand': '', 'category': '',
                'variants': [], 'is_closeout': False
            }

            # Helper to get clean text (handles mixed content)
            def get_clean_text(element):
                if element is None:
                    return ''
                # Get direct text content only, not nested elements
                text = element.text
                if text and isinstance(text, str):
                    clean = text.strip()
                    # Skip if it looks like array/object serialization
                    if clean and clean not in ['Array', 'Object', '[]', '{}']:
                        return clean
                return ''

            # Extract product data from response
            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'productName':
                    text = get_clean_text(el)
                    if text and not product['product_name']:
                        product['product_name'] = text
                elif tag == 'description':
                    text = get_clean_text(el)
                    if text and not product['description']:
                        product['description'] = text
                elif tag == 'productBrand':
                    text = get_clean_text(el)
                    if text:
                        product['brand'] = text
                elif tag == 'isCloseout':
                    text = get_clean_text(el)
                    if text:
                        product['is_closeout'] = text.lower() == 'true'

            # Extract categories
            categories = []
            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'category' and el.text:
                    categories.append(el.text.strip())
            if categories:
                product['category'] = ', '.join(set(categories))

            # Extract variants (ProductPart elements)
            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'ProductPart':
                    variant = {'variant_sku': '', 'color': '', 'size': '', 'country_of_origin': '', 'lead_time': ''}
                    
                    # Get direct children of ProductPart
                    for child in el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            variant['variant_sku'] = child.text.strip()
                        elif ctag == 'countryOfOrigin' and child.text:
                            variant['country_of_origin'] = child.text.strip()
                        elif ctag == 'leadTime' and child.text:
                            variant['lead_time'] = child.text.strip()
                        elif ctag == 'ColorArray':
                            # Color is nested: ColorArray/Color/colorName
                            for color_el in child:
                                for color_child in color_el:
                                    cctag = color_child.tag.split('}')[-1] if '}' in color_child.tag else color_child.tag
                                    if cctag == 'colorName' and color_child.text:
                                        variant['color'] = color_child.text.strip()
                                        break
                        elif ctag == 'ApparelSize':
                            # Size is nested: ApparelSize/labelSize
                            for size_child in child:
                                stag = size_child.tag.split('}')[-1] if '}' in size_child.tag else size_child.tag
                                if stag == 'labelSize' and size_child.text:
                                    variant['size'] = size_child.text.strip()
                                    break
                    
                    # Only add variants with a valid SKU (skip 'DEFAULT' placeholder)
                    if variant['variant_sku'] and variant['variant_sku'] != 'DEFAULT':
                        product['variants'].append(variant)

            return {'success': True, 'product': product}
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"getProduct error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}

    def get_inventory(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('inventory')
            safe_product_id = xml_escape(product_id)
            body_xml = f'''<ns:GetInventoryLevelsRequest xmlns:ns="{NS['inv']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:productId>{safe_product_id}</ns:productId>
            </ns:GetInventoryLevelsRequest>'''

            body = _soap_call(endpoint, 'getInventoryLevels', body_xml)
            inventory = []

            # Helper to extract quantity value from nested Quantity element
            def get_quantity_value(parent_el):
                """Extract value from <Quantity><value>X</value></Quantity> structure"""
                for child in parent_el.iter():
                    ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if ctag == 'value' and child.text:
                        try:
                            return int(float(child.text.strip()))
                        except ValueError:
                            pass
                return 0

            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'PartInventory':
                    item = {'part_id': '', 'part_color': '', 'label_size': '', 'quantity_available': 0, 'warehouses': []}
                    for child in el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            item['part_id'] = child.text.strip()
                        elif ctag == 'partColor' and child.text:
                            item['part_color'] = child.text.strip()
                        elif ctag == 'labelSize' and child.text:
                            item['label_size'] = child.text.strip()
                        elif ctag == 'quantityAvailable':
                            # Handle nested <Quantity><value>X</value></Quantity> structure
                            item['quantity_available'] = get_quantity_value(child)
                        elif ctag == 'InventoryLocationArray':
                            for loc_el in child:
                                loc_tag = loc_el.tag.split('}')[-1] if '}' in loc_el.tag else loc_el.tag
                                if loc_tag == 'InventoryLocation':
                                    wh = {'id': '', 'name': '', 'quantity': 0}
                                    for loc_child in loc_el:
                                        ltag = loc_child.tag.split('}')[-1] if '}' in loc_child.tag else loc_child.tag
                                        if ltag == 'inventoryLocationId' and loc_child.text:
                                            wh['id'] = loc_child.text.strip()
                                        elif ltag == 'inventoryLocationName' and loc_child.text:
                                            wh['name'] = loc_child.text.strip()
                                        elif ltag == 'inventoryLocationQuantity':
                                            # Handle nested <Quantity><value>X</value></Quantity> structure
                                            wh['quantity'] = get_quantity_value(loc_child)
                                    if wh['id']:
                                        item['warehouses'].append(wh)
                    if item['part_id']:
                        inventory.append(item)

            return {'success': True, 'inventory': inventory}
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"getInventoryLevels error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}

    def get_pricing(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('pricing')
            safe_product_id = xml_escape(product_id)
            body_xml = f'''<ns:GetConfigurationAndPricingRequest xmlns:ns="{NS['ppc']}">
              <ns:wsVersion>1.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
              <ns:productId>{safe_product_id}</ns:productId>
              <ns:currency>USD</ns:currency>
              <ns:fobId></ns:fobId>
              <ns:priceType>Net</ns:priceType>
              <ns:localizationCountry>US</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:configurationType>Blank</ns:configurationType>
            </ns:GetConfigurationAndPricingRequest>'''

            body = _soap_call(endpoint, 'GetConfigurationAndPricing', body_xml)
            pricing = []

            # Find all Part elements
            for part_el in body.iter():
                tag = part_el.tag.split('}')[-1] if '}' in part_el.tag else part_el.tag
                if tag == 'Part':
                    part_data = {'part_id': '', 'prices': []}
                    
                    # Get direct children of Part
                    for child in part_el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            part_data['part_id'] = child.text.strip()
                        elif ctag == 'PartPriceArray':
                            # Iterate over PartPrice elements
                            for pp in child:
                                price = {'min_quantity': 0, 'price': 0.0, 'uom': ''}
                                for pchild in pp:
                                    ptag = pchild.tag.split('}')[-1] if '}' in pchild.tag else pchild.tag
                                    if ptag == 'minQuantity' and pchild.text:
                                        try:
                                            price['min_quantity'] = int(float(pchild.text.strip()))
                                        except ValueError:
                                            pass
                                    elif ptag == 'price' and pchild.text:
                                        try:
                                            price['price'] = float(pchild.text.strip())
                                        except ValueError:
                                            pass
                                    elif ptag == 'priceUom' and pchild.text:
                                        price['uom'] = pchild.text.strip()
                                if price['price'] > 0:
                                    part_data['prices'].append(price)
                    
                    if part_data['part_id'] and part_data['prices']:
                        pricing.append(part_data)

            return {'success': True, 'pricing': pricing}
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"GetConfigurationAndPricing error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}

    def get_media(self, product_id: str) -> dict:
        try:
            endpoint = self._get_endpoint('media')
            safe_product_id = xml_escape(product_id)
            body_xml = f'''<ns:GetMediaContentRequest xmlns:ns="{NS['mc']}">
              <ns:wsVersion>1.1.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_media_password}</ns:password>
              <ns:cultureName>en-us</ns:cultureName>
              <ns:mediaType>Image</ns:mediaType>
              <ns:productId>{safe_product_id}</ns:productId>
              <ns:partId></ns:partId>
              <ns:classType>0</ns:classType>
            </ns:GetMediaContentRequest>'''

            body = _soap_call(endpoint, 'getMediaContent', body_xml)
            media = []

            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'MediaContent' and 'Array' not in el.tag:
                    item = {'url': '', 'media_type': 'Image', 'width': None, 'height': None, 'color': '', 'description': ''}
                    for child in el:
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'url' and child.text:
                            item['url'] = child.text.strip()
                        elif ctag == 'mediaType' and child.text:
                            item['media_type'] = child.text.strip()
                        elif ctag == 'width' and child.text:
                            try:
                                item['width'] = int(child.text.strip())
                            except ValueError:
                                pass
                        elif ctag == 'height' and child.text:
                            try:
                                item['height'] = int(child.text.strip())
                            except ValueError:
                                pass
                        elif ctag == 'color' and child.text:
                            item['color'] = child.text.strip()
                        elif ctag == 'description' and child.text:
                            item['description'] = child.text.strip()
                    
                    # Handle case where URL field contains multiple URLs (newline-separated)
                    if item['url']:
                        url_lines = [u.strip() for u in item['url'].split('\n') if u.strip()]
                        if len(url_lines) > 1:
                            # Multiple URLs in single field - create separate media items
                            for url in url_lines:
                                if url.startswith('http'):
                                    media.append({
                                        'url': url,
                                        'media_type': item['media_type'],
                                        'color': item['color'],
                                        'description': item['description']
                                    })
                        else:
                            media.append(item)

            logger.info(f"Got {len(media)} media items for {product_id}")
            return {'success': True, 'media': media}
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"getMediaContent error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}


    def get_bulk_data(self) -> dict:
        """
        Get bulk product data using BulkData Service 1.0.
        This endpoint returns comprehensive product data including image URLs
        that can be downloaded (unlike MediaContent URLs which are hotlink-blocked).
        
        Returns product data with: productId, productName, style, size, color, brand, 
        weight, quantity, price, salePrice, and importantly - image URLs.
        
        IMPORTANT: Limited to once per day per account. Subsequent calls return error 125.
        """
        try:
            endpoint = self._get_endpoint('bulk_data')
            
            # BulkData uses a different namespace than other PromoStandards services
            body_xml = f'''<ns:GetBulkDataRequest xmlns:ns="{NS['bd']}">
              <ns:wsVersion>1.0.0</ns:wsVersion>
              <ns:id>{self._safe_account_id}</ns:id>
              <ns:password>{self._safe_password}</ns:password>
            </ns:GetBulkDataRequest>'''
            
            logger.info(f"Calling BulkData API at {endpoint}")
            body = _soap_call(endpoint, 'getBulkData', body_xml, timeout=120)  # Longer timeout for large response
            
            # Check for service messages (errors)
            for msg_el in body.iter():
                tag = msg_el.tag.split('}')[-1] if '}' in msg_el.tag else msg_el.tag
                if tag == 'ServiceMessage':
                    code = ''
                    desc = ''
                    severity = ''
                    for child in msg_el.iter():
                        child_tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        text = child.text.strip() if child.text else ''
                        if child_tag == 'code':
                            code = text
                        elif child_tag == 'description':
                            desc = text
                        elif child_tag == 'severity':
                            severity = text
                    
                    if code == '125':
                        logger.warning(f"BulkData rate limit: {desc}")
                        return {'success': False, 'error': f"Rate limited: {desc}", 'rate_limited': True, 'code': code}
                    elif severity.lower() == 'error':
                        logger.error(f"BulkData service error [{code}]: {desc}")
                        return {'success': False, 'error': f"Service error [{code}]: {desc}", 'code': code}
            
            products = []
            current_product = None
            
            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                
                # Parse product data - look for Product element
                if tag == 'Product':
                    if current_product and current_product.get('product_id'):
                        products.append(current_product)
                    current_product = {
                        'product_id': '',
                        'product_name': '',
                        'fr_product_name': '',
                        'description': '',
                        'style': '',
                        'size': '',
                        'color': '',
                        'fr_color': '',
                        'brand': '',
                        'image_url': '',
                        'weight': None,
                        'case_size': None,
                        'quantity': 0,
                        'price': 0,
                        'sale_price': 0,
                        'sale_end_date': '',
                        'price_group': '',
                        'youth': False,
                        'discount_code': ''
                    }
                elif current_product is not None:
                    text = el.text.strip() if el.text else ''
                    tag_lower = tag.lower()
                    
                    if tag_lower == 'productid':
                        current_product['product_id'] = text
                    elif tag_lower == 'productname':
                        current_product['product_name'] = text
                    elif tag_lower == 'frproductname':
                        current_product['fr_product_name'] = text
                    elif tag_lower == 'description':
                        current_product['description'] = text
                    elif tag_lower == 'style':
                        current_product['style'] = text
                    elif tag_lower == 'size':
                        current_product['size'] = text
                    elif tag_lower == 'swatchcolor':
                        current_product['color'] = text
                    elif tag_lower == 'frswatchcolor':
                        current_product['fr_color'] = text
                    elif tag_lower == 'brand':
                        current_product['brand'] = text
                    elif tag_lower == 'image':
                        current_product['image_url'] = text
                    elif tag_lower == 'weight' and text:
                        try:
                            # Remove any text like "Lbs" from weight
                            weight_str = text.replace('Lbs', '').replace('(', '').replace(')', '').strip()
                            current_product['weight'] = float(weight_str)
                        except ValueError:
                            pass
                    elif tag_lower == 'casesize' and text:
                        try:
                            current_product['case_size'] = int(text)
                        except ValueError:
                            pass
                    elif tag_lower == 'quantity' and text:
                        try:
                            current_product['quantity'] = int(float(text))
                        except ValueError:
                            pass
                    elif tag_lower == 'price' and text:
                        try:
                            current_product['price'] = float(text)
                        except ValueError:
                            pass
                    elif tag_lower == 'saleprice' and text:
                        try:
                            current_product['sale_price'] = float(text)
                        except ValueError:
                            pass
                    elif tag_lower == 'saleenddate':
                        current_product['sale_end_date'] = text
                    elif tag_lower == 'pricegroup':
                        current_product['price_group'] = text
                    elif tag_lower == 'youth':
                        current_product['youth'] = text.upper() == 'TRUE'
                    elif tag_lower == 'discountcode':
                        current_product['discount_code'] = text
            
            # Don't forget the last product
            if current_product and current_product.get('product_id'):
                products.append(current_product)
            
            logger.info(f"BulkData returned {len(products)} products")
            return {'success': True, 'products': products, 'count': len(products)}
            
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"getBulkData error: {e}")
            return {'success': False, 'error': str(e)}

    def download_image(self, image_url: str, save_path: str = None) -> dict:
        """
        Download an image from a URL and optionally save it locally.
        This is used for BulkData images which can be downloaded (not hotlink-blocked).
        
        Args:
            image_url: The URL of the image to download
            save_path: Optional local path to save the image
            
        Returns:
            dict with 'success', 'image_data' (base64), and optionally 'saved_path'
        """
        import base64
        import os
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'image/*,*/*;q=0.8',
            }
            
            response = requests.get(image_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
            
            content_type = response.headers.get('content-type', '').lower()
            
            # Verify it's an image
            is_image = 'image' in content_type
            if not is_image and response.content:
                magic = response.content[:8]
                is_image = (magic.startswith(b'\xff\xd8\xff') or  # JPEG
                           magic.startswith(b'\x89PNG') or        # PNG
                           magic.startswith(b'GIF8') or           # GIF
                           magic.startswith(b'RIFF'))             # WebP
            
            if not is_image:
                return {'success': False, 'error': 'Response is not an image'}
            
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            result = {'success': True, 'image_data': image_base64, 'size': len(response.content)}
            
            # Save to file if path provided
            if save_path:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                result['saved_path'] = save_path
                logger.info(f"Saved image to {save_path}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error downloading image {image_url}: {e}")
            return {'success': False, 'error': str(e)}
