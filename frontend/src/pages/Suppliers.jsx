import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Truck, Plus, Pencil, Trash2, ExternalLink } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const emptyForm = { supplier_name: "", api_base_url: "", account_number: "", password: "", use_uat: false };

export default function Suppliers() {
  const [suppliers, setSuppliers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);

  const fetch = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/suppliers`);
      setSuppliers(res.data.suppliers || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const handleSave = async () => {
    if (!form.supplier_name) {
      toast.error("Supplier name is required");
      return;
    }
    try {
      if (editing) {
        await axios.put(`${API}/suppliers/${editing}`, form);
        toast.success("Supplier updated");
      } else {
        await axios.post(`${API}/suppliers`, form);
        toast.success("Supplier created");
      }
      setDialogOpen(false);
      setEditing(null);
      setForm(emptyForm);
      fetch();
    } catch (e) {
      toast.error("Failed to save supplier");
    }
  };

  const handleEdit = (s) => {
    setEditing(s.id);
    setForm({
      supplier_name: s.supplier_name,
      api_base_url: s.api_base_url || "",
      account_number: s.account_number || "",
      password: "",
      use_uat: s.use_uat || false,
    });
    setDialogOpen(true);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this supplier and all its products?")) return;
    try {
      await axios.delete(`${API}/suppliers/${id}`);
      toast.success("Supplier deleted");
      fetch();
    } catch (e) {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="suppliers-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">Suppliers</h1>
          <p className="text-zinc-500 text-sm mt-1">Manage PromoStandards supplier connections</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={(o) => { setDialogOpen(o); if (!o) { setEditing(null); setForm(emptyForm); } }}>
          <DialogTrigger asChild>
            <Button className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="add-supplier-btn">
              <Plus className="w-4 h-4 mr-2" />Add Supplier
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-zinc-900 border-zinc-800 rounded-sm max-w-lg">
            <DialogHeader>
              <DialogTitle className="font-heading">{editing ? "Edit Supplier" : "Add Supplier"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 mt-4">
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Supplier Name *</label>
                <Input
                  value={form.supplier_name}
                  onChange={(e) => setForm({ ...form, supplier_name: e.target.value })}
                  className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                  placeholder="e.g. ATC / SanMar Canada"
                  data-testid="supplier-name-input"
                />
              </div>
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">API Base URL</label>
                <Input
                  value={form.api_base_url}
                  onChange={(e) => setForm({ ...form, api_base_url: e.target.value })}
                  className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                  placeholder="https://edi.atc-apparel.com"
                  data-testid="supplier-url-input"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Account Number</label>
                  <Input
                    value={form.account_number}
                    onChange={(e) => setForm({ ...form, account_number: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                    data-testid="supplier-account-input"
                  />
                </div>
                <div>
                  <label className="text-xs text-zinc-500 mb-1 block">Password</label>
                  <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none font-mono text-sm"
                    data-testid="supplier-password-input"
                  />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Switch checked={form.use_uat} onCheckedChange={(v) => setForm({ ...form, use_uat: v })} data-testid="supplier-uat-switch" />
                <label className="text-sm text-zinc-400">Use UAT (Test) Environment</label>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-none border-zinc-700 text-zinc-300" data-testid="cancel-supplier-btn">Cancel</Button>
                <Button onClick={handleSave} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-supplier-btn">
                  {editing ? "Update" : "Create"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array(3).fill(0).map((_, i) => <div key={i} className="h-20 bg-zinc-800/30 animate-pulse rounded-sm" />)}
        </div>
      ) : suppliers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
          <Truck className="w-12 h-12 mb-4 text-zinc-700" strokeWidth={1} />
          <p className="font-mono text-sm">NO SUPPLIERS CONFIGURED</p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="suppliers-list">
          {suppliers.map((s) => (
            <Card key={s.id} className="bg-zinc-900/50 border-zinc-800 rounded-sm hover:border-zinc-700 transition-colors" data-testid={`supplier-card-${s.id}`}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-zinc-800 flex items-center justify-center border border-zinc-700">
                      <Truck className="w-5 h-5 text-blue-400" strokeWidth={1.5} />
                    </div>
                    <div>
                      <p className="font-medium text-zinc-200">{s.supplier_name}</p>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-xs font-mono text-zinc-500">{s.account_number || "No account"}</span>
                        {s.api_base_url && (
                          <>
                            <span className="text-zinc-700">|</span>
                            <span className="text-xs font-mono text-zinc-500 truncate max-w-xs">{s.api_base_url}</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <p className="text-xs text-zinc-500">Products</p>
                      <p className="font-mono text-sm tabular-nums">{s.products_count || 0}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-zinc-500">Last Sync</p>
                      <p className="text-xs font-mono text-zinc-400">{s.last_sync_time ? new Date(s.last_sync_time).toLocaleDateString() : "Never"}</p>
                    </div>
                    <span className={`px-2 py-0.5 text-xs font-mono border rounded-none ${s.status === "active" ? "bg-emerald-950/50 text-emerald-400 border-emerald-800" : "bg-zinc-800 text-zinc-500 border-zinc-700"}`}>
                      {s.status}
                    </span>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => handleEdit(s)} className="text-zinc-400 hover:text-white rounded-none" data-testid={`edit-supplier-${s.id}`}>
                        <Pencil className="w-4 h-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(s.id)} className="text-zinc-400 hover:text-red-400 rounded-none" data-testid={`delete-supplier-${s.id}`}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
