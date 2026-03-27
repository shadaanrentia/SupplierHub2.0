"""
Backend API tests for Scheduler and Settings features - Iteration 7
Tests:
- GET /api/scheduler/status - scheduler running status and jobs list
- PUT /api/settings - enable/disable auto_sync and auto_push_to_odoo
- POST /api/scheduler/reschedule - reschedule jobs
- GET /api/dashboard/stats - dashboard statistics
- GET /api/users - user list
- POST /api/users - create new user
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSchedulerAndSettings:
    """Test scheduler and settings endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - get auth token"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        login_res = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        yield
        
    def test_01_scheduler_status_endpoint(self):
        """GET /api/scheduler/status returns scheduler running status and jobs list"""
        res = self.session.get(f"{BASE_URL}/api/scheduler/status")
        assert res.status_code == 200, f"Scheduler status failed: {res.text}"
        data = res.json()
        
        # Verify response structure
        assert "running" in data, "Response should have 'running' field"
        assert "jobs" in data, "Response should have 'jobs' field"
        assert isinstance(data["running"], bool), "'running' should be boolean"
        assert isinstance(data["jobs"], list), "'jobs' should be a list"
        print(f"Scheduler status: running={data['running']}, jobs_count={len(data['jobs'])}")
        
    def test_02_enable_auto_sync_creates_jobs(self):
        """PUT /api/settings with auto_sync_enabled=true creates 3 scheduler jobs"""
        # First disable auto_sync to ensure clean state
        disable_res = self.session.put(f"{BASE_URL}/api/settings", json={
            "auto_sync_enabled": False
        })
        assert disable_res.status_code == 200
        
        # Check scheduler has no jobs
        status_res = self.session.get(f"{BASE_URL}/api/scheduler/status")
        assert status_res.status_code == 200
        initial_jobs = status_res.json().get("jobs", [])
        print(f"Initial jobs count (after disable): {len(initial_jobs)}")
        
        # Enable auto_sync
        enable_res = self.session.put(f"{BASE_URL}/api/settings", json={
            "auto_sync_enabled": True,
            "sync_products_interval_hours": 24,
            "sync_inventory_interval_minutes": 30,
            "sync_pricing_interval_hours": 12
        })
        assert enable_res.status_code == 200, f"Enable auto_sync failed: {enable_res.text}"
        
        # Check scheduler now has 3 jobs
        status_res = self.session.get(f"{BASE_URL}/api/scheduler/status")
        assert status_res.status_code == 200
        data = status_res.json()
        jobs = data.get("jobs", [])
        
        assert len(jobs) == 3, f"Expected 3 jobs, got {len(jobs)}"
        job_ids = [j["id"] for j in jobs]
        assert "auto_sync_products" in job_ids, "Missing auto_sync_products job"
        assert "auto_sync_inventory" in job_ids, "Missing auto_sync_inventory job"
        assert "auto_sync_pricing" in job_ids, "Missing auto_sync_pricing job"
        
        # Verify each job has required fields
        for job in jobs:
            assert "id" in job, "Job should have 'id'"
            assert "name" in job, "Job should have 'name'"
            assert "next_run" in job, "Job should have 'next_run'"
            assert "trigger" in job, "Job should have 'trigger'"
            print(f"Job: {job['id']} - next_run: {job['next_run']}")
        
        print("Auto-sync enabled successfully with 3 jobs")
        
    def test_03_disable_auto_sync_removes_jobs(self):
        """PUT /api/settings with auto_sync_enabled=false removes all scheduler jobs"""
        # First ensure auto_sync is enabled
        self.session.put(f"{BASE_URL}/api/settings", json={"auto_sync_enabled": True})
        
        # Disable auto_sync
        disable_res = self.session.put(f"{BASE_URL}/api/settings", json={
            "auto_sync_enabled": False
        })
        assert disable_res.status_code == 200, f"Disable auto_sync failed: {disable_res.text}"
        
        # Check scheduler has no jobs
        status_res = self.session.get(f"{BASE_URL}/api/scheduler/status")
        assert status_res.status_code == 200
        data = status_res.json()
        jobs = data.get("jobs", [])
        
        assert len(jobs) == 0, f"Expected 0 jobs after disable, got {len(jobs)}"
        assert data["running"] == True, "Scheduler should still be running"
        print("Auto-sync disabled successfully, all jobs removed")
        
    def test_04_reschedule_endpoint(self):
        """POST /api/scheduler/reschedule works and returns status"""
        # Enable auto_sync first
        self.session.put(f"{BASE_URL}/api/settings", json={"auto_sync_enabled": True})
        
        # Call reschedule
        res = self.session.post(f"{BASE_URL}/api/scheduler/reschedule")
        assert res.status_code == 200, f"Reschedule failed: {res.text}"
        data = res.json()
        
        assert "status" in data, "Response should have 'status'"
        assert data["status"] == "rescheduled", f"Expected 'rescheduled', got {data['status']}"
        assert "running" in data, "Response should have 'running'"
        assert "jobs" in data, "Response should have 'jobs'"
        print(f"Reschedule successful: {len(data['jobs'])} jobs")
        
    def test_05_auto_push_to_odoo_setting(self):
        """auto_push_to_odoo setting is persisted correctly"""
        # Enable auto_push_to_odoo
        enable_res = self.session.put(f"{BASE_URL}/api/settings", json={
            "auto_push_to_odoo": True
        })
        assert enable_res.status_code == 200
        
        # Verify it's persisted
        get_res = self.session.get(f"{BASE_URL}/api/settings")
        assert get_res.status_code == 200
        data = get_res.json()
        assert data.get("auto_push_to_odoo") == True, "auto_push_to_odoo should be True"
        print("auto_push_to_odoo enabled and persisted")
        
        # Disable auto_push_to_odoo
        disable_res = self.session.put(f"{BASE_URL}/api/settings", json={
            "auto_push_to_odoo": False
        })
        assert disable_res.status_code == 200
        
        # Verify it's persisted
        get_res = self.session.get(f"{BASE_URL}/api/settings")
        assert get_res.status_code == 200
        data = get_res.json()
        assert data.get("auto_push_to_odoo") == False, "auto_push_to_odoo should be False"
        print("auto_push_to_odoo disabled and persisted")
        
    def test_06_dashboard_stats(self):
        """GET /api/dashboard/stats returns statistics data"""
        res = self.session.get(f"{BASE_URL}/api/dashboard/stats")
        assert res.status_code == 200, f"Dashboard stats failed: {res.text}"
        data = res.json()
        
        # Verify required fields
        required_fields = [
            "total_products", "selected_for_odoo", "synced_to_odoo",
            "total_suppliers", "active_suppliers", "pending_products",
            "total_variants", "active_products",
            "category_distribution", "brand_distribution", "supplier_distribution"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # Verify distribution arrays
        assert isinstance(data["category_distribution"], list)
        assert isinstance(data["brand_distribution"], list)
        assert isinstance(data["supplier_distribution"], list)
        
        print(f"Dashboard stats: products={data['total_products']}, suppliers={data['total_suppliers']}, variants={data['total_variants']}")
        
    def test_07_get_users(self):
        """GET /api/users returns user list"""
        res = self.session.get(f"{BASE_URL}/api/users")
        assert res.status_code == 200, f"Get users failed: {res.text}"
        data = res.json()
        
        assert "users" in data, "Response should have 'users'"
        users = data["users"]
        assert isinstance(users, list), "'users' should be a list"
        assert len(users) >= 1, "Should have at least 1 user (admin)"
        
        # Find admin user
        admin_user = next((u for u in users if u.get("username") == "admin"), None)
        assert admin_user is not None, "Admin user should exist"
        assert admin_user.get("role") == "admin", "Admin should have admin role"
        
        print(f"Users count: {len(users)}")
        for u in users:
            print(f"  - {u.get('username')} ({u.get('role')})")
            
    def test_08_create_user(self):
        """POST /api/users creates a new user"""
        test_username = "TEST_user_iteration7"
        
        # Create user
        create_res = self.session.post(f"{BASE_URL}/api/users", json={
            "username": test_username,
            "email": "test_iter7@example.com",
            "password": "testpass123",
            "role": "user"
        })
        assert create_res.status_code == 200, f"Create user failed: {create_res.text}"
        data = create_res.json()
        
        assert "id" in data or "status" in data, "Response should have 'id' or 'status'"
        user_id = data.get("id")
        print(f"Created user: {test_username}, id={user_id}")
        
        # Verify user exists
        get_res = self.session.get(f"{BASE_URL}/api/users")
        assert get_res.status_code == 200
        users = get_res.json().get("users", [])
        test_user = next((u for u in users if u.get("username") == test_username), None)
        assert test_user is not None, f"Created user {test_username} should exist"
        
        # Cleanup - delete test user
        if user_id:
            delete_res = self.session.delete(f"{BASE_URL}/api/users/{user_id}")
            print(f"Cleanup: deleted test user {test_username}")
        elif test_user:
            delete_res = self.session.delete(f"{BASE_URL}/api/users/{test_user['id']}")
            print(f"Cleanup: deleted test user {test_username}")
            
    def test_09_settings_sync_intervals(self):
        """Settings sync intervals are persisted correctly"""
        # Update sync intervals
        update_res = self.session.put(f"{BASE_URL}/api/settings", json={
            "sync_products_interval_hours": 48,
            "sync_inventory_interval_minutes": 60,
            "sync_pricing_interval_hours": 24
        })
        assert update_res.status_code == 200
        
        # Verify persistence
        get_res = self.session.get(f"{BASE_URL}/api/settings")
        assert get_res.status_code == 200
        data = get_res.json()
        
        assert data.get("sync_products_interval_hours") == 48
        assert data.get("sync_inventory_interval_minutes") == 60
        assert data.get("sync_pricing_interval_hours") == 24
        print("Sync intervals updated and persisted correctly")
        
        # Reset to defaults
        self.session.put(f"{BASE_URL}/api/settings", json={
            "sync_products_interval_hours": 24,
            "sync_inventory_interval_minutes": 30,
            "sync_pricing_interval_hours": 12
        })
        
    def test_10_cleanup(self):
        """Cleanup - disable auto_sync"""
        res = self.session.put(f"{BASE_URL}/api/settings", json={
            "auto_sync_enabled": False,
            "auto_push_to_odoo": False
        })
        assert res.status_code == 200
        print("Cleanup complete - auto_sync and auto_push disabled")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
