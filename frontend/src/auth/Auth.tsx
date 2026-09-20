import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Outlet } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { User } from "../types/domain";
interface AuthState {
  user: User | null;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<User>;
  clear: () => void;
  can: (permission: string) => boolean;
}
const AuthContext = createContext<AuthState>(null!);
export const useAuth = () => useContext(AuthContext);
export function allowed(user: User | null, permission: string) {
  return (
    !!user &&
    (user.roles.includes("SYSTEM_ADMIN") ||
      user.permissions.includes(permission))
  );
}
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  async function refresh() {
    const current = await api<User>("/auth/me");
    setUser(current);
    setError(null);
    return current;
  }
  function clear() {
    setUser(null);
    setError(null);
  }
  useEffect(() => {
    let active = true;
    api<User>("/auth/me")
      .then((u) => {
        if (active) setUser(u);
      })
      .catch((e) => {
        if (active && !(e instanceof ApiError && e.status === 401)) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    const expired = () => clear();
    window.addEventListener("session-expired", expired);
    return () => {
      active = false;
      window.removeEventListener("session-expired", expired);
    };
  }, []);
  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        error,
        refresh,
        clear,
        can: (p) => allowed(user, p),
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export function AuthenticatedRoute() {
  const { user, loading, error, refresh } = useAuth();
  if (loading)
    return (
      <p role="status" className="splash">
        Opening your workspace…
      </p>
    );
  if (error)
    return (
      <div className="splash">
        <p role="alert">{error.message}</p>
        <button onClick={() => refresh().catch(() => undefined)}>Retry</button>
      </div>
    );
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}
export function PermissionGuard({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const { can } = useAuth();
  return can(permission) ? (
    <>{children}</>
  ) : (
    <section className="card">
      <h1>Permission required</h1>
      <p>You do not have access to this section. Contact your administrator.</p>
    </section>
  );
}
