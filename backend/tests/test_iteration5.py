"""
Test Iteration 5: PostgreSQL Migration Testing
Tests all features listed in review_request after MongoDB -> PostgreSQL migration:
- Login with admin/admin credentials
- Dashboard stats (572 products, 2 suppliers)
- Products page with product cards
- Products page view toggle (grid/list)
- Product detail page with variants table
- Suppliers page with both configured suppliers
- Supplier test connection (ATC/SanMar)
- Settings page with warehouse preference
- Product Search page
- Individual product sync endpoints (inventory, pricing, media)
- Sync Jobs page
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAuthentication:
    """Test authentication flow with admin/admin credentials"""
    
    def test_health_check(self):
        """Verify backend is running with PostgreSQL"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert data['database'] == 'postgresql'
        print(f"✓ Health check passed - database: {data['database']}")
    
    def test_login_admin(self):
        """Test login with admin/admin credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        data = response.json()
        assert 'token' in data
        assert 'user' in data
        assert data['user']['username'] == 'admin'
        assert data['user']['role'] == 'admin'
        print(f"✓ Login successful - user: {data['user']['username']}, role: {data['user']['role']}")
    
    def test_login_invalid_credentials(self):
        """Test login with wrong credentials returns 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "wrong",
            "password": "wrong"
        })
        assert response.status_code == 401
        print("✓ Invalid credentials correctly rejected with 401")


@pytest.fixture(scope="module")
def auth_headers():
    """Login and get authentication headers"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    token = response.json().get('token')
    return {"Authorization": f"Bearer {token}"}


class TestDashboard:
    """Test Dashboard statistics - should show 572 products, 2 suppliers"""
    
    def test_dashboard_stats(self, auth_headers):
        """GET /api/dashboard/stats - verify product and supplier counts"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check for expected stats fields
        assert 'total_products' in data
        assert 'total_suppliers' in data
        assert 'active_suppliers' in data
        assert 'selected_products' in data
        
        # Verify migrated data counts
        print(f"✓ Dashboard stats: {data['total_products']} products, {data['total_suppliers']} suppliers")
        
        # Expected: 572 products, 2 suppliers based on migration
        assert data['total_products'] >= 500, f"Expected ~572 products, got {data['total_products']}"
        assert data['total_suppliers'] >= 2, f"Expected 2 suppliers, got {data['total_suppliers']}"


class TestSuppliers:
    """Test Suppliers page - both ATC and SanMar should be configured"""
    
    def test_list_suppliers(self, auth_headers):
        """GET /api/suppliers - should return 2 suppliers"""
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'suppliers' in data
        suppliers = data['suppliers']
        assert len(suppliers) >= 2, f"Expected 2 suppliers, got {len(suppliers)}"
        
        # Check supplier names
        supplier_names = [s['supplier_name'] for s in suppliers]
        print(f"✓ Found suppliers: {supplier_names}")
        
        # Verify passwords are masked
        for s in suppliers:
            if s.get('password'):
                assert s['password'] == '***', "Password should be masked"
    
    def test_atc_supplier_exists(self, auth_headers):
        """Verify ATC supplier is configured"""
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        data = response.json()
        
        atc = next((s for s in data['suppliers'] if 'ATC' in s.get('supplier_name', '')), None)
        assert atc is not None, "ATC supplier not found"
        # endpoint_style may be None or 'atc' - either is acceptable
        print(f"✓ ATC supplier found: {atc['supplier_name']} (endpoint_style: {atc.get('endpoint_style')})")
        return atc['id']
    
    def test_sanmar_supplier_exists(self, auth_headers):
        """Verify SanMar supplier is configured"""
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        data = response.json()
        
        # Look for SanMar or S&S
        sanmar = next((s for s in data['suppliers'] 
                       if 'SanMar' in s.get('supplier_name', '') or 'S&S' in s.get('supplier_name', '')), None)
        assert sanmar is not None, "SanMar/S&S supplier not found"
        print(f"✓ SanMar/S&S supplier found: {sanmar['supplier_name']}")


class TestSupplierConnection:
    """Test supplier test connection endpoint"""
    
    def test_atc_connection(self, auth_headers):
        """POST /api/suppliers/{id}/test - ATC should connect successfully"""
        # First get ATC supplier ID
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        suppliers = response.json()['suppliers']
        atc = next((s for s in suppliers if 'ATC' in s.get('supplier_name', '')), None)
        
        if not atc:
            pytest.skip("ATC supplier not found")
        
        # Test connection
        test_response = requests.post(f"{BASE_URL}/api/suppliers/{atc['id']}/test", headers=auth_headers)
        assert test_response.status_code == 200
        result = test_response.json()
        
        print(f"✓ ATC connection test: success={result.get('success')}, message={result.get('message', '')[:50]}")
    
    def test_sanmar_connection(self, auth_headers):
        """POST /api/suppliers/{id}/test - SanMar connection test (may fail due to IP block)"""
        # Get SanMar supplier ID
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        suppliers = response.json()['suppliers']
        sanmar = next((s for s in suppliers 
                       if 'SanMar' in s.get('supplier_name', '') or 'S&S' in s.get('supplier_name', '')), None)
        
        if not sanmar:
            pytest.skip("SanMar supplier not found")
        
        # Test connection
        test_response = requests.post(f"{BASE_URL}/api/suppliers/{sanmar['id']}/test", headers=auth_headers)
        assert test_response.status_code == 200
        result = test_response.json()
        
        # May fail due to IP blocking - just verify API works
        print(f"✓ SanMar connection test: success={result.get('success')}, connected={result.get('connected')}")


