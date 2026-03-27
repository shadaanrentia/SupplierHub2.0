import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Users, Plus, Pencil, KeyRound, Trash2, RefreshCw, Loader2, Shield, User } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const emptyForm = {
  username: "",
  email: "",
  password: "",
  role: "user",
};

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [resetPasswordDialog, setResetPasswordDialog] = useState(null);
  const [newPassword, setNewPassword] = useState("");
  const [resettingPassword, setResettingPassword] = useState(false);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/users`);
      setUsers(res.data.users || []);
    } catch (e) {
      toast.error("Failed to fetch users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSave = async () => {
    if (!form.username) {
      toast.error("Username is required");
      return;
    }
    if (!editing && !form.password) {
      toast.error("Password is required for new users");
      return;
    }

    setSaving(true);
    try {
      if (editing) {
        await axios.put(`${API}/users/${editing}`, {
          username: form.username,
          email: form.email,
          role: form.role,
          ...(form.password && { password: form.password }),
        });
        toast.success("User updated");
      } else {
        await axios.post(`${API}/users`, form);
        toast.success("User created");
      }
      setDialogOpen(false);
      setEditing(null);
      setForm(emptyForm);
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to save user");
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (user) => {
    setEditing(user.id);
    setForm({
      username: user.username,
      email: user.email || "",
      password: "",
      role: user.role || "user",
    });
    setDialogOpen(true);
  };

  const handleDelete = async (userId, username) => {
    if (!window.confirm(`Delete user "${username}"?`)) return;
    try {
      await axios.delete(`${API}/users/${userId}`);
      toast.success("User deleted");
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to delete user");
    }
  };

  const handleResetPassword = async () => {
    if (!newPassword || newPassword.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }
    setResettingPassword(true);
    try {
      await axios.post(`${API}/users/${resetPasswordDialog.id}/reset-password`, {
        new_password: newPassword,
      });
      toast.success(`Password reset for ${resetPasswordDialog.username}`);
      setResetPasswordDialog(null);
      setNewPassword("");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to reset password");
    } finally {
      setResettingPassword(false);
    }
  };

  const openNewUserDialog = () => {
    setEditing(null);
    setForm(emptyForm);
    setDialogOpen(true);
  };

  return (
    <div className="p-6 space-y-6" data-testid="users-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-3xl font-bold tracking-tight">User Management</h1>
          <p className="text-zinc-500 text-sm mt-1">Manage system users and access</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={fetchUsers} variant="outline" className="rounded-none border-zinc-700 text-zinc-300 hover:bg-zinc-800" data-testid="refresh-users-btn">
            <RefreshCw className="w-4 h-4" />
          </Button>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button onClick={openNewUserDialog} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="add-user-btn">
                <Plus className="w-4 h-4 mr-2" /> Add User
              </Button>
            </DialogTrigger>
            <DialogContent className="bg-zinc-900 border-zinc-800 rounded-none max-w-md">
              <DialogHeader>
                <DialogTitle className="font-heading text-lg">{editing ? "Edit User" : "Create User"}</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 mt-4">
                <div>
                  <label className="text-sm text-zinc-400 mb-1 block">Username *</label>
                  <Input
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none"
                    placeholder="Enter username"
                    data-testid="user-username-input"
                  />
                </div>
                <div>
                  <label className="text-sm text-zinc-400 mb-1 block">Email</label>
                  <Input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none"
                    placeholder="Enter email (optional)"
                    data-testid="user-email-input"
                  />
                </div>
                <div>
                  <label className="text-sm text-zinc-400 mb-1 block">
                    Password {editing ? "(leave blank to keep current)" : "*"}
                  </label>
                  <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="bg-zinc-950 border-zinc-800 rounded-none"
                    placeholder={editing ? "Enter new password" : "Enter password"}
                    data-testid="user-password-input"
                  />
                </div>
                <div>
                  <label className="text-sm text-zinc-400 mb-1 block">Role</label>
                  <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                    <SelectTrigger className="bg-zinc-950 border-zinc-800 rounded-none" data-testid="user-role-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-zinc-900 border-zinc-800">
                      <SelectItem value="admin">Admin</SelectItem>
                      <SelectItem value="user">User</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-none border-zinc-700 text-zinc-300" data-testid="cancel-user-btn">
                    Cancel
                  </Button>
                  <Button onClick={handleSave} disabled={saving} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="save-user-btn">
                    {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                    {editing ? "Update" : "Create"}
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Users Table */}
      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm">
        <CardHeader className="p-4 border-b border-zinc-800/50">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-blue-400" />
            <CardTitle className="font-heading text-sm font-bold uppercase text-zinc-400 tracking-wider">System Users</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center">
              <Loader2 className="w-6 h-6 animate-spin mx-auto text-zinc-500" />
            </div>
          ) : users.length === 0 ? (
            <div className="p-8 text-center text-zinc-500">
              <Users className="w-10 h-10 mx-auto mb-2 text-zinc-700" />
              <p className="font-mono text-sm">NO USERS FOUND</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="text-zinc-400 font-mono text-xs uppercase">Username</TableHead>
                  <TableHead className="text-zinc-400 font-mono text-xs uppercase">Email</TableHead>
                  <TableHead className="text-zinc-400 font-mono text-xs uppercase">Role</TableHead>
                  <TableHead className="text-zinc-400 font-mono text-xs uppercase">Created</TableHead>
                  <TableHead className="text-zinc-400 font-mono text-xs uppercase text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id} className="border-zinc-800" data-testid={`user-row-${user.id}`}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {user.role === "admin" ? (
                          <Shield className="w-4 h-4 text-amber-500" />
                        ) : (
                          <User className="w-4 h-4 text-zinc-500" />
                        )}
                        {user.username}
                      </div>
                    </TableCell>
                    <TableCell className="text-zinc-400">{user.email || "-"}</TableCell>
                    <TableCell>
                      <span className={`px-2 py-0.5 text-xs font-mono border rounded-none ${user.role === "admin" ? "bg-amber-950/50 text-amber-400 border-amber-800" : "bg-zinc-800 text-zinc-400 border-zinc-700"}`}>
                        {user.role}
                      </span>
                    </TableCell>
                    <TableCell className="text-zinc-500 text-sm">
                      {user.created_at ? new Date(user.created_at).toLocaleDateString() : "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(user)}
                          className="text-zinc-400 hover:text-white rounded-none"
                          data-testid={`edit-user-${user.id}`}
                        >
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setResetPasswordDialog(user);
                            setNewPassword("");
                          }}
                          className="text-zinc-400 hover:text-white rounded-none"
                          data-testid={`reset-password-${user.id}`}
                        >
                          <KeyRound className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDelete(user.id, user.username)}
                          className="text-zinc-400 hover:text-red-400 rounded-none"
                          data-testid={`delete-user-${user.id}`}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Reset Password Dialog */}
      <Dialog open={!!resetPasswordDialog} onOpenChange={(open) => !open && setResetPasswordDialog(null)}>
        <DialogContent className="bg-zinc-900 border-zinc-800 rounded-none max-w-sm">
          <DialogHeader>
            <DialogTitle className="font-heading text-lg">Reset Password</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            <p className="text-sm text-zinc-400">
              Enter a new password for <span className="text-white font-medium">{resetPasswordDialog?.username}</span>
            </p>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="bg-zinc-950 border-zinc-800 rounded-none"
              placeholder="New password (min 6 characters)"
              data-testid="new-password-input"
            />
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setResetPasswordDialog(null)} className="rounded-none border-zinc-700 text-zinc-300">
                Cancel
              </Button>
              <Button onClick={handleResetPassword} disabled={resettingPassword} className="bg-blue-600 hover:bg-blue-500 text-white rounded-none" data-testid="confirm-reset-password-btn">
                {resettingPassword ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                Reset Password
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
