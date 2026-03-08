import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Package, Truck, Check, ArrowUpRight, Layers, RefreshCw } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4", "#EC4899", "#F97316"];

function SyncBadge({ status }) {
  const s = {
    completed: "bg-emerald-950/50 text-emerald-400 border-emerald-800",
    completed_with_errors: "bg-amber-950/50 text-amber-400 border-amber-800",
    failed: "bg-red-950/50 text-red-400 border-red-800",
    running: "bg-blue-950/50 text-blue-400 border-blue-800",
  };
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs font-mono border rounded-none ${s[status] || s.running}`}>
      {status}
    </span>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);

  const fetchStats = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/dashboard/stats`);
      setStats(res.data);
    } catch (e) {
      console.error("Stats fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const seedDemo = async () => {
    setSeeding(true);
    try {
      const res = await axios.post(`${API}/seed-demo`);
      if (res.data.status === "success") {
        toast.success(`Seeded ${res.data.products_created} demo products`);
        fetchStats();
      } else {
        toast.info(res.data.message);
      }
    } catch (e) {
      toast.error("Failed to seed demo data");
    } finally {
      setSeeding(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <div className="h-8 w-48 bg-zinc-800 animate-pulse rounded-sm" />
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array(6).fill(0).map((_, i) => <div key={i} className="h-24 bg-zinc-800/50 animate-pulse rounded-sm" />)}
        </div>
      </div>
    );
  }

  const statCards = [
    { label: "Total Products", value: stats?.total_products || 0, icon: Package, color: "text-blue-400" },
    { label: "Selected for Odoo", value: stats?.selected_for_odoo || 0, icon: Check, color: "text-emerald-400" },
    { label: "Synced to Odoo", value: stats?.synced_to_odoo || 0, icon: ArrowUpRight, color: "text-amber-400" },
    { label: "Suppliers", value: stats?.total_suppliers || 0, icon: Truck, color: "text-sky-400" },
    { label: "Total Variants", value: stats?.total_variants || 0, icon: Layers, color: "text-violet-400" },
    { label: "Active Products", value: stats?.active_products || 0, icon: Package, color: "text-green-400" },
  ];

  return (
    <div className="p-6 space-y-6" data-testid="dashboard-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-zinc-500 text-sm mt-1 font-body">PromoStandards Middleware Overview</p>
        </div>
        <div className="flex gap-2">
          {stats?.total_products === 0 && (
            <Button
              onClick={seedDemo}
              disabled={seeding}
              data-testid="seed-demo-btn"
              className="bg-blue-600 hover:bg-blue-500 text-white rounded-none text-sm font-body"
            >
              {seeding ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : null}
              {seeding ? "Seeding..." : "Seed Demo Data"}
            </Button>
          )}
          <Button onClick={fetchStats} variant="outline" className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800" data-testid="refresh-stats-btn">
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {statCards.map((card, i) => (
          <Card key={i} className="bg-zinc-900/50 border-zinc-800 rounded-sm" data-testid={`stat-card-${i}`}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <card.icon className={`w-4 h-4 ${card.color}`} strokeWidth={1.5} />
              </div>
              <div className="font-mono text-2xl font-bold tabular-nums">{card.value.toLocaleString()}</div>
              <div className="text-xs text-zinc-500 mt-1 font-body">{card.label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
          <CardHeader className="pb-2 border-b border-zinc-800/50 p-4">
            <CardTitle className="font-heading text-sm font-bold tracking-wider uppercase text-zinc-400">Products by Category</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {stats?.category_distribution?.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={stats.category_distribution}>
                  <XAxis dataKey="category" tick={{ fill: "#71717A", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#71717A", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: "#18181B", border: "1px solid #27272A", borderRadius: 0, fontFamily: "Manrope", fontSize: 12 }} />
                  <Bar dataKey="count" fill="#3B82F6" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-zinc-600 text-sm font-mono">NO DATA</div>
            )}
          </CardContent>
        </Card>

        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
          <CardHeader className="pb-2 border-b border-zinc-800/50 p-4">
            <CardTitle className="font-heading text-sm font-bold tracking-wider uppercase text-zinc-400">Products by Brand</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {stats?.brand_distribution?.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={stats.brand_distribution} dataKey="count" nameKey="brand" cx="50%" cy="50%" outerRadius={70} label={({ brand, count }) => `${brand} (${count})`} labelLine={false}>
                    {stats.brand_distribution.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#18181B", border: "1px solid #27272A", borderRadius: 0 }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-zinc-600 text-sm font-mono">NO DATA</div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="pb-2 border-b border-zinc-800/50 p-4">
          <CardTitle className="font-heading text-sm font-bold tracking-wider uppercase text-zinc-400">Recent Sync Activity</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {stats?.recent_syncs?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full" data-testid="recent-syncs-table">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/80">
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Type</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Supplier</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Status</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Processed</th>
                    <th className="text-left p-3 text-xs font-mono text-zinc-500 uppercase tracking-wider">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_syncs.map((log, i) => (
                    <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors">
                      <td className="p-3 text-sm font-mono">{log.sync_type}</td>
                      <td className="p-3 text-sm font-body">{log.supplier_name}</td>
                      <td className="p-3"><SyncBadge status={log.status} /></td>
                      <td className="p-3 text-sm font-mono tabular-nums">{log.products_processed || 0}</td>
                      <td className="p-3 text-xs font-mono text-zinc-500">{log.started_at ? new Date(log.started_at).toLocaleString() : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-8 text-center text-zinc-600 text-sm font-mono">NO SYNC ACTIVITY YET</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