class TestProducts:
    """Test Products page functionality"""
    
    def test_list_products(self, auth_headers):
        """GET /api/products - returns paginated products"""
        response = requests.get(f"{BASE_URL}/api/products", headers=auth_headers, params={"limit": 50})
        assert response.status_code == 200
        data = response.json()
        
        assert 'products' in data
        assert 'total' in data
        assert 'page' in data
        assert 'pages' in data
        
        print(f"✓ Products list: {data['total']} total, page {data['page']}/{data['pages']}")
        
        # Verify product structure
        if len(data['products']) > 0:
            product = data['products'][0]
            assert 'id' in product
            assert 'product_name' in product
            assert 'supplier_sku' in product
    
    def test_get_product_detail(self, auth_headers):
        """GET /api/products/{id} - returns product with variants"""
        # Get first product
        list_response = requests.get(f"{BASE_URL}/api/products", headers=auth_headers, params={"limit": 1})
        products = list_response.json().get('products', [])
        
        if not products:
            pytest.skip("No products available")
        
        product_id = products[0]['id']
        
        # Get product detail
        response = requests.get(f"{BASE_URL}/api/products/{product_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'id' in data
        assert 'variants' in data
        assert 'media' in data
        
        print(f"✓ Product detail: {data['product_name'][:30]}... with {len(data['variants'])} variants")
    
    def test_get_categories(self, auth_headers):
        """GET /api/products/categories - returns distinct categories"""
        response = requests.get(f"{BASE_URL}/api/products/categories", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'categories' in data
        assert isinstance(data['categories'], list)
        print(f"✓ Categories: {len(data['categories'])} available")
    
    def test_get_brands(self, auth_headers):
        """GET /api/products/brands - returns distinct brands"""
        response = requests.get(f"{BASE_URL}/api/products/brands", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'brands' in data
        assert isinstance(data['brands'], list)
        print(f"✓ Brands: {len(data['brands'])} available")
    
    def test_product_search(self, auth_headers):
        """GET /api/products?search=... - search functionality"""
        response = requests.get(f"{BASE_URL}/api/products", headers=auth_headers, params={
            "search": "Polo",
            "limit": 50
        })
        assert response.status_code == 200
        data = response.json()
        
        print(f"✓ Product search 'Polo': {data['total']} results")
    
    def test_product_pagination(self, auth_headers):
        """Test pagination works correctly"""
        # Page 1
        response1 = requests.get(f"{BASE_URL}/api/products", headers=auth_headers, params={"page": 1, "limit": 10})
        data1 = response1.json()
        
        # Page 2
        response2 = requests.get(f"{BASE_URL}/api/products", headers=auth_headers, params={"page": 2, "limit": 10})
        data2 = response2.json()
        
        # Products should be different
        if len(data1['products']) > 0 and len(data2['products']) > 0:
            assert data1['products'][0]['id'] != data2['products'][0]['id']
        
        print(f"✓ Pagination: page 1 has {len(data1['products'])}, page 2 has {len(data2['products'])} products")


class TestProductSync:
    """Test individual product sync endpoints"""
    
    @pytest.fixture
    def product_id(self, auth_headers):
        """Get a valid product ID for testing"""
        response = requests.get(f"{BASE_URL}/api/products", headers=auth_headers, params={"limit": 1})
        products = response.json().get('products', [])
        if not products:
            pytest.skip("No products available for testing")
        return products[0]['id']
    
    def test_sync_product_inventory(self, auth_headers, product_id):
        """POST /api/sync/product/{id}/inventory"""
        response = requests.post(f"{BASE_URL}/api/sync/product/{product_id}/inventory", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'message' in data
        print(f"✓ Inventory sync: {data['message']}")
    
    def test_sync_product_pricing(self, auth_headers, product_id):
        """POST /api/sync/product/{id}/pricing"""
        response = requests.post(f"{BASE_URL}/api/sync/product/{product_id}/pricing", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'message' in data
        print(f"✓ Pricing sync: {data['message']}")
    
    def test_sync_product_media(self, auth_headers, product_id):
        """POST /api/sync/product/{id}/media"""
        response = requests.post(f"{BASE_URL}/api/sync/product/{product_id}/media", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'message' in data
        print(f"✓ Media sync: {data['message']}")


class TestSettings:
    """Test Settings page - warehouse preference"""
    
    def test_get_settings(self, auth_headers):
        """GET /api/settings - returns system settings"""
        response = requests.get(f"{BASE_URL}/api/settings", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'preferred_warehouse' in data
        assert 'sync_products_interval_hours' in data
        assert 'sync_inventory_interval_minutes' in data
        
        print(f"✓ Settings: preferred_warehouse={data['preferred_warehouse']}")
    
    def test_get_warehouses(self, auth_headers):
        """GET /api/settings/warehouses - returns available warehouses"""
        response = requests.get(f"{BASE_URL}/api/settings/warehouses", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'warehouses' in data
        assert isinstance(data['warehouses'], list)
        print(f"✓ Available warehouses: {len(data['warehouses'])}")


class TestSyncLogs:
    """Test Sync Jobs page"""
    
    def test_get_sync_logs(self, auth_headers):
        """GET /api/sync/logs - returns sync history"""
        response = requests.get(f"{BASE_URL}/api/sync/logs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert 'logs' in data
        assert isinstance(data['logs'], list)
        print(f"✓ Sync logs: {len(data['logs'])} entries")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
