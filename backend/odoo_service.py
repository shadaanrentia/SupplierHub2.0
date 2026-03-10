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
        """Create or update a product in Odoo."""
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

            models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            
            # Search for existing product by SKU
            existing = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.template', 'search_read',
                [[['default_code', '=', product.get('supplier_sku', '')]]],
                {'fields': ['id'], 'limit': 1}
            )
            
            # Prepare product values
            vals = {
                'name': product.get('product_name', ''),
                'default_code': product.get('supplier_sku', ''),
                'description': product.get('description', ''),
                'list_price': float(product.get('base_price', 0) or 0),
                'type': 'product',
                'sale_ok': True,
                'purchase_ok': True,
            }
            
            if existing:
                # Update existing product
                odoo_id = existing[0]['id']
                models.execute_kw(self.db_name, self.uid, self.api_key, 'product.template', 'write', [[odoo_id], vals])
                return {'success': True, 'odoo_id': str(odoo_id), 'created': False}
            else:
                # Create new product
                odoo_id = models.execute_kw(self.db_name, self.uid, self.api_key, 'product.template', 'create', [vals])
                return {'success': True, 'odoo_id': str(odoo_id), 'created': True}
                
        except xmlrpc.client.Fault as e:
            logger.error(f"Odoo API error: {e.faultString}")
            return {'success': False, 'error': f'Odoo API error: {e.faultString}'}
        except Exception as e:
            logger.error(f"Odoo push error: {e}")
            return {'success': False, 'error': str(e)}
