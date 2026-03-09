import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Users as UsersIcon, Check, X, Trash2, Shield, User, Clock, Loader2 } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const getAuthHeader = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem("token")}` }
});

export default function Users() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(null);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/users`, getAuthHeader());
      setUsers(res.data.users || []);
    } catch (e) {
      toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleApprove = async (userId, approve) => {
    setProcessing(userId);
    try {
      await axios.post(`${API}/users/${userId}/approve`, { user_id: userId, approved: approve }, getAuthHeader());
      toast.success(approve ? "User approved" : "User rejected");
      fetchUsers();
    } catch (e) {
      toast.error("Failed to update user status");
    } finally {
      setProcessing(null);
    }
  };

  const handleDelete = async (userId) => {
    if (!window.confirm("Are you sure you want to delete this user?")) return;
    setProcessing(userId);
    try {
      await axios.delete(`${API}/users/${userId}`, getAuthHeader());
      toast.success("User deleted");
      fetchUsers();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to delete user");
    } finally {
      setProcessing(null);
    }
  };

  const pendingUsers = users.filter(u => u.status === "pending");
  const activeUsers = users.filter(u => u.status === "approved");
  const rejectedUsers = users.filter(u => u.status === "rejected");

  const StatusBadge = ({ status }) => {
    const styles = {
      pending: "bg-amber-950/50 text-amber-400 border-amber-800",
      approved: "bg-emerald-950/50 text-emerald-400 border-emerald-800",
      rejected: "bg-red-950/50 text-red-400 border-red-800"
    };
    return (
      <span className={`px-2 py-0.5 text-xs font-mono border rounded-none ${styles[status] || styles.pending}`}>
        {status}
      </span>
    );
  };

  const RoleBadge = ({ role }) => (
    <span className={`px-2 py-0.5 text-xs font-mono border rounded-none ${role === "admin" ? "bg-blue-950/50 text-blue-400 border-blue-800" : "bg-zinc-800 text-zinc-400 border-zinc-700"}`}>
      {role === "admin" ? <Shield className="w-3 h-3 inline mr-1" /> : <User className="w-3 h-3 inline mr-1" />}
      {role}
    </span>
  );

  const UserRow = ({ user, showActions = true }) => (
    <div className="flex items-center justify-between p-4 border-b border-zinc-800 last:border-b-0 hover:bg-zinc-900/50" data-testid={`user-row-${user.id}`}>
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 bg-zinc-800 rounded-full flex items-center justify-center border border-zinc-700">
          {user.role === "admin" ? <Shield className="w-5 h-5 text-blue-400" /> : <User className="w-5 h-5 text-zinc-400" />}
        </div>
        <div>
          <p className="font-medium text-zinc-200">{user.name}</p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span className="text-xs font-mono text-zinc-500">@{user.username}</span>
            <span className="text-zinc-700">|</span>
            <span className="text-xs text-zinc-500">{user.email}</span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <RoleBadge role={user.role} />
        <StatusBadge status={user.status} />
        {showActions && user.status === "pending" && (
          <div className="flex gap-1 ml-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => handleApprove(user.id, true)}
              disabled={processing === user.id}
              className="text-emerald-400 hover:text-emerald-300 hover:bg-emerald-950/30 rounded-none"
              data-testid={`approve-${user.id}`}
            >
              {processing === user.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => handleApprove(user.id, false)}
              disabled={processing === user.id}
              className="text-red-400 hover:text-red-300 hover:bg-red-950/30 rounded-none"
              data-testid={`reject-${user.id}`}
            >
              <X className="w-4 h-4" />
            </Button>
          </div>
        )}
        {showActions && user.username !== "admin" && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => handleDelete(user.id)}
            disabled={processing === user.id}
            className="text-zinc-400 hover:text-red-400 rounded-none ml-1"
            data-testid={`delete-${user.id}`}
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        )}
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="users-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading tracking-tight">User Management</h1>
          <p className="text-zinc-500 text-sm mt-1">Approve new users and manage existing accounts</p>
        </div>
      </div>

      {pendingUsers.length > 0 && (
        <Card className="bg-amber-950/20 border-amber-800/50 rounded-sm" data-testid="pending-users-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg font-heading flex items-center gap-2">
              <Clock className="w-5 h-5 text-amber-400" />
              Pending Approvals ({pendingUsers.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {pendingUsers.map(user => <UserRow key={user.id} user={user} />)}
          </CardContent>
        </Card>
      )}

      <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm" data-testid="active-users-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg font-heading flex items-center gap-2">
            <UsersIcon className="w-5 h-5 text-blue-400" />
            Active Users ({activeUsers.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {activeUsers.length === 0 ? (
            <div className="p-6 text-center text-zinc-500">No active users</div>
          ) : (
            activeUsers.map(user => <UserRow key={user.id} user={user} />)
          )}
        </CardContent>
      </Card>

      {rejectedUsers.length > 0 && (
        <Card className="bg-zinc-900/50 border-zinc-800 rounded-sm" data-testid="rejected-users-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg font-heading flex items-center gap-2 text-zinc-400">
              <X className="w-5 h-5 text-red-400" />
              Rejected Users ({rejectedUsers.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {rejectedUsers.map(user => <UserRow key={user.id} user={user} />)}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
