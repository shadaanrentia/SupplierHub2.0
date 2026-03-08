import logging
import xmlrpc.client

logger = logging.getLogger(__name__)


class OdooConnector:
    """Odoo ERP integration via XML-RPC. Mock mode when no credentials."""

    def __init__(self, settings: dict):
        self.url = settings.get('odoo_url', '')
        self.db_name = settings.get('odoo_db', '')
        self.username = settings.get('odoo_username', '')
        self.api_key = settings.get('odoo_api_key', '')
        self.uid = None
        self.mock_mode = not all([self.url, self.db_name, self.username, self.api_key])
        if self.mock_mode:
            logger.info("Odoo connector: MOCK mode (no credentials)")

    def test_connection(self) -> dict:
        if self.mock_mode:
            return {
                'connected': False,
                'message': 'Odoo not configured. Set URL, database, username, and API key in Settings.',
                'mock_mode': True
            }
        try:
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            version = common.version()
            uid = common.authenticate(self.db_name, self.username, self.api_key, {})
            if uid:
                self.uid = uid
                return {'connected': True, 'message': f'Connected to Odoo {version.get("server_version", "?")}', 'mock_mode': False}
            return {'connected': False, 'message': 'Authentication failed', 'mock_mode': False}
        except Exception as e:
            return {'connected': False, 'message': str(e), 'mock_mode': False}

    def push_product(self, product: dict, variants: list, media: list) -> dict:
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
            existing = models.execute_kw(
                self.db_name, self.uid, self.api_key,
                'product.template', 'search_read',
                [[['default_code', '=', product.get('supplier_sku', '')]]],
                {'fields': ['id'], 'limit': 1}
            )
            vals = {
                'name': product.get('product_name', ''),
                'default_code': product.get('supplier_sku', ''),
                'description': product.get('description', ''),
                'list_price': product.get('base_price', 0),
                'type': 'product',
                'sale_ok': True,
                'purchase_ok': True,
            }
            if existing:
                odoo_id = existing[0]['id']
                models.execute_kw(self.db_name, self.uid, self.api_key, 'product.template', 'write', [[odoo_id], vals])
                return {'success': True, 'odoo_id': str(odoo_id), 'created': False}
            else:
                odoo_id = models.execute_kw(self.db_name, self.uid, self.api_key, 'product.template', 'create', [vals])
                return {'success': True, 'odoo_id': str(odoo_id), 'created': True}
        except Exception as e:
            logger.error(f"Odoo push error: {e}")
            return {'success': False, 'error': str(e)}
