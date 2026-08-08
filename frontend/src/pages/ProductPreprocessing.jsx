import React, { useState, useEffect, useCallback } from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Badge } from "../components/ui/badge";
import { 
  RefreshCw, Package, DollarSign, CheckCircle, XCircle, 
  AlertTriangle, Eye, Upload, Calculator, Layers, Image,
  ArrowRight, Filter, Zap
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

export default function ProductPreprocessing() {
  const [products, setProducts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [selectedProducts, setSelectedProducts] = useState(new Set());
  const [previewProduct, setPreviewProduct] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [syncPlatform, setSyncPlatform] = useState("lightspeed");
  const limit = 25;

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, limit });
      if (statusFilter !== "all") {
        params.append("status", statusFilter);
      }
      const res = await axios.get(`${API}/preprocessing/products?${params}`);
      setProducts(res.data.products || []);
      setTotal(res.data.total || 0);
    } catch (e) {
      toast.error("Failed to load products");
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/preprocessing/summary`);
      setSummary(res.data);
    } catch (e) {
      console.error("Failed to load summary");
    }
  }, []);

  useEffect(() => {
    fetchProducts();
    fetchSummary();
  }, [fetchProducts, fetchSummary]);

  const recalculatePrices = async () => {
    setLoading(true);
    try {
      const res = await axios.post(`${API}/preprocessing/recalculate-prices`);
      toast.success(`Recalculated prices for ${res.data.updated} products (${res.data.markup_percentage}% markup)`);
      fetchProducts();
    } catch (e) {
      toast.error("Failed to recalculate prices");
    } finally {
      setLoading(false);
    }
  };

  const validateProducts = async () => {
    setLoading(true);
    try {
      const productIds = selectedProducts.size > 0 ? Array.from(selectedProducts) : [];
      const res = await axios.post(`${API}/preprocessing/validate-products`, { product_ids: productIds });
      toast.success(`Validated ${res.data.validated} products, ${res.data.invalid} invalid`);
      fetchProducts();
      fetchSummary();
    } catch (e) {
      toast.error("Failed to validate products");
    } finally {
      setLoading(false);
    }
  };

  const syncEndpoint = syncPlatform === "odoo" ? "sync-to-odoo" : "sync-to-lightspeed";
  const platformLabel = syncPlatform === "odoo" ? "Odoo" : "Lightspeed";

  const syncSelected = async () => {
    if (selectedProducts.size === 0) {
      toast.error("No products selected");
      return;
    }
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/preprocessing/${syncEndpoint}`, {
        product_ids: Array.from(selectedProducts)
      });
      if (res.data.synced > 0) {
        toast.success(`Synced ${res.data.synced} products to ${platformLabel}`);
      }
      if (res.data.failed > 0) {
        toast.error(`Failed to sync ${res.data.failed} products`);
      }
      setSelectedProducts(new Set());
      fetchProducts();
      fetchSummary();
    } catch (e) {
      toast.error(e.response?.data?.detail || `Sync to ${platformLabel} failed`);
    } finally {
      setSyncing(false);
    }
  };

  const syncAll = async () => {
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/preprocessing/${syncEndpoint}`, { sync_all: true });
      if (res.data.synced > 0) {
        toast.success(`Synced ${res.data.synced} products to ${platformLabel}`);
      }
      if (res.data.failed > 0) {
        toast.error(`Failed to sync ${res.data.failed} products`);
      }
      fetchProducts();
      fetchSummary();
    } catch (e) {
      toast.error(e.response?.data?.detail || `Sync to ${platformLabel} failed`);
    } finally {
      setSyncing(false);
    }
  };

  const previewProductData = async (productId) => {
    try {
      const res = await axios.get(`${API}/preprocessing/product/${productId}/preview`);
      setPreviewProduct(res.data);
      setShowPreview(true);
    } catch (e) {
      toast.error("Failed to load preview");
    }
  };

  const toggleProductSelection = (productId) => {
    setSelectedProducts(prev => {
      const newSet = new Set(prev);
      if (newSet.has(productId)) {
        newSet.delete(productId);
      } else {
        newSet.add(productId);
      }
      return newSet;
    });
  };

  const selectAllVisible = () => {
    const validProducts = products.filter(p => p.is_valid);
    setSelectedProducts(new Set(validProducts.map(p => p.id)));
  };

  const deselectAll = () => {
    setSelectedProducts(new Set());
  };

  const formatPrice = (price) => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(price || 0);
  };

  return (
    <div className="p-6 space-y-6" data-testid="product-preprocessing-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Product Preprocessing</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Validate, calculate prices, and sync products to {platformLabel}
          </p>
        </div>
        <div className="flex gap-2">
          <Button 
            variant="outline" 
            onClick={recalculatePrices}
            disabled={loading}
          >
            <Calculator className="w-4 h-4 mr-2" />
            Recalculate Prices
          </Button>
          <Button 
            variant="outline" 
            onClick={validateProducts}
            disabled={loading}
          >
            <CheckCircle className="w-4 h-4 mr-2" />
            Validate All
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Package className="w-8 h-8 text-blue-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.total_products}</p>
                  <p className="text-xs text-zinc-500">Total Products</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Layers className="w-8 h-8 text-purple-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.total_variants}</p>
                  <p className="text-xs text-zinc-500">Total Variants</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-8 h-8 text-green-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.sync_status?.ready || 0}</p>
                  <p className="text-xs text-zinc-500">Ready for Sync</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Upload className="w-8 h-8 text-emerald-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.sync_status?.synced || 0}</p>
                  <p className="text-xs text-zinc-500">Synced</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-8 h-8 text-amber-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.category_mapping?.unmapped || 0}</p>
                  <p className="text-xs text-zinc-500">Missing Mapping</p>
                </div>
              </div>
            </CardContent>
          </Card>
          
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <Image className="w-8 h-8 text-rose-400" />
                <div>
                  <p className="text-2xl font-bold text-zinc-100">{summary.images?.without_images || 0}</p>
                  <p className="text-xs text-zinc-500">Missing Images</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Products Table */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Package className="w-5 h-5 text-blue-400" />
              Products Ready for Sync
            </CardTitle>
            <div className="flex items-center gap-3">
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-40 bg-zinc-800 border-zinc-700">
                  <Filter className="w-4 h-4 mr-2" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">
                  <SelectItem value="all">All Products</SelectItem>
                  <SelectItem value="ready">Ready</SelectItem>
                  <SelectItem value="invalid">Invalid</SelectItem>
                </SelectContent>
              </Select>
              
              <Button variant="outline" size="sm" onClick={selectAllVisible}>
                Select Valid
              </Button>
              <Button variant="outline" size="sm" onClick={deselectAll}>
                Deselect All
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <RefreshCw className="w-6 h-6 animate-spin text-zinc-500" />
            </div>
          ) : products.length > 0 ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400">
                      <th className="text-left py-2 px-3 w-10"></th>
                      <th className="text-left py-2 px-3">Product</th>
                      <th className="text-left py-2 px-3">Supplier Category</th>
                      <th className="text-left py-2 px-3">Mapped Category</th>
                      <th className="text-right py-2 px-3">Supplier Price</th>
                      <th className="text-right py-2 px-3">Retail Price</th>
                      <th className="text-center py-2 px-3">Variants</th>
                      <th className="text-center py-2 px-3">Images</th>
                      <th className="text-center py-2 px-3">Status</th>
                      <th className="text-center py-2 px-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {products.map((product) => (
                      <tr 
                        key={product.id} 
                        className={`border-b border-zinc-800/50 hover:bg-zinc-800/30 ${
                          !product.is_valid ? 'opacity-60' : ''
                        }`}
                      >
                        <td className="py-2 px-3">
                          <Checkbox
                            checked={selectedProducts.has(product.id)}
                            onCheckedChange={() => toggleProductSelection(product.id)}
                            disabled={!product.is_valid}
                          />
                        </td>
                        <td className="py-2 px-3">
                          <div>
                            <p className="text-zinc-100 font-medium truncate max-w-[200px]">
                              {product.product_name || product.supplier_sku}
                            </p>
                            <p className="text-xs text-zinc-500">{product.supplier_sku}</p>
                          </div>
                        </td>
                        <td className="py-2 px-3 text-zinc-400">
                          {product.category || <span className="text-zinc-600">--</span>}
                        </td>
                        <td className="py-2 px-3">
                          {(product.odoo_category_name || product.mapped_lightspeed_category_id) ? (
                            <Badge variant="outline" className="bg-green-900/20 text-green-400 border-green-800">
                              {product.odoo_category_name || "Lightspeed Mapped"}
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="bg-red-900/20 text-red-400 border-red-800">
                              Not Mapped
                            </Badge>
                          )}
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-zinc-400">
                          {formatPrice(product.cost_price)}
                        </td>
                        <td className="py-2 px-3 text-right font-mono text-green-400 font-medium">
                          {formatPrice(product.calculated_sale_price)}
                        </td>
                        <td className="py-2 px-3 text-center text-zinc-400">
                          {product.variants_count || 0}
                        </td>
                        <td className="py-2 px-3 text-center">
                          {product.images_count > 0 ? (
                            <span className="text-green-400">{product.images_count}</span>
                          ) : (
                            <span className="text-red-400">0</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-center">
                          {product.is_valid ? (
                            <Badge className="bg-green-900/30 text-green-400">Ready</Badge>
                          ) : (
                            <Badge className="bg-red-900/30 text-red-400">Invalid</Badge>
                          )}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <Button 
                            variant="ghost" 
                            size="sm"
                            onClick={() => previewProductData(product.id)}
                          >
                            <Eye className="w-4 h-4" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              
              {/* Pagination */}
              <div className="flex items-center justify-between mt-4 pt-4 border-t border-zinc-800">
                <p className="text-sm text-zinc-500">
                  Showing {(page - 1) * limit + 1} - {Math.min(page * limit, total)} of {total} products
                </p>
                <div className="flex gap-2">
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    Previous
                  </Button>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    onClick={() => setPage(p => p + 1)}
                    disabled={page * limit >= total}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <div className="text-center py-10 text-zinc-500">
              <Package className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No products found</p>
              <p className="text-sm mt-1">Sync products from suppliers first</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sync Actions */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardContent className="p-4">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div className="flex items-center gap-4">
              <p className="text-sm text-zinc-400">
                <span className="font-bold text-zinc-100">{selectedProducts.size}</span> products selected
              </p>
              {summary && (
                <p className="text-sm text-zinc-400">
                  <span className="font-bold text-green-400">{summary.sync_status?.ready || 0}</span> ready for sync
                </p>
              )}
            </div>
            <div className="flex items-center gap-3">
              <Select value={syncPlatform} onValueChange={setSyncPlatform}>
                <SelectTrigger className="w-[180px] bg-zinc-800 border-zinc-700" data-testid="sync-platform-selector">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">
                  <SelectItem value="lightspeed">
                    <span className="flex items-center gap-2"><Zap className="w-3 h-3 text-emerald-400" /> Lightspeed</span>
                  </SelectItem>
                  <SelectItem value="odoo">
                    <span className="flex items-center gap-2"><ArrowRight className="w-3 h-3 text-blue-400" /> Odoo ERP</span>
                  </SelectItem>
                </SelectContent>
              </Select>
              <Button 
                onClick={syncSelected}
                disabled={syncing || selectedProducts.size === 0}
                className={syncPlatform === "lightspeed" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-blue-600 hover:bg-blue-700"}
                data-testid="sync-selected-btn"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <Upload className="w-4 h-4 mr-2" />}
                Sync Selected ({selectedProducts.size})
              </Button>
              <Button 
                onClick={syncAll}
                disabled={syncing}
                className={syncPlatform === "lightspeed" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-green-600 hover:bg-green-700"}
                data-testid="sync-all-btn"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <ArrowRight className="w-4 h-4 mr-2" />}
                Sync All Ready to {platformLabel}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Preview Dialog */}
      <Dialog open={showPreview} onOpenChange={setShowPreview}>
        <DialogContent className="bg-zinc-900 border-zinc-800 max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Product Preview</DialogTitle>
          </DialogHeader>
          {previewProduct && (
            <div className="space-y-6 py-4">
              {/* Product Template */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Product Details</h3>
                <div className="bg-zinc-800/50 rounded-lg p-4 space-y-2">
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Name:</span>
                    <span className="text-zinc-100">{previewProduct.product_template.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">SKU:</span>
                    <span className="font-mono text-zinc-100">{previewProduct.product_template.default_code}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Category:</span>
                    <span className={previewProduct.product_template.categ_id ? "text-green-400" : "text-red-400"}>
                      {previewProduct.product_template.category_name}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Supplier Price (before markup):</span>
                    <span className="font-mono text-zinc-400">{formatPrice(previewProduct.product_template.standard_price)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Retail Price (after markup):</span>
                    <span className="font-mono text-green-400 font-bold">{formatPrice(previewProduct.product_template.list_price)}</span>
                  </div>
                </div>
              </div>

              {/* Attributes */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Attributes</h3>
                <div className="bg-zinc-800/50 rounded-lg p-4 grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-zinc-500 mb-1">Colors ({previewProduct.attributes.colors.length})</p>
                    <div className="flex flex-wrap gap-1">
                      {previewProduct.attributes.colors.slice(0, 10).map((c, i) => (
                        <Badge key={i} variant="outline" className="text-xs">{c}</Badge>
                      ))}
                      {previewProduct.attributes.colors.length > 10 && (
                        <Badge variant="outline" className="text-xs">+{previewProduct.attributes.colors.length - 10} more</Badge>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-zinc-500 mb-1">Sizes ({previewProduct.attributes.sizes.length})</p>
                    <div className="flex flex-wrap gap-1">
                      {previewProduct.attributes.sizes.map((s, i) => (
                        <Badge key={i} variant="outline" className="text-xs">{s}</Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Variants */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Variants ({previewProduct.variants.length})</h3>
                <div className="bg-zinc-800/50 rounded-lg p-4 max-h-40 overflow-y-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-zinc-500">
                        <th className="text-left py-1">SKU</th>
                        <th className="text-left py-1">Color</th>
                        <th className="text-left py-1">Size</th>
                        <th className="text-right py-1">Stock</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewProduct.variants.slice(0, 20).map((v, i) => (
                        <tr key={i} className="text-zinc-300">
                          <td className="py-1 font-mono">{v.sku}</td>
                          <td className="py-1">{v.color || '--'}</td>
                          <td className="py-1">{v.size || '--'}</td>
                          <td className="py-1 text-right">{v.inventory}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {previewProduct.variants.length > 20 && (
                    <p className="text-xs text-zinc-500 mt-2">... and {previewProduct.variants.length - 20} more variants</p>
                  )}
                </div>
              </div>

              {/* Validation */}
              <div>
                <h3 className="text-sm font-semibold text-zinc-400 mb-2">Validation</h3>
                <div className={`rounded-lg p-4 ${previewProduct.validation.is_valid ? 'bg-green-900/20' : 'bg-red-900/20'}`}>
                  {previewProduct.validation.is_valid ? (
                    <div className="flex items-center gap-2 text-green-400">
                      <CheckCircle className="w-5 h-5" />
                      <span>Product is valid and ready for sync</span>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-center gap-2 text-red-400 mb-2">
                        <XCircle className="w-5 h-5" />
                        <span>Product has validation errors</span>
                      </div>
                      <ul className="list-disc list-inside text-sm text-red-300">
                        {previewProduct.validation.errors.map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
