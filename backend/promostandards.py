"""
PromoStandards SOAP Connector - Raw XML approach.
Works with ANY PromoStandards-compliant supplier without WSDL fetching.
Uses standardized XML namespaces and operation names.
"""
import logging
import requests
from lxml import etree
from typing import Dict, List, Optional

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
}

# Known supplier endpoint patterns (service endpoints, NOT WSDLs)
SUPPLIER_PATTERNS = {
    "ss": {
        "label": "S&S Activewear",
        "product_data": "{base}/ProductData/v2/ProductDataServicev2.svc",
        "inventory": "{base}/Inventory/v2/InventoryService.svc",
        "pricing": "{base}/PricingAndConfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/MediaContent/v1/MediaContentService.svc",
    },
    "atc": {
        "label": "ATC / SanMar",
        "product_data": "{base}/pstd/productdata2.0/ProductDataServiceV2.php",
        "inventory": "{base}/pstd/inventory2.0/InventoryServiceV2.php",
        "pricing": "{base}/pstd/productpricingconfiguration/PricingAndConfigurationService.php",
        "media": "{base}/pstd/mediacontent1.1/MediaContentService.php",
    },
    "alphabroder": {
        "label": "alphabroder",
        "product_data": "{base}/promostandards/ProductDataService/v2.0.0/ProductDataService.svc",
        "inventory": "{base}/promostandards/InventoryService/v2.0.0/InventoryService.svc",
        "pricing": "{base}/promostandards/PricingAndConfigurationService/v1.0.0/PricingAndConfigurationService.svc",
        "media": "{base}/promostandards/MediaContentService/v1.1.0/MediaContentService.svc",
    },
    "generic": {
        "label": "Generic PromoStandards",
        "product_data": "{base}/productdata/v2/ProductDataService.svc",
        "inventory": "{base}/inventory/v2/InventoryService.svc",
        "pricing": "{base}/pricingandconfiguration/v1/PricingAndConfigurationService.svc",
        "media": "{base}/mediacontent/v1/MediaContentService.svc",
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
              <ns:id>{self.account_id}</ns:id>
              <ns:password>{self.password}</ns:password>
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
              <ns:id>{self.account_id}</ns:id>
              <ns:password>{self.password}</ns:password>
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
            body_xml = f'''<ns:GetProductRequest xmlns:ns="{NS['pd']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self.account_id}</ns:id>
              <ns:password>{self.password}</ns:password>
              <ns:localizationCountry>US</ns:localizationCountry>
              <ns:localizationLanguage>en</ns:localizationLanguage>
              <ns:productId>{product_id}</ns:productId>
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
                    for child in el.iter():
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            variant['variant_sku'] = child.text.strip()
                        elif ctag == 'colorName' and child.text:
                            variant['color'] = child.text.strip()
                        elif ctag == 'labelSize' and child.text:
                            variant['size'] = child.text.strip()
                        elif ctag == 'countryOfOrigin' and child.text:
                            variant['country_of_origin'] = child.text.strip()
                        elif ctag == 'leadTime' and child.text:
                            variant['lead_time'] = child.text.strip()
                    if variant['variant_sku']:
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
            body_xml = f'''<ns:GetInventoryLevelsRequest xmlns:ns="{NS['inv']}">
              <ns:wsVersion>2.0.0</ns:wsVersion>
              <ns:id>{self.account_id}</ns:id>
              <ns:password>{self.password}</ns:password>
              <ns:productId>{product_id}</ns:productId>
            </ns:GetInventoryLevelsRequest>'''

            body = _soap_call(endpoint, 'getInventoryLevels', body_xml)
            inventory = []

            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'PartInventory':
                    item = {'part_id': '', 'part_color': '', 'label_size': '', 'quantity_available': 0, 'warehouses': []}
                    for child in el.iter():
                        ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if ctag == 'partId' and child.text:
                            item['part_id'] = child.text.strip()
                        elif ctag == 'partColor' and child.text:
                            item['part_color'] = child.text.strip()
                        elif ctag == 'labelSize' and child.text:
                            item['label_size'] = child.text.strip()
                        elif ctag == 'quantityAvailable' and child.text:
                            try:
                                item['quantity_available'] = int(float(child.text.strip()))
                            except ValueError:
                                pass
                        elif ctag == 'InventoryLocation':
                            wh = {'id': '', 'name': '', 'quantity': 0}
                            for loc_child in child.iter():
                                ltag = loc_child.tag.split('}')[-1] if '}' in loc_child.tag else loc_child.tag
                                if ltag == 'inventoryLocationId' and loc_child.text:
                                    wh['id'] = loc_child.text.strip()
                                elif ltag == 'inventoryLocationName' and loc_child.text:
                                    wh['name'] = loc_child.text.strip()
                                elif ltag == 'inventoryLocationQuantity' and loc_child.text:
                                    try:
                                        wh['quantity'] = int(float(loc_child.text.strip()))
                                    except ValueError:
                                        pass
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
            body_xml = f'''<ns:GetConfigurationAndPricingRequest xmlns:ns="{NS['ppc']}">
              <ns:wsVersion>1.0.0</ns:wsVersion>
              <ns:id>{self.account_id}</ns:id>
              <ns:password>{self.password}</ns:password>
              <ns:productId>{product_id}</ns:productId>
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
            password = self.media_password
            body_xml = f'''<ns:GetMediaContentRequest xmlns:ns="{NS['mc']}">
              <ns:wsVersion>1.1.0</ns:wsVersion>
              <ns:id>{self.account_id}</ns:id>
              <ns:password>{password}</ns:password>
              <ns:cultureName>en-us</ns:cultureName>
              <ns:mediaType>Image</ns:mediaType>
              <ns:productId>{product_id}</ns:productId>
              <ns:partId></ns:partId>
              <ns:classType>0</ns:classType>
            </ns:GetMediaContentRequest>'''

            body = _soap_call(endpoint, 'getMediaContent', body_xml)
            media = []

            for el in body.iter():
                tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
                if tag == 'MediaContent' and 'Array' not in el.tag:
                    item = {'url': '', 'media_type': 'Image', 'width': None, 'height': None, 'color': '', 'description': ''}
                    for child in el.iter():
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
                    if item['url']:
                        media.append(item)

            logger.info(f"Got {len(media)} media items for {product_id}")
            return {'success': True, 'media': media}
        except (ConnectionError, ValueError) as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"getMediaContent error [{product_id}]: {e}")
            return {'success': False, 'error': str(e)}
