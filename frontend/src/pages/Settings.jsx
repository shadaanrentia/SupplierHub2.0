import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Settings as SettingsIcon, Save, Plug, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [odooForm, setOdooForm] = useState({ odoo_url: "", odoo_db: "", odoo_username: "", odoo_api_key: "" });
  const [syncForm, setSyncForm] = useState({ sync_products_interval_hours: 24, sync_inventory_interval_minutes: 30, sync_pricing_interval_hours: 12, auto_sync_enabled: false });

  const fetchSettings = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/settings`);
      setSettings(res.data);
      setOdooForm({
        odoo_url: res.data.odoo_url || "",
        odoo_db: res.data.odoo_db || "",
        odoo_username: res.data.odoo_username || "",
        odoo_api_key: res.data.odoo_api_key === "***" ? "" : (res.data.odoo_api_key || ""),
      });
      setSyncForm({
        sync_products_interval_hours: res.data.sync_products_interval_hours || 24,
        sync_inventory_interval_minutes: res.data.sync_inventory_interval_minutes || 30,
        sync_pricing_interval_hours: res.data.sync_pricing_interval_hours || 12,
        auto_sync_enabled: res.data.auto_sync_enabled || false,
      });
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const saveOdoo = async () => {
    setSaving(true);
    try {
      const data = { ...odooForm };
      if (!data.odoo_api_key) delete data.odoo_api_key;
      await axios.put(`${API}/settings`, data);
      toast.success("Odoo settings saved");
      fetchSettings();
    } catch (e) {
      toast.error("Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const saveSync = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/settings`, syncForm);
      toast.success("Sync settings saved");
    } catch (e) {
      toast.error("Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const testOdoo = async () => {
    setTesting(true);
    try {
      const res = await axios.post(`${API}/odoo/test-connection`);
      if (res.data.connected) {
        toast.success(res.data.message);
      } else {
        toast.info(res.data.message);
      }
    } catch (e) {
      toast.error("Connection test failed");
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-8 w-48 bg-zinc-800 animate-pulse rounded-sm" />
        <div className="h-48 bg-zinc-800/50 animate-pulse rounded-sm" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6" data-testid="settings-page">
      <div>
        <h1 className="font-heading text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-zinc-500 text-sm mt-1">Configure integrations and sync schedules</p>
      </div>

      {/* Odoo Connection */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50 flex flex-row items-center justify-between">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Odoo ERP Connection</CardTitle>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={testOdoo}
              disabled={testing}
              className="rounded-none border-zinc-700 text-zinc-300"
              data-testid="test-odoo-btn"
            >
              {testing ? <RefreshCw className="w-3 h-3 animate-spin mr-1" /> : <Plug className="w-3 h-3 mr-1" />}
              Test Connection
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Odoo URL</label>
              <Input
                value={odooForm.odoo_url}
                onChange={(e) => setOdooForm({ ...odooForm, odoo_url: e.target.value })}
                placeholder="https://your-odoo.com"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="odoo-url-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Database Name</label>
              <Input
                value={odooForm.odoo_db}
                onChange={(e) => setOdooForm({ ...odooForm, odoo_db: e.target.value })}
                placeholder="odoo_db"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="odoo-db-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Username</label>
              <Input
                value={odooForm.odoo_username}
                onChange={(e) => setOdooForm({ ...odooForm, odoo_username: e.target.value })}
                placeholder="admin"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="odoo-username-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">API Key</label>
              <Input
                type="password"
                value={odooForm.odoo_api_key}
                onChange={(e) => setOdooForm({ ...odooForm, odoo_api_key: e.target.value })}
                placeholder="Enter API key"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="odoo-apikey-input"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={saveOdoo} disabled={saving} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-odoo-btn">
              <Save className="w-4 h-4 mr-2" />Save Odoo Settings
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Sync Schedule */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Sync Schedule</CardTitle>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Product Sync Interval (hours)</label>
              <Input
                type="number"
                value={syncForm.sync_products_interval_hours}
                onChange={(e) => setSyncForm({ ...syncForm, sync_products_interval_hours: parseInt(e.target.value) || 24 })}
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="sync-products-interval"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Inventory Sync Interval (minutes)</label>
              <Input
                type="number"
                value={syncForm.sync_inventory_interval_minutes}
                onChange={(e) => setSyncForm({ ...syncForm, sync_inventory_interval_minutes: parseInt(e.target.value) || 30 })}
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="sync-inventory-interval"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Pricing Sync Interval (hours)</label>
              <Input
                type="number"
                value={syncForm.sync_pricing_interval_hours}
                onChange={(e) => setSyncForm({ ...syncForm, sync_pricing_interval_hours: parseInt(e.target.value) || 12 })}
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="sync-pricing-interval"
              />
            </div>
          </div>
          <div className="flex items-center justify-between pt-2">
            <div className="flex items-center gap-2">
              <Switch
                checked={syncForm.auto_sync_enabled}
                onCheckedChange={(v) => setSyncForm({ ...syncForm, auto_sync_enabled: v })}
                data-testid="auto-sync-switch"
              />
              <label className="text-sm text-zinc-400">Enable Automatic Sync</label>
            </div>
            <Button onClick={saveSync} disabled={saving} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-sync-btn">
              <Save className="w-4 h-4 mr-2" />Save Sync Settings
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
