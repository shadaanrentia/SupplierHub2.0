import React, { useState, useEffect, useCallback } from "react";
import axios from "../lib/axios";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { RefreshCw, FolderTree, ArrowRight, Check, X } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function CategoryMapping() {
  const [odooCategories, setOdooCategories] = useState([]);
  const [supplierCategories, setSupplierCategories] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [savingMapping, setSavingMapping] = useState({});
  const [selectedCategories, setSelectedCategories] = useState(new Set());

  const fetchData = useCallback(async () => {
    try {
      const [odooRes, supplierRes, mappingsRes] = await Promise.all([
        axios.get(`${API}/odoo/categories`),
        axios.get(`${API}/supplier-categories`),
        axios.get(`${API}/category-mappings`)
      ]);
      
      setOdooCategories(odooRes.data.categories || []);
      setSupplierCategories(supplierRes.data.categories || []);
      setMappings(mappingsRes.data.mappings || []);
      
      // Set selected categories from stored data
      const selected = new Set(
        (odooRes.data.categories || [])
          .filter(c => c.is_selected)
          .map(c => c.id)
      );
      setSelectedCategories(selected);
    } catch (e) {
      console.error("Failed to fetch data:", e);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const syncCategories = async () => {
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/odoo/sync-categories`);
      toast.success(`Synced ${res.data.synced} categories from Odoo`);
      fetchData();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to sync categories");
    } finally {
      setSyncing(false);
    }
  };

  const toggleCategorySelection = async (categoryId, isSelected) => {
    try {
      await axios.put(`${API}/odoo/categories/${categoryId}/select`, { is_selected: isSelected });
      setSelectedCategories(prev => {
        const newSet = new Set(prev);
        if (isSelected) {
          newSet.add(categoryId);
        } else {
          newSet.delete(categoryId);
        }
        return newSet;
      });
    } catch (e) {
      toast.error("Failed to update selection");
    }
  };

  const selectAll = async () => {
    const allIds = odooCategories.map(c => c.id);
    try {
      await axios.put(`${API}/odoo/categories/bulk-select`, { category_ids: allIds, is_selected: true });
      setSelectedCategories(new Set(allIds));
      toast.success("All categories selected");
    } catch (e) {
      toast.error("Failed to select all");
    }
  };

  const deselectAll = async () => {
    const allIds = odooCategories.map(c => c.id);
    try {
      await axios.put(`${API}/odoo/categories/bulk-select`, { category_ids: allIds, is_selected: false });
      setSelectedCategories(new Set());
      toast.success("All categories deselected");
    } catch (e) {
      toast.error("Failed to deselect all");
    }
  };

  const updateMapping = async (supplierCategory, odooValue) => {
    setSavingMapping(prev => ({ ...prev, [supplierCategory]: true }));
    try {
      const odooId = odooValue === "none" ? null : parseInt(odooValue);
      await axios.post(`${API}/category-mappings`, {
        supplier_category_name: supplierCategory,
        odoo_category_id: odooId
      });
      toast.success(`Mapped "${supplierCategory}"`);
      fetchData();
    } catch (e) {
      toast.error("Failed to save mapping");
    } finally {
      setSavingMapping(prev => ({ ...prev, [supplierCategory]: false }));
    }
  };

  const getMappingForSupplier = (supplierCategory) => {
    const mapping = mappings.find(m => m.supplier_category_name === supplierCategory);
    return mapping?.odoo_category_id?.toString() || "none";
  };

  const selectedOdooCategories = odooCategories.filter(c => selectedCategories.has(c.id));

  return (
    <div className="p-6 space-y-6" data-testid="category-mapping-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Category Mapping</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Sync Odoo categories and map them to supplier categories
          </p>
        </div>
      </div>

      {/* Step 1: Odoo Categories */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <FolderTree className="w-5 h-5 text-blue-400" />
              <CardTitle className="text-lg">Step 1: Odoo E-Commerce Categories</CardTitle>
            </div>
            <Button
              onClick={syncCategories}
              disabled={syncing}
              className="bg-blue-600 hover:bg-blue-700"
              data-testid="sync-categories-btn"
            >
              {syncing ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              Sync Categories
            </Button>
          </div>
          <p className="text-sm text-zinc-500 mt-2">
            Fetch categories from Odoo and select which ones to use for product mapping.
          </p>
        </CardHeader>
        <CardContent>
          {odooCategories.length > 0 ? (
            <>
              <div className="flex gap-2 mb-4">
                <Button variant="outline" size="sm" onClick={selectAll} className="text-xs">
                  <Check className="w-3 h-3 mr-1" /> Select All
                </Button>
                <Button variant="outline" size="sm" onClick={deselectAll} className="text-xs">
                  <X className="w-3 h-3 mr-1" /> Deselect All
                </Button>
                <span className="text-sm text-zinc-500 ml-4 self-center">
                  {selectedCategories.size} of {odooCategories.length} selected
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400">
                      <th className="text-left py-2 px-3 w-12">Select</th>
                      <th className="text-left py-2 px-3">Odoo Category ID</th>
                      <th className="text-left py-2 px-3">Category Name</th>
                      <th className="text-left py-2 px-3">Parent Category</th>
                    </tr>
                  </thead>
                  <tbody>
                    {odooCategories.map((cat) => (
                      <tr 
                        key={cat.id} 
                        className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
                        data-testid={`odoo-category-row-${cat.odoo_category_id}`}
                      >
                        <td className="py-2 px-3">
                          <Checkbox
                            checked={selectedCategories.has(cat.id)}
                            onCheckedChange={(checked) => toggleCategorySelection(cat.id, checked)}
                            data-testid={`category-checkbox-${cat.odoo_category_id}`}
                          />
                        </td>
                        <td className="py-2 px-3 font-mono text-zinc-400">{cat.odoo_category_id}</td>
                        <td className="py-2 px-3 text-zinc-100">{cat.category_name}</td>
                        <td className="py-2 px-3 text-zinc-500">{cat.parent_category || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="text-center py-10 text-zinc-500">
              <FolderTree className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No categories synced yet.</p>
              <p className="text-sm mt-1">Click "Sync Categories" to fetch from Odoo.</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Step 2: Supplier Category Mapping */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3">
            <ArrowRight className="w-5 h-5 text-green-400" />
            <CardTitle className="text-lg">Step 2: Supplier Category Mapping</CardTitle>
          </div>
          <p className="text-sm text-zinc-500 mt-2">
            Map supplier categories (from API) to Odoo categories for product sync.
          </p>
        </CardHeader>
        <CardContent>
          {supplierCategories.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-zinc-400">
                    <th className="text-left py-2 px-3">Supplier Category (SanMar API)</th>
                    <th className="text-left py-2 px-3 w-1/3">Odoo Category Mapping</th>
                    <th className="text-left py-2 px-3 w-20">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {supplierCategories.map((supplierCat) => {
                    const currentMapping = getMappingForSupplier(supplierCat);
                    const isMapped = currentMapping !== "none";
                    return (
                      <tr 
                        key={supplierCat} 
                        className="border-b border-zinc-800/50 hover:bg-zinc-800/30"
                        data-testid={`mapping-row-${supplierCat}`}
                      >
                        <td className="py-2 px-3 text-zinc-100 font-medium">{supplierCat}</td>
                        <td className="py-2 px-3">
                          <Select
                            value={currentMapping}
                            onValueChange={(value) => updateMapping(supplierCat, value)}
                            disabled={savingMapping[supplierCat]}
                          >
                            <SelectTrigger className="w-full bg-zinc-800 border-zinc-700">
                              <SelectValue placeholder="Select Odoo category" />
                            </SelectTrigger>
                            <SelectContent className="bg-zinc-900 border-zinc-800">
                              <SelectItem value="none">— Not Mapped —</SelectItem>
                              {selectedOdooCategories.map((odooCat) => (
                                <SelectItem 
                                  key={odooCat.odoo_category_id} 
                                  value={odooCat.odoo_category_id.toString()}
                                >
                                  {odooCat.category_name}
                                  {odooCat.parent_category && ` (${odooCat.parent_category})`}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </td>
                        <td className="py-2 px-3">
                          {savingMapping[supplierCat] ? (
                            <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
                          ) : isMapped ? (
                            <Check className="w-4 h-4 text-green-400" />
                          ) : (
                            <span className="text-zinc-500 text-xs">Not mapped</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-10 text-zinc-500">
              <ArrowRight className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No supplier categories found.</p>
              <p className="text-sm mt-1">Sync products from suppliers first to see their categories.</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Summary */}
      {mappings.length > 0 && (
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Mapping Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-blue-400">{odooCategories.length}</p>
                <p className="text-sm text-zinc-500">Odoo Categories</p>
              </div>
              <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-green-400">{selectedCategories.size}</p>
                <p className="text-sm text-zinc-500">Selected for Mapping</p>
              </div>
              <div className="bg-zinc-800/50 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-amber-400">
                  {mappings.filter(m => m.odoo_category_id).length} / {supplierCategories.length}
                </p>
                <p className="text-sm text-zinc-500">Categories Mapped</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
