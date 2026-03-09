import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, UserPlus, Package, CheckCircle } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function Register() {
  const [form, setForm] = useState({ name: "", email: "", username: "", password: "", confirmPassword: "" });
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name || !form.email || !form.username || !form.password) {
      toast.error("Please fill in all fields");
      return;
    }
    if (form.password !== form.confirmPassword) {
      toast.error("Passwords do not match");
      return;
    }
    if (form.password.length < 4) {
      toast.error("Password must be at least 4 characters");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API}/auth/register`, {
        name: form.name,
        email: form.email,
        username: form.username,
        password: form.password
      });
      setSuccess(true);
    } catch (e) {
      const msg = e.response?.data?.detail || "Registration failed";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
        <Card className="w-full max-w-md bg-zinc-900 border-zinc-800 rounded-sm" data-testid="register-success-card">
          <CardContent className="pt-8 pb-8 text-center">
            <div className="w-16 h-16 bg-emerald-600/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle className="w-8 h-8 text-emerald-400" />
            </div>
            <h2 className="text-xl font-heading text-white mb-2">Registration Successful!</h2>
            <p className="text-zinc-400 mb-6">
              Your account has been created and is pending admin approval. You will be notified once your account is approved.
            </p>
            <Button onClick={() => navigate("/login")} className="bg-blue-600 hover:bg-blue-500 rounded-none" data-testid="back-to-login">
              Back to Login
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <Card className="w-full max-w-md bg-zinc-900 border-zinc-800 rounded-sm" data-testid="register-card">
        <CardHeader className="text-center pb-2">
          <div className="flex items-center justify-center gap-2 mb-4">
            <div className="w-10 h-10 bg-blue-600 flex items-center justify-center">
              <Package className="w-6 h-6 text-white" strokeWidth={1.5} />
            </div>
            <span className="text-xl font-heading tracking-wide">SupplierHub</span>
          </div>
          <CardTitle className="font-heading text-xl">Create Account</CardTitle>
          <CardDescription className="text-zinc-500">Register for access to the supplier dashboard</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Full Name</label>
              <Input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="John Doe"
                className="bg-zinc-950 border-zinc-800 rounded-none"
                data-testid="register-name"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Email</label>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="john@company.com"
                className="bg-zinc-950 border-zinc-800 rounded-none"
                data-testid="register-email"
              />
            </div>
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Username</label>
              <Input
                type="text"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="johndoe"
                className="bg-zinc-950 border-zinc-800 rounded-none font-mono"
                data-testid="register-username"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Password</label>
                <Input
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="****"
                  className="bg-zinc-950 border-zinc-800 rounded-none"
                  data-testid="register-password"
                />
              </div>
              <div>
                <label className="text-xs text-zinc-500 mb-1 block">Confirm Password</label>
                <Input
                  type="password"
                  value={form.confirmPassword}
                  onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
                  placeholder="****"
                  className="bg-zinc-950 border-zinc-800 rounded-none"
                  data-testid="register-confirm-password"
                />
              </div>
            </div>
            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white rounded-none"
              data-testid="register-submit"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <UserPlus className="w-4 h-4 mr-2" />}
              {loading ? "Creating account..." : "Create Account"}
            </Button>
          </form>
          <div className="mt-6 pt-4 border-t border-zinc-800">
            <p className="text-sm text-zinc-500 text-center">
              Already have an account?{" "}
              <Link to="/login" className="text-blue-400 hover:text-blue-300" data-testid="login-link">
                Sign in
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
