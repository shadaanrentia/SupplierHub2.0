"""
Backend API Tests - Iteration 6
Testing all backend endpoints as specified in review request:
- Health check endpoint
- Admin login with admin/admin
- Supplier CRUD operations
- Dashboard stats endpoint
- Products list endpoint
- Settings endpoint
- Media proxy endpoint (domain validation)
- Sync logs endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestHealthCheck:
    """Test health check endpoint"""
    
    def test_health_endpoint_returns_200(self):
        """Health check should return 200 with status healthy"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "healthy", f"Expected status 'healthy', got {data.get('status')}"
        assert "database" in data, "Response should contain 'database' key"
        assert "timestamp" in data, "Response should contain 'timestamp' key"
        print(f"Health check passed: {data}")


class TestAuthentication:
    """Test admin login functionality"""
    
    def test_admin_login_success(self):
        """Admin login with admin/admin should return token and user data"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "token" in data, "Response should contain 'token'"
        assert "user" in data, "Response should contain 'user'"
        assert data["user"]["username"] == "admin", f"Expected username 'admin', got {data['user']['username']}"
        assert data["user"]["role"] == "admin", f"Expected role 'admin', got {data['user']['role']}"
        print(f"Admin login successful: token length={len(data['token'])}, user={data['user']['username']}")
    
    def test_login_invalid_credentials(self):
        """Invalid credentials should return 401"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "username": "wrong_user",
            "password": "wrong_pass"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("Invalid credentials test passed: 401 returned as expected")


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for tests that require it"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Could not authenticate - skipping authenticated tests")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestSupplierCRUD:
    """Test Supplier CRUD operations"""
    
    def test_get_suppliers_list(self, auth_headers):
        """Should return list of suppliers"""
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "suppliers" in data, "Response should contain 'suppliers' key"
        assert isinstance(data["suppliers"], list), "Suppliers should be a list"
        print(f"Get suppliers passed: {len(data['suppliers'])} suppliers found")
        
        # Verify supplier data structure if any suppliers exist
        if len(data["suppliers"]) > 0:
            supplier = data["suppliers"][0]
            assert "id" in supplier, "Supplier should have 'id'"
            assert "supplier_name" in supplier, "Supplier should have 'supplier_name'"
            print(f"First supplier: {supplier.get('supplier_name')}")
    
    def test_create_supplier(self, auth_headers):
        """Should create a new supplier successfully"""
        test_supplier = {
            "supplier_name": "TEST_Supplier_Iteration6",
            "api_base_url": "https://test.promostandards.org",
            "account_number": "TEST123",
            "password": "testpass",
            "media_password": "mediapass",
            "use_uat": True,
            "services": {
                "product_data": "https://test.promostandards.org/product"
            },
            "endpoint_style": "generic"
        }
        
        response = requests.post(f"{BASE_URL}/api/suppliers", json=test_supplier, headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "id" in data, "Response should contain 'id'"
        assert "message" in data, "Response should contain 'message'"
        print(f"Create supplier passed: id={data['id']}")
        
        # Store supplier_id for cleanup
        return data["id"]
    
    def test_get_supplier_by_id(self, auth_headers):
        """Should get supplier details by ID"""
        # First get list of suppliers
        list_response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        suppliers = list_response.json().get("suppliers", [])
        
        if not suppliers:
            pytest.skip("No suppliers available to test")
        
        supplier_id = suppliers[0]["id"]
        response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["id"] == supplier_id, f"Expected id {supplier_id}, got {data.get('id')}"
        assert "supplier_name" in data, "Response should contain 'supplier_name'"
        print(f"Get supplier by ID passed: {data.get('supplier_name')}")


class TestDashboardStats:
    """Test dashboard stats endpoint"""
    
    def test_dashboard_stats_returns_correct_format(self, auth_headers):
        """Dashboard stats should return all required fields"""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check all required fields exist
        required_fields = [
            "total_products",
            "selected_products", 
            "total_suppliers",
            "active_suppliers",
            "synced_products",
            "pending_products",
            "total_variants",
            "active_products"
        ]
        
        for field in required_fields:
            assert field in data, f"Dashboard stats should contain '{field}'"
            assert isinstance(data[field], int), f"'{field}' should be an integer"
        
        print(f"Dashboard stats passed: products={data['total_products']}, suppliers={data['total_suppliers']}, variants={data['total_variants']}")


class TestProductsEndpoint:
    """Test products list endpoint"""
    
    def test_products_list_returns_paginated_data(self, auth_headers):
        """Products list should return paginated data with correct structure"""
        response = requests.get(f"{BASE_URL}/api/products", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check pagination fields
        assert "products" in data, "Response should contain 'products'"
        assert "total" in data, "Response should contain 'total'"
        assert "page" in data, "Response should contain 'page'"
        assert "limit" in data, "Response should contain 'limit'"
        assert "pages" in data, "Response should contain 'pages'"
        
        assert isinstance(data["products"], list), "Products should be a list"
        print(f"Products list passed: {len(data['products'])} products on page {data['page']} of {data['pages']}")
        
        # Check product structure if any exist
        if len(data["products"]) > 0:
            product = data["products"][0]
            assert "id" in product, "Product should have 'id'"
            assert "product_name" in product, "Product should have 'product_name'"
            assert "supplier_sku" in product, "Product should have 'supplier_sku'"
            print(f"First product: {product.get('product_name')[:50]}...")
    
    def test_products_pagination_works(self, auth_headers):
        """Products pagination should work correctly"""
        # Test page 1
        response1 = requests.get(f"{BASE_URL}/api/products?page=1&limit=10", headers=auth_headers)
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Test page 2 if there are enough products
        if data1["pages"] > 1:
            response2 = requests.get(f"{BASE_URL}/api/products?page=2&limit=10", headers=auth_headers)
            assert response2.status_code == 200
            data2 = response2.json()
            
            # Products on page 2 should be different from page 1
            if data1["products"] and data2["products"]:
                assert data1["products"][0]["id"] != data2["products"][0]["id"], "Page 2 should have different products"
            print("Pagination test passed: different products on different pages")
        else:
            print("Pagination test skipped: only one page of products")


class TestSettingsEndpoint:
    """Test settings endpoint"""
    
    def test_get_settings_returns_correct_structure(self, auth_headers):
        """Settings should return all configuration fields"""
        response = requests.get(f"{BASE_URL}/api/settings", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Check required settings fields
        expected_fields = [
            "sync_products_interval_hours",
            "sync_inventory_interval_minutes",
            "sync_pricing_interval_hours",
            "auto_sync_enabled",
            "preferred_warehouse"
        ]
        
        for field in expected_fields:
            assert field in data, f"Settings should contain '{field}'"
        
        # Odoo fields should exist but api_key should be masked
        assert "odoo_url" in data, "Settings should contain 'odoo_url'"
        assert "odoo_db" in data, "Settings should contain 'odoo_db'"
        
        print(f"Settings passed: preferred_warehouse={data.get('preferred_warehouse')}, auto_sync={data.get('auto_sync_enabled')}")


class TestMediaProxyEndpoint:
    """Test media proxy endpoint domain validation"""
    
    def test_media_proxy_exists(self, auth_headers):
        """Media proxy endpoint should exist"""
        # Test without URL parameter - should return 422 (validation error) or 400
        response = requests.get(f"{BASE_URL}/api/media_proxy", headers=auth_headers)
        # Without URL parameter, it should return an error (400 or 422)
        assert response.status_code in [400, 422], f"Expected 400 or 422 without URL param, got {response.status_code}"
        print(f"Media proxy endpoint exists, returns {response.status_code} without URL param")
    
    def test_media_proxy_validates_domain(self, auth_headers):
        """Media proxy should validate URL domain"""
        # Test with disallowed domain
        test_url = "https://evil-domain.com/image.jpg"
        response = requests.get(f"{BASE_URL}/api/media_proxy?url={test_url}", headers=auth_headers)
        assert response.status_code == 403, f"Expected 403 for disallowed domain, got {response.status_code}"
        print("Media proxy domain validation passed: blocks disallowed domains")
    
    def test_media_proxy_allows_valid_domains(self, auth_headers):
        """Media proxy should allow valid supplier domains (domain passes validation)"""
        # Test with allowed domain - domain validation passes, but actual fetch may fail (CDN blocking)
        # The key test is that we don't get "Domain not allowed" error message
        allowed_domains = ['cdn-atc.ca', 'cdn.ssactivewear.com', 'media.alphabroder.com']
        
        for domain in allowed_domains:
            test_url = f"https://{domain}/test-image.jpg"
            response = requests.get(f"{BASE_URL}/api/media_proxy?url={test_url}", headers=auth_headers)
            # Check the error message - if domain validation failed, it would say "Domain not allowed"
            # Other errors (403 from CDN, 404, etc.) mean domain validation passed
            if response.status_code == 403:
                detail = response.json().get("detail", "")
                # Domain validation error says "Domain not allowed", CDN block says "Failed to fetch"
                assert "Domain not allowed" not in detail, f"Domain {domain} should be allowed but got validation error"
                print(f"Domain {domain} passes validation (CDN returns 403 - bot protection)")
            else:
                print(f"Domain {domain} is allowed (status: {response.status_code})")


class TestSyncLogsEndpoint:
    """Test sync logs endpoint"""
    
    def test_get_sync_logs_returns_correct_structure(self, auth_headers):
        """Sync logs should return list with correct structure"""
        response = requests.get(f"{BASE_URL}/api/sync/logs", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "logs" in data, "Response should contain 'logs'"
        assert isinstance(data["logs"], list), "Logs should be a list"
        print(f"Sync logs passed: {len(data['logs'])} logs found")
        
        # Check log structure if any exist
        if len(data["logs"]) > 0:
            log = data["logs"][0]
            expected_fields = ["id", "sync_type", "status", "message"]
            for field in expected_fields:
                assert field in log, f"Log should contain '{field}'"
            print(f"First log: type={log.get('sync_type')}, status={log.get('status')}")
    
    def test_sync_logs_filter_by_type(self, auth_headers):
        """Sync logs should support filtering by sync_type"""
        # Test filtering by sync_type
        response = requests.get(f"{BASE_URL}/api/sync/logs?sync_type=products", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("Sync logs filter by type passed")


class TestCleanup:
    """Cleanup test data"""
    
    def test_cleanup_test_suppliers(self, auth_headers):
        """Remove TEST_ prefixed suppliers created during tests"""
        # Get all suppliers
        response = requests.get(f"{BASE_URL}/api/suppliers", headers=auth_headers)
        if response.status_code == 200:
            suppliers = response.json().get("suppliers", [])
            for supplier in suppliers:
                if supplier.get("supplier_name", "").startswith("TEST_"):
                    delete_response = requests.delete(
                        f"{BASE_URL}/api/suppliers/{supplier['id']}", 
                        headers=auth_headers
                    )
                    print(f"Cleaned up test supplier: {supplier['supplier_name']} (status: {delete_response.status_code})")
        print("Cleanup completed")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
