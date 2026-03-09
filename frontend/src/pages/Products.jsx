import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, Package, Filter, ChevronLeft, ChevronRight, Check, X } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Products() {
  const navigate = useNavigate();
  const [products, setProducts] = useState([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [supplier, setSupplier] = useState("all");
  const [category, setCategory] = useState("all");
  const [brand, setBrand] = useState("all");
  const [selectedFilter, setSelectedFilter] = useState("all");
  const [odooSyncFilter, setOdooSyncFilter] = useState("all"); // New: all, synced, not_synced
  const [suppliers, setSuppliers] = useState([]);
  const [categories, setCategories] = useState([]);
  const [brands, setBrands] = useState([]);

  const fetchFilters = useCallback(async () => {
    try {
      const [sRes, cRes, bRes] = await Promise.all([
        axios.get(`${API}/suppliers`),
        axios.get(`${API}/products/categories`),
        axios.get(`${API}/products/brands`),
      ]);
      setSuppliers(sRes.data.suppliers || []);
      setCategories(cRes.data.categories || []);
      setBrands(bRes.data.brands || []);
    } catch (e) {
      console.error("Filter fetch error:", e);
    }
  }, []);

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, limit: 20 };
      if (search) params.search = search;
      if (supplier !== "all") params.supplier_id = supplier;
      if (category !== "all") params.category = category;
      if (brand !== "all") params.brand = brand;
      if (selectedFilter === "selected") params.selected_for_odoo = true;
      if (selectedFilter === "not_selected") params.selected_for_odoo = false;
      if (odooSyncFilter === "synced") params.odoo_synced = true;
      if (odooSyncFilter === "not_synced") params.odoo_synced = false;
      const res = await axios.get(`${API}/products`, { params });
      setProducts(res.data.products || []);
      setTotal(res.data.total || 0);
      setPages(res.data.pages || 1);
    } catch (e) {
      console.error("Products fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, [page, search, supplier, category, brand, selectedFilter, odooSyncFilter]);

  useEffect(() => {
    fetchFilters();
  }, [fetchFilters]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  const toggleSelection = async (productId, currentValue) => {
    try {
      await axios.post(`${API}/products/${productId}/select-for-odoo`, {
        product_id: productId,
        selected: !currentValue,
      });
      setProducts((prev) =>
        prev.map((p) => (p.id === productId ? { ...p, selected_for_odoo: !currentValue } : p))
      );
      toast.success(!currentValue ? "Selected for Odoo" : "Deselected");
    } catch (e) {
      toast.error("Failed to update selection");
    }
  };

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    fetchProducts();
  };

  return (
    <div className="p-6 space-y-4" data-testid="products-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">Products</h1>
          <p className="text-zinc-500 text-sm mt-1">{total.toLocaleString()} products in catalog</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end" data-testid="product-filters">
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
            <Input
              placeholder="Search products..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10 w-64 bg-zinc-950 border-zinc-800 rounded-none text-sm font-mono placeholder:text-zinc-600 focus:border-blue-500"
              data-testid="search-input"
            />
          </div>
        </form>

        <Select value={supplier} onValueChange={(v) => { setSupplier(v); setPage(1); }}>
          <SelectTrigger className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="filter-supplier">
            <SelectValue placeholder="Supplier" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Suppliers</SelectItem>
            {suppliers.map((s) => <SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={category} onValueChange={(v) => { setCategory(v); setPage(1); }}>
          <SelectTrigger className="w-40 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="filter-category">
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Categories</SelectItem>
            {categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={brand} onValueChange={(v) => { setBrand(v); setPage(1); }}>
          <SelectTrigger className="w-40 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="filter-brand">
            <SelectValue placeholder="Brand" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Brands</SelectItem>
            {brands.map((b) => <SelectItem key={b} value={b}>{b}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={selectedFilter} onValueChange={(v) => { setSelectedFilter(v); setPage(1); }}>
          <SelectTrigger className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="filter-selection">
            <SelectValue placeholder="Selection" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Products</SelectItem>
            <SelectItem value="selected">Selected for Odoo</SelectItem>
            <SelectItem value="not_selected">Not Selected</SelectItem>
          </SelectContent>
        </Select>

        <Select value={odooSyncFilter} onValueChange={(v) => { setOdooSyncFilter(v); setPage(1); }}>
          <SelectTrigger className="w-44 bg-zinc-950 border-zinc-800 rounded-none text-sm" data-testid="filter-odoo-sync">
            <SelectValue placeholder="Odoo Sync Status" />
          </SelectTrigger>
          <SelectContent className="bg-zinc-900 border-zinc-800 rounded-none">
            <SelectItem value="all">All Sync Status</SelectItem>
            <SelectItem value="synced">Synced to Odoo</SelectItem>
            <SelectItem value="not_synced">Not Synced</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Product Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {Array(8).fill(0).map((_, i) => <div key={i} className="h-48 bg-zinc-800/30 animate-pulse rounded-sm" />)}
        </div>
      ) : products.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
          <Package className="w-12 h-12 mb-4 text-zinc-700" strokeWidth={1} />
          <p className="font-mono text-sm">NO PRODUCTS FOUND</p>
          <p className="text-xs mt-1">Sync products from a supplier or seed demo data</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3" data-testid="product-grid">
          {products.map((product) => (
            <Card
              key={product.id}
              className="bg-zinc-900/50 border-zinc-800 rounded-sm hover:border-zinc-700 transition-colors cursor-pointer group"
              data-testid={`product-card-${product.id}`}
            >
              <CardContent className="p-0">
                {/* Image */}
                <div
                  className="h-32 bg-zinc-800/50 flex items-center justify-center border-b border-zinc-800/50 overflow-hidden"
                  onClick={() => navigate(`/products/${product.id}`)}
                >
                  {product.thumbnail ? (
                    <img src={product.thumbnail} alt={product.product_name} className="h-full w-full object-cover" />
                  ) : (
                    <Package className="w-8 h-8 text-zinc-700" strokeWidth={1} />
                  )}
                </div>

                <div className="p-3 space-y-2">
                  <div onClick={() => navigate(`/products/${product.id}`)}>
                    <p className="text-sm font-medium text-zinc-200 group-hover:text-white transition-colors line-clamp-1">
                      {product.product_name}
                    </p>
                    <p className="text-xs font-mono text-zinc-500 mt-0.5">{product.supplier_sku}</p>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-400">{product.brand}</span>
                    <span className="font-mono text-zinc-300 tabular-nums">${product.base_price?.toFixed(2)}</span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-zinc-500">{product.variants_count} variants</span>
                    <span className={`px-1.5 py-0.5 font-mono border rounded-none ${product.status === "active" ? "bg-emerald-950/50 text-emerald-400 border-emerald-800" : "bg-zinc-800 text-zinc-500 border-zinc-700"}`}>
                      {product.status}
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-1 border-t border-zinc-800/50">
                    <span className="text-xs text-zinc-400">Odoo Sync</span>
                    <Switch
                      checked={product.selected_for_odoo}
                      onCheckedChange={() => toggleSelection(product.id, product.selected_for_odoo)}
                      data-testid={`odoo-toggle-${product.id}`}
                      className="data-[state=checked]:bg-blue-600"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between pt-4" data-testid="pagination">
          <span className="text-xs text-zinc-500 font-mono">
            Page {page} of {pages} ({total} total)
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800"
              data-testid="prev-page-btn"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page === pages}
              className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800"
              data-testid="next-page-btn"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
