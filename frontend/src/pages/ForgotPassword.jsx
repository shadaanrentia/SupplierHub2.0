import { useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, Mail, Package, CheckCircle, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email) {
      toast.error("Please enter your email");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API}/auth/reset-password`, { email });
      setSuccess(true);
    } catch (e) {
      toast.error("Failed to send reset email");
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
        <Card className="w-full max-w-md bg-zinc-900 border-zinc-800 rounded-sm" data-testid="reset-success-card">
          <CardContent className="pt-8 pb-8 text-center">
            <div className="w-16 h-16 bg-blue-600/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle className="w-8 h-8 text-blue-400" />
            </div>
            <h2 className="text-xl font-heading text-white mb-2">Check Your Email</h2>
            <p className="text-zinc-400 mb-6">
              If an account exists with that email, you will receive a password reset link shortly.
            </p>
            <Link to="/login">
              <Button className="bg-blue-600 hover:bg-blue-500 rounded-none" data-testid="back-to-login">
                <ArrowLeft className="w-4 h-4 mr-2" /> Back to Login
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <Card className="w-full max-w-md bg-zinc-900 border-zinc-800 rounded-sm" data-testid="forgot-password-card">
        <CardHeader className="text-center pb-2">
          <div className="flex items-center justify-center gap-2 mb-4">
            <div className="w-10 h-10 bg-blue-600 flex items-center justify-center">
              <Package className="w-6 h-6 text-white" strokeWidth={1.5} />
            </div>
            <span className="text-xl font-heading tracking-wide">SupplierHub</span>
          </div>
          <CardTitle className="font-heading text-xl">Reset Password</CardTitle>
          <CardDescription className="text-zinc-500">Enter your email to receive a reset link</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs text-zinc-500 mb-1 block">Email Address</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="bg-zinc-950 border-zinc-800 rounded-none"
                data-testid="reset-email"
              />
            </div>
            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white rounded-none"
              data-testid="reset-submit"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Mail className="w-4 h-4 mr-2" />}
              {loading ? "Sending..." : "Send Reset Link"}
            </Button>
          </form>
          <div className="mt-6 pt-4 border-t border-zinc-800">
            <Link to="/login" className="flex items-center justify-center gap-2 text-sm text-zinc-400 hover:text-white" data-testid="back-link">
              <ArrowLeft className="w-4 h-4" /> Back to Login
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
