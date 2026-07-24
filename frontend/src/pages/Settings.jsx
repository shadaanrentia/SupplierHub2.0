import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Settings as SettingsIcon, Save, Plug, RefreshCw, Warehouse, Clock, Timer, Zap } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testingLs, setTestingLs] = useState(false);
  const [warehouses, setWarehouses] = useState([]);
  const [schedulerStatus, setSchedulerStatus] = useState(null);
  const [odooForm, setOdooForm] = useState({ odoo_url: "", odoo_db: "", odoo_username: "", odoo_api_key: "" });
  const [lsForm, setLsForm] = useState({ lightspeed_api_key: "", lightspeed_api_secret: "", lightspeed_cluster: "us1", lightspeed_language: "en" });
  const [syncForm, setSyncForm] = useState({ sync_products_interval_hours: 24, sync_inventory_interval_minutes: 30, sync_pricing_interval_hours: 12, auto_sync_enabled: false, auto_push_to_odoo: false });
  const [warehouseForm, setWarehouseForm] = useState({ preferred_warehouse: "" });
  const [pricingForm, setPricingForm] = useState({ markup_percentage: 40, default_warehouse: "Main Warehouse" });

  const fetchSettings = useCallback(async () => {
    try {
      const [settingsRes, warehousesRes, schedulerRes] = await Promise.all([
        axios.get(`${API}/settings`),
        axios.get(`${API}/settings/warehouses`),
        axios.get(`${API}/scheduler/status`).catch(() => ({ data: null })),
      ]);
      const res = settingsRes;
      setSettings(res.data);
      setWarehouses(warehousesRes.data.warehouses || []);
      setSchedulerStatus(schedulerRes.data);
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
        auto_push_to_odoo: res.data.auto_push_to_odoo || false,
      });
      setWarehouseForm({
        preferred_warehouse: res.data.preferred_warehouse || "",
      });
      setPricingForm({
        markup_percentage: res.data.markup_percentage || 40,
        default_warehouse: res.data.default_warehouse || "Main Warehouse",
      });
      setLsForm({
        lightspeed_api_key: res.data.lightspeed_api_key || "",
        lightspeed_api_secret: res.data.lightspeed_api_secret === "***" ? "" : (res.data.lightspeed_api_secret || ""),
        lightspeed_cluster: res.data.lightspeed_cluster || "us1",
        lightspeed_language: res.data.lightspeed_language || "en",
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

  const saveWarehouse = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/settings`, warehouseForm);
      toast.success("Warehouse preference saved");
    } catch (e) {
      toast.error("Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const savePricing = async () => {
    setSaving(true);
    try {
      await axios.put(`${API}/settings`, pricingForm);
      toast.success("Pricing settings saved");
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

  const saveLightspeed = async () => {
    setSaving(true);
    try {
      const data = { ...lsForm };
      if (!data.lightspeed_api_secret) delete data.lightspeed_api_secret;
      await axios.put(`${API}/settings`, data);
      toast.success("Lightspeed settings saved");
      fetchSettings();
    } catch (e) {
      toast.error("Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const testLightspeed = async () => {
    setTestingLs(true);
    try {
      const res = await axios.post(`${API}/settings/lightspeed/test`);
      if (res.data.connected) {
        toast.success(res.data.message);
      } else {
        toast.info(res.data.message);
      }
    } catch (e) {
      toast.error("Lightspeed connection test failed");
    } finally {
      setTestingLs(false);
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

      {/* Lightspeed eCom Connection */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50 flex flex-row items-center justify-between">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Lightspeed eCom Connection</CardTitle>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={testLightspeed}
              disabled={testingLs}
              className="rounded-none border-zinc-700 text-zinc-300"
              data-testid="test-lightspeed-btn"
            >
              {testingLs ? <RefreshCw className="w-3 h-3 animate-spin mr-1" /> : <Zap className="w-3 h-3 mr-1" />}
              Test Connection
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">API Key</label>
              <Input
                value={lsForm.lightspeed_api_key}
                onChange={(e) => setLsForm({ ...lsForm, lightspeed_api_key: e.target.value })}
                placeholder="Enter Lightspeed API key"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="ls-api-key-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">API Secret</label>
              <Input
                type="password"
                value={lsForm.lightspeed_api_secret}
                onChange={(e) => setLsForm({ ...lsForm, lightspeed_api_secret: e.target.value })}
                placeholder="Enter API secret"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="ls-api-secret-input"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Cluster</label>
              <Select value={lsForm.lightspeed_cluster} onValueChange={(v) => setLsForm({ ...lsForm, lightspeed_cluster: v })}>
                <SelectTrigger className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm" data-testid="ls-cluster-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="us1">US1 (shoplightspeed.com)</SelectItem>
                  <SelectItem value="eu1">EU1 (webshopapp.com)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Language</label>
              <Input
                value={lsForm.lightspeed_language}
                onChange={(e) => setLsForm({ ...lsForm, lightspeed_language: e.target.value })}
                placeholder="en"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                data-testid="ls-language-input"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={saveLightspeed} disabled={saving} className="bg-emerald-600 hover:bg-emerald-500 text-white rounded-none" data-testid="save-lightspeed-btn">
              <Save className="w-4 h-4 mr-2" />Save Lightspeed Settings
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
          <div className="flex flex-col gap-3 pt-2 border-t border-zinc-800/50">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Switch
                  checked={syncForm.auto_sync_enabled}
                  onCheckedChange={(v) => setSyncForm({ ...syncForm, auto_sync_enabled: v })}
                  data-testid="auto-sync-switch"
                />
                <label className="text-sm text-zinc-400">Enable Automatic Sync</label>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Switch
                  checked={syncForm.auto_push_to_odoo}
                  onCheckedChange={(v) => setSyncForm({ ...syncForm, auto_push_to_odoo: v })}
                  data-testid="auto-push-odoo-switch"
                />
                <label className="text-sm text-zinc-400">Auto-push to Odoo after BulkData sync</label>
              </div>
              <Button onClick={saveSync} disabled={saving} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-sync-btn">
                <Save className="w-4 h-4 mr-2" />Save Sync Settings
              </Button>
            </div>
          </div>

          {/* Scheduler Status */}
          {schedulerStatus && (
            <div className="mt-3 p-3 border border-zinc-800 bg-zinc-950/50">
              <div className="flex items-center gap-2 mb-2">
                <Timer className="w-4 h-4 text-zinc-400" />
                <span className="text-xs font-mono text-zinc-400 uppercase tracking-wider">Scheduler Status</span>
                <span className={`ml-2 inline-flex px-2 py-0.5 text-xs font-mono border rounded-none ${schedulerStatus.running ? 'bg-emerald-950/50 text-emerald-400 border-emerald-800' : 'bg-zinc-800 text-zinc-500 border-zinc-700'}`}>
                  {schedulerStatus.running ? 'RUNNING' : 'STOPPED'}
                </span>
              </div>
              {schedulerStatus.jobs && schedulerStatus.jobs.length > 0 ? (
                <div className="space-y-1">
                  {schedulerStatus.jobs.map((job) => (
                    <div key={job.id} className="flex items-center justify-between text-xs">
                      <span className="font-mono text-zinc-400">{job.id}</span>
                      <span className="font-mono text-zinc-500">{job.trigger}</span>
                      <span className="font-mono text-emerald-400">
                        {job.next_run ? `Next: ${new Date(job.next_run).toLocaleString()}` : 'Not scheduled'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-zinc-600 font-mono">No scheduled jobs (enable auto-sync to activate)</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Warehouse Preference */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider flex items-center gap-2">
            <Warehouse className="w-4 h-4" />
            Inventory Warehouse
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          <p className="text-sm text-zinc-400">Select your preferred warehouse location. Inventory levels will be displayed for this warehouse only.</p>
          <div className="flex items-center gap-4">
            <Select value={warehouseForm.preferred_warehouse} onValueChange={(v) => setWarehouseForm({ preferred_warehouse: v })}>
              <SelectTrigger className="w-64 bg-zinc-950 border-zinc-800 rounded-none" data-testid="warehouse-select">
                <SelectValue placeholder="Select warehouse..." />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-800">
                {warehouses.length > 0 ? (
                  warehouses.map((wh) => (
                    <SelectItem key={wh} value={wh}>{wh}</SelectItem>
                  ))
                ) : (
                  <SelectItem value="none" disabled>No warehouses available (sync inventory first)</SelectItem>
                )}
              </SelectContent>
            </Select>
            <Button onClick={saveWarehouse} disabled={saving} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-warehouse-btn">
              <Save className="w-4 h-4 mr-2" />Save
            </Button>
          </div>
          {warehouseForm.preferred_warehouse && (
            <p className="text-xs text-emerald-400">Currently showing inventory for: {warehouseForm.preferred_warehouse}</p>
          )}
        </CardContent>
      </Card>

      {/* Pricing & Markup Settings */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider flex items-center gap-2">
            <SettingsIcon className="w-4 h-4" />
            Pricing Configuration
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 space-y-4">
          <p className="text-sm text-zinc-400">Configure markup percentage for calculating sale prices from supplier cost prices.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Markup Percentage (%)</label>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min="0"
                  max="500"
                  value={pricingForm.markup_percentage}
                  onChange={(e) => setPricingForm({ ...pricingForm, markup_percentage: parseFloat(e.target.value) || 0 })}
                  className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm w-32"
                  data-testid="markup-percentage-input"
                />
                <span className="text-zinc-400">%</span>
              </div>
              <p className="text-xs text-zinc-600 mt-1">Sale Price = Cost + (Cost × Markup%)</p>
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Default Odoo Warehouse</label>
              <Input
                type="text"
                value={pricingForm.default_warehouse}
                onChange={(e) => setPricingForm({ ...pricingForm, default_warehouse: e.target.value })}
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                placeholder="Main Warehouse"
                data-testid="default-warehouse-input"
              />
            </div>
          </div>
          <div className="flex items-center justify-between pt-2 border-t border-zinc-800/50">
            <div className="text-sm text-zinc-500">
              Example: Cost $10.00 + {pricingForm.markup_percentage}% = <span className="text-green-400 font-bold">${(10 + (10 * pricingForm.markup_percentage / 100)).toFixed(0)}.00</span> sale price
            </div>
            <Button onClick={savePricing} disabled={saving} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-pricing-btn">
              <Save className="w-4 h-4 mr-2" />Save Pricing Settings
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
