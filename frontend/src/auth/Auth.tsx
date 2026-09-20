import {
  createContext,
  useContext,
  useEffect,
  useState,
  useRef,
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
  clear: (notice?: string) => void;
  notice: string | null;
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
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const sessionRequest = useRef<AbortController | null>(null);
  async function refresh() {
    sessionRequest.current?.abort();
    const controller = new AbortController();
    sessionRequest.current = controller;
    try {
      const current = await api<User>("/auth/me", {
        signal: controller.signal,
      });
      if (controller.signal.aborted)
        throw new DOMException("Request cancelled", "AbortError");
      setUser(current);
      setNotice(null);
      setError(null);
      return current;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  function clear(message?: string) {
    sessionRequest.current?.abort();
    setNotice(message || null);
    setUser(null);
    setError(null);
    setLoading(false);
  }
  useEffect(() => {
    const controller = new AbortController();
    sessionRequest.current = controller;
    api<User>("/auth/me", { signal: controller.signal })
      .then((u) => {
        if (!controller.signal.aborted) setUser(u);
      })
      .catch((e) => {
        if (
          !controller.signal.aborted &&
          !(e instanceof ApiError && e.status === 401)
        )
          setError(e);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    const expired = () => clear();
    window.addEventListener("session-expired", expired);
    return () => {
      controller.abort();
      sessionRequest.current?.abort();
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
        notice,
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
  return user ? (
    user.roles.includes("PATIENT") ? (
      <Navigate to="/patient" replace />
    ) : (
      <Outlet />
    )
  ) : (
    <Navigate to="/login" replace />
  );
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
