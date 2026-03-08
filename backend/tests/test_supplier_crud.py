"""
Test suite for Supplier CRUD operations and test-connection endpoint.
Tests multi-supplier support with PromoStandards SOAP APIs.
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known supplier IDs from review_request
ATC_SUPPLIER_ID = "0ebf9ad0-4022-4cc5-b204-e7ad070e0445"
SS_SUPPLIER_ID = "43cec498-e9b7-442f-bdde-d4d0711f7657"


class TestSupplierListAndGet:
    """Test GET /api/suppliers and GET /api/suppliers/{id}"""

    def test_list_suppliers_returns_200(self):
        """GET /api/suppliers should return list of suppliers"""
        response = requests.get(f"{BASE_URL}/api/suppliers")
        assert response.status_code == 200
        data = response.json()
        assert "suppliers" in data
        assert isinstance(data["suppliers"], list)
        print(f"✓ GET /api/suppliers - returned {len(data['suppliers'])} suppliers")

    def test_list_suppliers_masks_passwords(self):
        """Passwords should be masked in supplier list"""
        response = requests.get(f"{BASE_URL}/api/suppliers")
        assert response.status_code == 200
        data = response.json()
        for supplier in data["suppliers"]:
            if supplier.get("password"):
                assert supplier["password"] == "***", "Password should be masked"
            if supplier.get("media_password"):
                assert supplier["media_password"] == "***", "Media password should be masked"
        print("✓ Passwords are properly masked in response")

    def test_get_atc_supplier_by_id(self):
        """GET /api/suppliers/{id} - ATC supplier should exist"""
        response = requests.get(f"{BASE_URL}/api/suppliers/{ATC_SUPPLIER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == ATC_SUPPLIER_ID
        assert "supplier_name" in data
        assert data.get("endpoint_style") == "atc"
        print(f"✓ GET /api/suppliers/{ATC_SUPPLIER_ID} - Found: {data['supplier_name']}")

    def test_get_ss_supplier_by_id(self):
        """GET /api/suppliers/{id} - S&S supplier should exist"""
        response = requests.get(f"{BASE_URL}/api/suppliers/{SS_SUPPLIER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == SS_SUPPLIER_ID
        assert "supplier_name" in data
        assert data.get("endpoint_style") == "ss"
        print(f"✓ GET /api/suppliers/{SS_SUPPLIER_ID} - Found: {data['supplier_name']}")

    def test_get_nonexistent_supplier_returns_404(self):
        """GET /api/suppliers/{id} - Nonexistent ID should return 404"""
        fake_id = str(uuid.uuid4())
        response = requests.get(f"{BASE_URL}/api/suppliers/{fake_id}")
        assert response.status_code == 404
        print(f"✓ GET /api/suppliers/{fake_id} - Correctly returned 404")


class TestSupplierCreate:
    """Test POST /api/suppliers"""

    def test_create_supplier_minimal(self):
        """POST /api/suppliers - Create with minimal fields"""
        payload = {
            "supplier_name": f"TEST_MinimalSupplier_{uuid.uuid4().hex[:8]}",
            "endpoint_style": "custom"
        }
        response = requests.post(f"{BASE_URL}/api/suppliers", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["supplier_name"] == payload["supplier_name"]
        assert data["status"] == "active"
        print(f"✓ POST /api/suppliers - Created: {data['supplier_name']} (ID: {data['id']})")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{data['id']}")

    def test_create_supplier_with_auto_endpoint_discovery(self):
        """POST /api/suppliers - Endpoint style auto-generates service URLs"""
        payload = {
            "supplier_name": f"TEST_AutoEndpoints_{uuid.uuid4().hex[:8]}",
            "api_base_url": "https://example-promo.com",
            "endpoint_style": "ss",
            "account_number": "test123",
            "password": "testpass"
        }
        response = requests.post(f"{BASE_URL}/api/suppliers", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        # Check auto-generated endpoints for S&S style
        assert "services" in data
        services = data["services"]
        assert "product_data" in services
        assert "https://example-promo.com/ProductData/v2/ProductDataServicev2.svc" == services["product_data"]
        print(f"✓ POST /api/suppliers - Auto-discovered S&S endpoints correctly")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{data['id']}")

    def test_create_supplier_with_atc_style(self):
        """POST /api/suppliers - ATC endpoint style auto-discovery"""
        payload = {
            "supplier_name": f"TEST_ATCStyle_{uuid.uuid4().hex[:8]}",
            "api_base_url": "https://example-atc.com",
            "endpoint_style": "atc"
        }
        response = requests.post(f"{BASE_URL}/api/suppliers", json=payload)
        assert response.status_code == 200
        data = response.json()
        
        services = data.get("services", {})
        assert "product_data" in services
        assert "pstd/productdata2.0" in services["product_data"]
        print(f"✓ POST /api/suppliers - Auto-discovered ATC endpoints correctly")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{data['id']}")


class TestSupplierUpdate:
    """Test PUT /api/suppliers/{id}"""

    def test_update_supplier_name(self):
        """PUT /api/suppliers/{id} - Update supplier name"""
        # Create test supplier
        create_payload = {
            "supplier_name": f"TEST_ToUpdate_{uuid.uuid4().hex[:8]}"
        }
        create_response = requests.post(f"{BASE_URL}/api/suppliers", json=create_payload)
        assert create_response.status_code == 200
        supplier_id = create_response.json()["id"]
        
        # Update
        new_name = f"TEST_Updated_{uuid.uuid4().hex[:8]}"
        update_payload = {"supplier_name": new_name}
        update_response = requests.put(f"{BASE_URL}/api/suppliers/{supplier_id}", json=update_payload)
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["supplier_name"] == new_name
        
        # Verify persistence via GET
        get_response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}")
        assert get_response.status_code == 200
        assert get_response.json()["supplier_name"] == new_name
        print(f"✓ PUT /api/suppliers/{supplier_id} - Name updated and persisted")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}")

    def test_update_supplier_endpoint_style(self):
        """PUT /api/suppliers/{id} - Update endpoint_style"""
        # Create test supplier
        create_response = requests.post(f"{BASE_URL}/api/suppliers", json={
            "supplier_name": f"TEST_StyleUpdate_{uuid.uuid4().hex[:8]}",
            "endpoint_style": "atc"
        })
        supplier_id = create_response.json()["id"]
        
        # Update to different style
        update_response = requests.put(f"{BASE_URL}/api/suppliers/{supplier_id}", json={
            "endpoint_style": "alphabroder"
        })
        assert update_response.status_code == 200
        assert update_response.json()["endpoint_style"] == "alphabroder"
        print(f"✓ PUT /api/suppliers/{supplier_id} - endpoint_style updated")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}")

    def test_update_nonexistent_supplier_returns_404(self):
        """PUT /api/suppliers/{id} - Nonexistent ID should return 404"""
        fake_id = str(uuid.uuid4())
        response = requests.put(f"{BASE_URL}/api/suppliers/{fake_id}", json={"supplier_name": "Test"})
        assert response.status_code == 404
        print(f"✓ PUT /api/suppliers/{fake_id} - Correctly returned 404")


class TestSupplierDelete:
    """Test DELETE /api/suppliers/{id}"""

    def test_delete_supplier(self):
        """DELETE /api/suppliers/{id} - Delete supplier"""
        # Create
        create_response = requests.post(f"{BASE_URL}/api/suppliers", json={
            "supplier_name": f"TEST_ToDelete_{uuid.uuid4().hex[:8]}"
        })
        supplier_id = create_response.json()["id"]
        
        # Delete
        delete_response = requests.delete(f"{BASE_URL}/api/suppliers/{supplier_id}")
        assert delete_response.status_code == 200
        assert delete_response.json().get("status") == "deleted"
        
        # Verify gone
        get_response = requests.get(f"{BASE_URL}/api/suppliers/{supplier_id}")
        assert get_response.status_code == 404
        print(f"✓ DELETE /api/suppliers/{supplier_id} - Deleted and verified gone")

    def test_delete_nonexistent_supplier_returns_404(self):
        """DELETE /api/suppliers/{id} - Nonexistent ID should return 404"""
        fake_id = str(uuid.uuid4())
        response = requests.delete(f"{BASE_URL}/api/suppliers/{fake_id}")
        assert response.status_code == 404
        print(f"✓ DELETE /api/suppliers/{fake_id} - Correctly returned 404")


class TestTestConnection:
    """Test POST /api/suppliers/{id}/test-connection endpoint"""

    def test_connection_atc_supplier_success(self):
        """POST /api/suppliers/{id}/test-connection - ATC should connect successfully"""
        response = requests.post(f"{BASE_URL}/api/suppliers/{ATC_SUPPLIER_ID}/test-connection")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["connected"] == True
        assert "successful" in data.get("message", "").lower()
        print(f"✓ Test connection ATC - Success: {data['message']}")

    def test_connection_ss_supplier_blocked(self):
        """POST /api/suppliers/{id}/test-connection - S&S returns 403 (IP blocked)"""
        response = requests.post(f"{BASE_URL}/api/suppliers/{SS_SUPPLIER_ID}/test-connection")
        assert response.status_code == 200  # API returns 200 with error details
        data = response.json()
        assert data["success"] == False
        assert data["connected"] == False
        assert "403" in data.get("message", "") or "blocked" in data.get("message", "").lower()
        print(f"✓ Test connection S&S - Correctly reports blocked: {data['message']}")

    def test_connection_nonexistent_supplier_returns_404(self):
        """POST /api/suppliers/{id}/test-connection - Nonexistent ID returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/suppliers/{fake_id}/test-connection")
        assert response.status_code == 404
        print(f"✓ Test connection {fake_id} - Correctly returned 404")


