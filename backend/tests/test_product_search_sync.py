"""
Test Product Search and Individual Product Sync Endpoints
Tests the new features added in iteration 4:
- Individual product sync (pricing, inventory, media)
- Bulk sync endpoint
- Product search page APIs
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestProductSync:
    """Test individual product sync endpoints"""
    
    @pytest.fixture
    def product_id(self):
        """Get a valid product ID for testing"""
        response = requests.get(f"{BASE_URL}/api/products", params={"limit": 1})
        assert response.status_code == 200
        products = response.json().get('products', [])
        assert len(products) > 0, "No products available for testing"
        return products[0]['id']
    
    @pytest.fixture
    def auth_token(self):
        """Login and get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        return response.json().get('token')
    
    def test_sync_product_pricing(self, product_id):
        """Test POST /api/sync/product/{product_id}/pricing"""
        response = requests.post(f"{BASE_URL}/api/sync/product/{product_id}/pricing")
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'message' in data
        print(f"Pricing sync result: {data}")
    
    def test_sync_product_inventory(self, product_id):
        """Test POST /api/sync/product/{product_id}/inventory"""
        response = requests.post(f"{BASE_URL}/api/sync/product/{product_id}/inventory")
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'message' in data
        print(f"Inventory sync result: {data}")
    
    def test_sync_product_media(self, product_id):
        """Test POST /api/sync/product/{product_id}/media"""
        response = requests.post(f"{BASE_URL}/api/sync/product/{product_id}/media")
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'message' in data
        print(f"Media sync result: {data}")
    
    def test_sync_product_not_found(self):
        """Test sync endpoints with invalid product ID"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        
        # Test pricing
        response = requests.post(f"{BASE_URL}/api/sync/product/{fake_id}/pricing")
        assert response.status_code == 404
        
        # Test inventory
        response = requests.post(f"{BASE_URL}/api/sync/product/{fake_id}/inventory")
        assert response.status_code == 404
        
        # Test media
        response = requests.post(f"{BASE_URL}/api/sync/product/{fake_id}/media")
        assert response.status_code == 404


class TestBulkSync:
    """Test bulk product sync endpoint"""
    
    @pytest.fixture
    def product_ids(self):
        """Get valid product IDs for testing"""
        response = requests.get(f"{BASE_URL}/api/products", params={"limit": 3})
        assert response.status_code == 200
        products = response.json().get('products', [])
        assert len(products) >= 2, "Need at least 2 products for bulk testing"
        return [p['id'] for p in products[:3]]
    
    def test_bulk_sync_pricing(self, product_ids):
        """Test POST /api/sync/products/bulk?sync_type=pricing"""
        response = requests.post(
            f"{BASE_URL}/api/sync/products/bulk",
            params={"sync_type": "pricing"},
            json=product_ids
        )
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'failed' in data
        assert 'errors' in data
        print(f"Bulk pricing sync: success={data['success']}, failed={data['failed']}")
    
    def test_bulk_sync_inventory(self, product_ids):
        """Test POST /api/sync/products/bulk?sync_type=inventory"""
        response = requests.post(
            f"{BASE_URL}/api/sync/products/bulk",
            params={"sync_type": "inventory"},
            json=product_ids
        )
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'failed' in data
        print(f"Bulk inventory sync: success={data['success']}, failed={data['failed']}")
    
    def test_bulk_sync_media(self, product_ids):
        """Test POST /api/sync/products/bulk?sync_type=media"""
        response = requests.post(
            f"{BASE_URL}/api/sync/products/bulk",
            params={"sync_type": "media"},
            json=product_ids
        )
        assert response.status_code == 200
        data = response.json()
        assert 'success' in data
        assert 'failed' in data
        print(f"Bulk media sync: success={data['success']}, failed={data['failed']}")
    
    def test_bulk_sync_invalid_type(self, product_ids):
        """Test bulk sync with invalid sync type"""
        response = requests.post(
            f"{BASE_URL}/api/sync/products/bulk",
            params={"sync_type": "invalid"},
            json=product_ids
        )
        assert response.status_code == 422  # Validation error


class TestProductSearch:
    """Test Product Search page API functionality"""
    
    @pytest.fixture
    def supplier_id(self):
        """Get ATC supplier ID"""
        response = requests.get(f"{BASE_URL}/api/suppliers")
        assert response.status_code == 200
        suppliers = response.json().get('suppliers', [])
        atc = next((s for s in suppliers if 'ATC' in s.get('supplier_name', '')), None)
        assert atc is not None, "ATC supplier not found"
        return atc['id']
    
    def test_search_products_by_supplier(self, supplier_id):
        """Test searching products filtered by supplier"""
        response = requests.get(f"{BASE_URL}/api/products", params={
            "supplier_id": supplier_id,
            "search": "Polo",
            "limit": 100
        })
        assert response.status_code == 200
        data = response.json()
        assert 'products' in data
        assert 'total' in data
        print(f"Search 'Polo' in ATC: {data['total']} products found")
        
        # Verify all products are from the selected supplier
        for product in data.get('products', []):
            assert product.get('supplier_id') == supplier_id
    
    def test_search_products_no_supplier(self):
        """Test search without supplier returns all matching products"""
        response = requests.get(f"{BASE_URL}/api/products", params={
            "search": "Shirt",
            "limit": 50
        })
        assert response.status_code == 200
        data = response.json()
        assert 'products' in data
        print(f"Search 'Shirt' (all suppliers): {data['total']} products found")


class TestProductsPageFilters:
    """Test Products page filter and view APIs"""
    
    def test_get_categories(self):
        """Test GET /api/products/categories"""
        response = requests.get(f"{BASE_URL}/api/products/categories")
        assert response.status_code == 200
        data = response.json()
        assert 'categories' in data
        assert isinstance(data['categories'], list)
        print(f"Categories available: {len(data['categories'])}")
    
    def test_get_brands(self):
        """Test GET /api/products/brands"""
        response = requests.get(f"{BASE_URL}/api/products/brands")
        assert response.status_code == 200
        data = response.json()
        assert 'brands' in data
        assert isinstance(data['brands'], list)
        print(f"Brands available: {len(data['brands'])}")
    
    def test_pagination(self):
        """Test product pagination"""
        # Get first page
        response1 = requests.get(f"{BASE_URL}/api/products", params={"page": 1, "limit": 10})
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Get second page
        response2 = requests.get(f"{BASE_URL}/api/products", params={"page": 2, "limit": 10})
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Products should be different
        if len(data1['products']) > 0 and len(data2['products']) > 0:
            assert data1['products'][0]['id'] != data2['products'][0]['id']
        
        print(f"Pagination: page 1 has {len(data1['products'])}, page 2 has {len(data2['products'])} products")


class TestAuthentication:
    """Test authentication flow"""
    
    def test_login_admin(self):
        """Test login with admin credentials"""
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
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "wrong",
            "password": "wrong"
        })
        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
