import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Search, Package, Grid3X3, List, DollarSign, Warehouse, Image, Loader2, MoreVertical, RefreshCw } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ProductSearch() {
  const navigate = useNavigate();
  const [suppliers, setSuppliers] = useState([]);
  const [selectedSupplier, setSelectedSupplier] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [viewMode, setViewMode] = useState("grid");
  const [syncing, setSyncing] = useState({});
  const [bulkSyncing, setBulkSyncing] = useState({});

  // Fetch suppliers on mount
  useEffect(() => {
    axios.get(`${API}/suppliers`).then(res => {
      setSuppliers(res.data.suppliers || []);
    }).catch(() => {});
  }, []);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!selectedSupplier) {
      toast.error("Please select a supplier");
      return;
    }
    if (!searchQuery.trim()) {
      toast.error("Please enter a search term");
      return;
    }

    setLoading(true);
    setSearched(true);
    try {
      const res = await axios.get(`${API}/products`, {
        params: {
          supplier_id: selectedSupplier,
          search: searchQuery.trim(),
          limit: 100
        }
      });
      setResults(res.data.products || []);
      if (res.data.products?.length === 0) {
        toast.info("No products found matching your search");
      }
    } catch (e) {
      toast.error("Search failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const syncProduct = async (productId, type) => {
    const key = `${productId}-${type}`;
    setSyncing(prev => ({ ...prev, [key]: true }));
    try {
      const res = await axios.post(`${API}/sync/product/${productId}/${type}`);
      if (res.data.success) {
        toast.success(res.data.message);
        // Refresh the product in results
        const updatedRes = await axios.get(`${API}/products/${productId}`);
        setResults(prev => prev.map(p => p.id === productId ? { ...p, ...updatedRes.data } : p));
      } else {
        toast.error(res.data.message || `${type} sync failed`);
      }
    } catch (e) {
      toast.error(`Failed to sync ${type}`);
    } finally {
      setSyncing(prev => ({ ...prev, [key]: false }));
    }
  };

  const syncAllResults = async (type) => {
    if (results.length === 0) {
      toast.error("No products to sync");
      return;
    }
    
    setBulkSyncing(prev => ({ ...prev, [type]: true }));
    try {
      const productIds = results.map(p => p.id);
      const res = await axios.post(`${API}/sync/products/bulk?sync_type=${type}`, productIds);
      toast.success(`Synced ${res.data.success} products, ${res.data.failed} failed`);
      
      // Refresh results
      handleSearch({ preventDefault: () => {} });
    } catch (e) {
      toast.error(`Bulk ${type} sync failed`);
    } finally {
      setBulkSyncing(prev => ({ ...prev, [type]: false }));
    }
  };

  const toggleSelection = async (productId, currentValue) => {
    try {
      await axios.post(`${API}/products/${productId}/select-for-odoo`, {
        product_id: productId,
        selected: !currentValue,
      });
      setResults(prev => prev.map(p => p.id === productId ? { ...p, selected_for_odoo: !currentValue } : p));
      toast.success(!currentValue ? "Selected for Odoo" : "Deselected");
    } catch (e) {
      toast.error("Failed to update selection");
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="product-search-page">
      <div>
        <h1 className="font-heading text-3xl font-bold tracking-tight">Product Search</h1>
        <p className="text-zinc-500 text-sm mt-1">Search and sync products from a specific supplier</p>
      </div>

      {/* Search Form */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg font-heading">Search Products</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSearch} className="flex flex-wrap gap-3 items-end">
            <div className="w-64">
              <label className="text-xs text-zinc-500 mb-1 block">Supplier *</label>
              <Select value={selectedSupplier} onValueChange={setSelectedSupplier}>
                <SelectTrigger className="bg-zinc-950 border-zinc-800 rounded-none" data-testid="search-supplier">
                  <SelectValue placeholder="Select supplier..." />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">
                  {suppliers.map(s => (
                    <SelectItem key={s.id} value={s.id}>{s.supplier_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            <div className="flex-1 min-w-[300px]">
              <label className="text-xs text-zinc-500 mb-1 block">Product Name *</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
                <Input
                  placeholder="Enter product name to search..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10 bg-zinc-950 border-zinc-800 rounded-none font-mono"
                  data-testid="search-query"
                />
              </div>
            </div>
            
            <Button 
              type="submit" 
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-500 rounded-none"
              data-testid="search-btn"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Search className="w-4 h-4 mr-2" />}
              Search
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Results */}
      {searched && (
        <div className="space-y-4">
          {/* Results Header */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-heading text-xl">Search Results</h2>
              <p className="text-zinc-500 text-sm">{results.length} products found</p>
            </div>
            
            <div className="flex items-center gap-3">
              {/* Bulk Sync Buttons */}
              {results.length > 0 && (
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => syncAllResults('pricing')}
                    disabled={bulkSyncing.pricing}
                    className="rounded-none border-zinc-700 text-zinc-300"
                    data-testid="sync-all-pricing"
                  >
                    {bulkSyncing.pricing ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <DollarSign className="w-4 h-4 mr-1" />}
                    Sync All Pricing
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => syncAllResults('inventory')}
                    disabled={bulkSyncing.inventory}
                    className="rounded-none border-zinc-700 text-zinc-300"
                    data-testid="sync-all-inventory"
                  >
                    {bulkSyncing.inventory ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Warehouse className="w-4 h-4 mr-1" />}
                    Sync All Inventory
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => syncAllResults('media')}
                    disabled={bulkSyncing.media}
                    className="rounded-none border-zinc-700 text-zinc-300"
                    data-testid="sync-all-media"
                  >
                    {bulkSyncing.media ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Image className="w-4 h-4 mr-1" />}
                    Sync All Media
                  </Button>
                </div>
              )}
              
              {/* View Toggle */}
              <div className="flex border border-zinc-800">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setViewMode("grid")}
                  className={`rounded-none px-3 ${viewMode === "grid" ? "bg-zinc-800 text-white" : "text-zinc-500 hover:text-white"}`}
                  data-testid="view-grid"
                >
                  <Grid3X3 className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setViewMode("list")}
                  className={`rounded-none px-3 ${viewMode === "list" ? "bg-zinc-800 text-white" : "text-zinc-500 hover:text-white"}`}
                  data-testid="view-list"
                >
                  <List className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </div>

          {/* Results Content */}
          {loading ? (
            <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3" : "space-y-2"}>
              {Array(8).fill(0).map((_, i) => (
                <div key={i} className={viewMode === "grid" ? "h-48 bg-zinc-800/30 animate-pulse rounded-sm" : "h-16 bg-zinc-800/30 animate-pulse rounded-sm"} />
              ))}
            </div>
          ) : results.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
              <Package className="w-12 h-12 mb-4 text-zinc-700" strokeWidth={1} />
              <p className="font-mono text-sm">NO PRODUCTS FOUND</p>
              <p className="text-xs mt-1">Try a different search term or supplier</p>
            </div>
          ) : viewMode === "grid" ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3" data-testid="results-grid">
              {results.map((product) => (
                <Card
                  key={product.id}
                  className="bg-zinc-900/50 border-zinc-800 rounded-sm hover:border-zinc-700 transition-colors group"
                  data-testid={`result-card-${product.id}`}
                >
                  <CardContent className="p-0">
                    <div
                      className="h-32 bg-zinc-800/50 flex items-center justify-center border-b border-zinc-800/50 overflow-hidden cursor-pointer"
                      onClick={() => navigate(`/products/${product.id}`)}
                    >
                      {product.thumbnail ? (
                        <img src={product.thumbnail} alt={product.product_name} className="h-full w-full object-cover" />
                      ) : (
                        <Package className="w-8 h-8 text-zinc-700" strokeWidth={1} />
                      )}
                    </div>

                    <div className="p-3 space-y-2">
                      <div className="flex items-start justify-between">
                        <div className="cursor-pointer flex-1" onClick={() => navigate(`/products/${product.id}`)}>
                          <p className="text-sm font-medium text-zinc-200 group-hover:text-white transition-colors line-clamp-1">
                            {product.product_name}
                          </p>
                          <p className="text-xs font-mono text-zinc-500 mt-0.5">{product.supplier_sku}</p>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-zinc-500 hover:text-white">
                              <MoreVertical className="w-4 h-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="bg-zinc-900 border-zinc-800">
                            <DropdownMenuItem 
                              onClick={() => syncProduct(product.id, 'pricing')}
                              disabled={syncing[`${product.id}-pricing`]}
                              className="text-zinc-300 focus:bg-zinc-800"
                            >
                              {syncing[`${product.id}-pricing`] ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <DollarSign className="w-4 h-4 mr-2" />}
                              Sync Pricing
                            </DropdownMenuItem>
                            <DropdownMenuItem 
                              onClick={() => syncProduct(product.id, 'inventory')}
                              disabled={syncing[`${product.id}-inventory`]}
                              className="text-zinc-300 focus:bg-zinc-800"
                            >
                              {syncing[`${product.id}-inventory`] ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Warehouse className="w-4 h-4 mr-2" />}
                              Sync Inventory
                            </DropdownMenuItem>
                            <DropdownMenuItem 
                              onClick={() => syncProduct(product.id, 'media')}
                              disabled={syncing[`${product.id}-media`]}
                              className="text-zinc-300 focus:bg-zinc-800"
                            >
                              {syncing[`${product.id}-media`] ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Image className="w-4 h-4 mr-2" />}
                              Sync Media
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
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
                          className="data-[state=checked]:bg-blue-600"
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <div className="space-y-2" data-testid="results-list">
              {results.map((product) => (
                <div
                  key={product.id}
                  className="flex items-center gap-4 p-3 bg-zinc-900/50 border border-zinc-800 hover:border-zinc-700 transition-colors"
                  data-testid={`result-row-${product.id}`}
                >
                  <div 
                    className="w-16 h-16 bg-zinc-800/50 flex items-center justify-center overflow-hidden cursor-pointer shrink-0"
                    onClick={() => navigate(`/products/${product.id}`)}
                  >
                    {product.thumbnail ? (
                      <img src={product.thumbnail} alt={product.product_name} className="h-full w-full object-cover" />
                    ) : (
                      <Package className="w-6 h-6 text-zinc-700" strokeWidth={1} />
                    )}
                  </div>
                  
                  <div className="flex-1 min-w-0 cursor-pointer" onClick={() => navigate(`/products/${product.id}`)}>
                    <p className="text-sm font-medium text-zinc-200 truncate">{product.product_name}</p>
                    <p className="text-xs font-mono text-zinc-500">{product.supplier_sku}</p>
                  </div>
                  
                  <div className="text-right shrink-0">
                    <p className="text-xs text-zinc-400">{product.brand}</p>
                    <p className="text-sm font-mono text-zinc-300">${product.base_price?.toFixed(2)}</p>
                  </div>
                  
                  <div className="text-center shrink-0 w-20">
                    <p className="text-xs text-zinc-500">{product.variants_count} variants</p>
                  </div>
                  
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => syncProduct(product.id, 'pricing')}
                      disabled={syncing[`${product.id}-pricing`]}
                      className="h-8 px-2 text-zinc-500 hover:text-emerald-400"
                      title="Sync Pricing"
                    >
                      {syncing[`${product.id}-pricing`] ? <Loader2 className="w-4 h-4 animate-spin" /> : <DollarSign className="w-4 h-4" />}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => syncProduct(product.id, 'inventory')}
                      disabled={syncing[`${product.id}-inventory`]}
                      className="h-8 px-2 text-zinc-500 hover:text-blue-400"
                      title="Sync Inventory"
                    >
                      {syncing[`${product.id}-inventory`] ? <Loader2 className="w-4 h-4 animate-spin" /> : <Warehouse className="w-4 h-4" />}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => syncProduct(product.id, 'media')}
                      disabled={syncing[`${product.id}-media`]}
                      className="h-8 px-2 text-zinc-500 hover:text-purple-400"
                      title="Sync Media"
                    >
                      {syncing[`${product.id}-media`] ? <Loader2 className="w-4 h-4 animate-spin" /> : <Image className="w-4 h-4" />}
                    </Button>
                  </div>
                  
                  <div className="flex items-center gap-2 shrink-0 border-l border-zinc-800 pl-3">
                    <span className="text-xs text-zinc-500">Odoo</span>
                    <Switch
                      checked={product.selected_for_odoo}
                      onCheckedChange={() => toggleSelection(product.id, product.selected_for_odoo)}
                      className="data-[state=checked]:bg-blue-600"
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
