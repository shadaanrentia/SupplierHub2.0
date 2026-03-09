import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, LogIn, Package } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Login({ onLogin }) {
  const [form, setForm] = useState({ username: "", password: "" });
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.username || !form.password) {
      toast.error("Please enter username and password");
      return;
    }
    setLoading(true);
    try {
      const res = await axios.post(`${API}/auth/login`, form);
      localStorage.setItem("token", res.data.token);
      localStorage.setItem("user", JSON.stringify(res.data.user));
      onLogin(res.data.user);
      toast.success(`Welcome back, ${res.data.user.full_name || res.data.user.username}!`);
      navigate("/");
    } catch (e) {
      const msg = e.response?.data?.detail || "Login failed";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <Card className="w-full max-w-md bg-zinc-900 border-zinc-800 rounded-sm" data-testid="login-card">
        <CardHeader className="text-center pb-2">
          <div className="flex items-center justify-center gap-2 mb-4">
            <div className="w-10 h-10 bg-blue-600 flex items-center justify-center">
              <Package className="w-6 h-6 text-white" strokeWidth={1.5} />
            </div>
            <span className="text-xl font-heading tracking-wide">SupplierHub</span>
          </div>
          <CardTitle className="font-heading text-xl">Sign In</CardTitle>
          <CardDescription className="text-zinc-500">Enter your credentials to access the dashboard</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Username</label>
              <Input
                type="text"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="Enter username"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono"
                data-testid="login-username"
                autoComplete="username"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Password</label>
              <Input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="Enter password"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono"
                data-testid="login-password"
                autoComplete="current-password"
              />
            </div>
            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white rounded-none"
              data-testid="login-submit"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <LogIn className="w-4 h-4 mr-2" />}
              {loading ? "Signing in..." : "Sign In"}
            </Button>
          </form>
          <div className="mt-6 pt-4 border-t border-zinc-800 space-y-2">
            <Link to="/forgot-password" className="block text-sm text-blue-400 hover:text-blue-300 text-center" data-testid="forgot-password-link">
              Forgot password?
            </Link>
            <p className="text-sm text-zinc-500 text-center">
              Don't have an account?{" "}
              <Link to="/register" className="text-blue-400 hover:text-blue-300" data-testid="register-link">
                Create account
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
