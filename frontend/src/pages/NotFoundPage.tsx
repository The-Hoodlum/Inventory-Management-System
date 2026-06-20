import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-100 text-center">
      <div className="text-3xl font-semibold text-slate-800">404</div>
      <p className="text-sm text-slate-500">That page doesn’t exist.</p>
      <Link to="/dashboard" className="text-sm font-medium text-brand-600 hover:underline">
        Go to dashboard
      </Link>
    </div>
  );
}