class TestProductSync:
    """Test POST /api/sync/products/{supplier_id}"""

    def test_product_sync_trigger(self):
        """POST /api/sync/products/{id} - Triggers background sync for ATC"""
        response = requests.post(f"{BASE_URL}/api/sync/products/{ATC_SUPPLIER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "sync_log_id" in data
        assert data["status"] == "started"
        print(f"✓ Product sync triggered - Log ID: {data['sync_log_id']}")

    def test_product_sync_nonexistent_supplier(self):
        """POST /api/sync/products/{id} - Nonexistent ID returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/sync/products/{fake_id}")
        assert response.status_code == 404
        print(f"✓ Product sync {fake_id} - Correctly returned 404")


class TestProducts:
    """Test product-related endpoints"""

    def test_list_products(self):
        """GET /api/products - Returns paginated products"""
        response = requests.get(f"{BASE_URL}/api/products")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        print(f"✓ GET /api/products - {data['total']} products, page {data['page']}/{data['pages']}")

    def test_list_products_with_thumbnails(self):
        """GET /api/products - Products include thumbnail field"""
        response = requests.get(f"{BASE_URL}/api/products?limit=5")
        assert response.status_code == 200
        data = response.json()
        for product in data.get("products", []):
            assert "thumbnail" in product, "Product should have thumbnail field"
        print(f"✓ GET /api/products - All products have thumbnail field")

    def test_filter_products_by_supplier(self):
        """GET /api/products - Filter by supplier_id"""
        response = requests.get(f"{BASE_URL}/api/products", params={"supplier_id": ATC_SUPPLIER_ID})
        assert response.status_code == 200
        data = response.json()
        for product in data.get("products", []):
            assert product.get("supplier_id") == ATC_SUPPLIER_ID
        print(f"✓ GET /api/products?supplier_id={ATC_SUPPLIER_ID} - Filtered correctly")

    def test_get_categories(self):
        """GET /api/products/categories - Returns distinct categories"""
        response = requests.get(f"{BASE_URL}/api/products/categories")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert isinstance(data["categories"], list)
        print(f"✓ GET /api/products/categories - {len(data['categories'])} categories")

    def test_get_brands(self):
        """GET /api/products/brands - Returns distinct brands"""
        response = requests.get(f"{BASE_URL}/api/products/brands")
        assert response.status_code == 200
        data = response.json()
        assert "brands" in data
        assert isinstance(data["brands"], list)
        print(f"✓ GET /api/products/brands - {len(data['brands'])} brands")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
