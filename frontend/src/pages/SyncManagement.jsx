import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { RefreshCw, Play, Package, ArrowUpRight, Clock, AlertTriangle, Square, Zap, Loader2 } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function SyncBadge({ status }) {
  const s = {
    completed: "bg-emerald-950/50 text-emerald-400 border-emerald-800",
    completed_with_errors: "bg-amber-950/50 text-amber-400 border-amber-800",
    failed: "bg-red-950/50 text-red-400 border-red-800",
    running: "bg-blue-950/50 text-blue-400 border-blue-800",
    cancelled: "bg-zinc-800 text-zinc-400 border-zinc-700",
  };
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs font-mono border rounded-none ${s[status] || s.running}`}>
      {status}
    </span>
  );
}

export default function SyncManagement() {
  const [logs, setLogs] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [selectedSupplier, setSelectedSupplier] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState({});

  const fetchData = useCallback(async () => {
    try {
      const [logsRes, suppRes] = await Promise.all([
        axios.get(`${API}/sync/logs`, {
          params: {
            ...(selectedSupplier !== "all" && { supplier_id: selectedSupplier }),
            ...(filterType !== "all" && { sync_type: filterType }),
            limit: 50,
          },
        }),
        axios.get(`${API}/suppliers`),
      ]);
      setLogs(logsRes.data.logs || []);
      setSuppliers(suppRes.data.suppliers || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [selectedSupplier, filterType]);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10000);
    return () => clearInterval(iv);
  }, [fetchData]);

  const triggerSync = async (supplierId, type) => {
    const key = `${supplierId}-${type}`;
    setSyncing((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await axios.post(`${API}/sync/${type}/${supplierId}`);
      toast.success(`${type} sync started`);
      setTimeout(fetchData, 2000);
    } catch (e) {
      toast.error(`Failed to start ${type} sync`);
    } finally {
      setSyncing((prev) => ({ ...prev, [key]: false }));
    }
  };

  const triggerSyncAll = async (supplierId, supplierName) => {
    const key = `${supplierId}-all`;
    setSyncing((prev) => ({ ...prev, [key]: true }));
    try {
      const res = await axios.post(`${API}/sync/all/${supplierId}?limit=1500`);
      toast.success(`Full sync started for ${supplierName} (Products → Inventory → Pricing → Media)`);
      setTimeout(fetchData, 2000);
    } catch (e) {
      toast.error(`Failed to start full sync: ${e.response?.data?.detail || e.message}`);
    } finally {
      setSyncing((prev) => ({ ...prev, [key]: false }));
    }
  };

  const stopSync = async (logId) => {
    setSyncing((prev) => ({ ...prev, [`stop-${logId}`]: true }));
    try {
      await axios.post(`${API}/sync/stop/${logId}`);
      toast.success("Sync stopped");
      setTimeout(fetchData, 1000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to stop sync");
    } finally {
      setSyncing((prev) => ({ ...prev, [`stop-${logId}`]: false }));
    }
  };

  const pushToOdoo = async () => {
    setSyncing((prev) => ({ ...prev, odoo: true }));
    try {
      const res = await axios.post(`${API}/odoo/push-products`);
      if (res.data.status === "no_products") {
        toast.info("No products pending sync to Odoo");
      } else {
        toast.success(`Pushing ${res.data.products_to_push} products to Odoo`);
      }
      setTimeout(fetchData, 2000);
    } catch (e) {
      toast.error("Failed to push to Odoo");
    } finally {
      setSyncing((prev) => ({ ...prev, odoo: false }));
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="sync-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">Sync Management</h1>
          <p className="text-zinc-500 text-sm mt-1">Manage data synchronization jobs</p>
        </div>
        <Button onClick={fetchData} variant="outline" className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800" data-testid="refresh-logs-btn">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </div>

      {/* Sync Triggers */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Manual Sync Triggers</CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          {suppliers.length > 0 ? (
            <div className="space-y-4">
              {suppliers.map((s) => (
                <div key={s.id} className="flex items-center justify-between p-3 border border-zinc-800 bg-zinc-950/50">
                  <div>
                    <p className="text-sm font-medium text-zinc-200">{s.supplier_name}</p>
                    <p className="text-xs font-mono text-zinc-500">{s.account_number}</p>
                  </div>
                  <div className="flex gap-2 flex-wrap justify-end">
                    {/* Individual sync buttons */}
                    {["products", "inventory", "pricing", "media"].map((type) => (
                      <Button
                        key={type}
                        size="sm"
                        onClick={() => triggerSync(s.id, type)}
                        disabled={syncing[`${s.id}-${type}`]}
                        className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-none text-xs border border-zinc-700"
                        data-testid={`sync-${type}-${s.id}`}
                      >
                        {syncing[`${s.id}-${type}`] ? (
                          <RefreshCw className="w-3 h-3 animate-spin mr-1" />
                        ) : (
                          <Play className="w-3 h-3 mr-1" />
                        )}
                        {type}
                      </Button>
                    ))}
                    {/* Sync All button */}
                    <Button
                      size="sm"
                      onClick={() => triggerSyncAll(s.id, s.supplier_name)}
                      disabled={syncing[`${s.id}-all`]}
                      className="bg-emerald-700 hover:bg-emerald-600 text-white rounded-none text-xs border border-emerald-600"
                      data-testid={`sync-all-${s.id}`}
                    >
                      {syncing[`${s.id}-all`] ? (
                        <Loader2 className="w-3 h-3 animate-spin mr-1" />
                      ) : (
                        <Zap className="w-3 h-3 mr-1" />
                      )}
                      Sync All
                    </Button>
                  </div>
                </div>
              ))}

              <div className="flex items-center justify-between p-3 border border-blue-800/50 bg-blue-950/20">
                <div>
                  <p className="text-sm font-medium text-blue-300">Push to Odoo</p>
                  <p className="text-xs text-blue-400/60">Push all selected products to Odoo ERP</p>
                </div>
                <Button
                  onClick={pushToOdoo}
                  disabled={syncing.odoo}
                  className="bg-blue-600 hover:bg-blue-500 text-white rounded-none"
                  data-testid="push-to-odoo-btn"
                >
                  {syncing.odoo ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <ArrowUpRight className="w-4 h-4 mr-2" />}
                  Push to Odoo
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-zinc-500 text-sm font-mono">No suppliers configured</p>
          )}
        </CardContent>
      </Card>

      {/* Filters */}
      <div className="flex gap-3">
        <Select value={selectedSupplier} onValueChange={setSelectedSupplier}>
          <SelectTrigger className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="log-filter-supplier">
            <SelectValue placeholder="Supplier" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Suppliers</SelectItem>
            {suppliers.map((s) => <SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-40 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="log-filter-type">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="products">Products</SelectItem>
            <SelectItem value="inventory">Inventory</SelectItem>
            <SelectItem value="pricing">Pricing</SelectItem>
            <SelectItem value="media">Media</SelectItem>
            <SelectItem value="odoo_push">Odoo Push</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Sync Logs */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50">
          <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">Sync Logs</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-2">
              {Array(5).fill(0).map((_, i) => <div key={i} className="h-10 bg-zinc-800/30 animate-pulse rounded-sm" />)}
            </div>
          ) : logs.length === 0 ? (
            <div className="p-12 text-center text-zinc-600 font-mono text-sm">NO SYNC LOGS</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full" data-testid="sync-logs-table">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/80">
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Type</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Supplier</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Status</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Processed</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Created</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Errors</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Message</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Started</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <tr key={log.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                      <td className="p-3 text-sm font-mono">{log.sync_type}</td>
                      <td className="p-3 text-sm">{log.supplier_name}</td>
                      <td className="p-3"><SyncBadge status={log.status} /></td>
                      <td className="p-3 text-sm font-mono tabular-nums">{log.products_processed || 0}</td>
                      <td className="p-3 text-sm font-mono tabular-nums text-emerald-400">{log.products_created || 0}</td>
                      <td className="p-3 text-sm font-mono tabular-nums">
                        {log.errors_count > 0 ? <span className="text-red-400">{log.errors_count}</span> : <span className="text-zinc-600">0</span>}
                      </td>
                      <td className="p-3 text-xs text-zinc-400 max-w-xs truncate">{log.message}</td>
                      <td className="p-3 text-xs font-mono text-zinc-500">{log.started_at ? new Date(log.started_at).toLocaleString() : "-"}</td>
                      <td className="p-3">
                        {log.status === "running" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => stopSync(log.id)}
                            disabled={syncing[`stop-${log.id}`]}
                            className="text-red-400 hover:text-red-300 hover:bg-red-950/30 rounded-none h-7 px-2"
                            data-testid={`stop-sync-${log.id}`}
                          >
                            {syncing[`stop-${log.id}`] ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <Square className="w-3 h-3 mr-1" />
                            )}
                            Stop
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
