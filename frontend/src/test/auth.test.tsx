import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { Login } from "../pages/Login";
import { AuthenticatedRoute, PermissionGuard, useAuth } from "../auth/Auth";
import { AppRoutes } from "../App";
import { admin, mockFetch, renderAuth, respond } from "./helpers";
function Identity() {
  const { user } = useAuth();
  return <p>{user?.username}</p>;
}
function authRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<AuthenticatedRoute />}>
        <Route path="/dashboard" element={<Identity />} />
      </Route>
    </Routes>
  );
}
describe("staff authentication", () => {
  it("recovers session using auth/me", async () => {
    const fetch = mockFetch();
    renderAuth(<Identity />);
    expect(await screen.findByText("staff-demo")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });
  it("shows labeled login fields and no stored secrets", async () => {
    mockFetch(undefined, null);
    const local = vi.spyOn(Storage.prototype, "setItem");
    renderAuth(authRoutes(), "/login");
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "type",
      "password",
    );
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Password"), "temporary-secret");
    expect(local).not.toHaveBeenCalled();
  });
  it("logs in and navigates to the recovered identity", async () => {
    let logged = false;
    const fetch = vi.fn((path: string) =>
      Promise.resolve(
        path.endsWith("/auth/me")
          ? respond(logged ? admin : {}, logged ? 200 : 401)
          : ((logged = true), respond({})),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    renderAuth(authRoutes(), "/login");
    await userEvent.type(screen.getByLabelText("Username"), "staff");
    await userEvent.type(screen.getByLabelText("Password"), "entered-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("staff-demo")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/auth/login",
      expect.objectContaining({
        body: JSON.stringify({
          username: "staff",
          password: "entered-password",
        }),
      }),
    );
  });
  it("shows a safe invalid login error and clears password", async () => {
    mockFetch(() => respond({ detail: "private SQL" }, 401), null);
    renderAuth(authRoutes(), "/login");
    await userEvent.type(screen.getByLabelText("Username"), "staff");
    await userEvent.type(screen.getByLabelText("Password"), "invalid");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("SQL");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
  it.each([false, true])(
    "handles MFA challenge recovery=%s",
    async (recovery) => {
      let logged = false;
      const fetch = vi.fn((path: string) =>
        Promise.resolve(
          path.endsWith("/auth/me")
            ? respond(logged ? admin : {}, logged ? 200 : 401)
            : path.endsWith("/login")
              ? respond(
                  { mfa_required: true, methods: ["TOTP", "RECOVERY_CODE"] },
                  202,
                )
              : ((logged = true), respond({})),
        ),
      );
      vi.stubGlobal("fetch", fetch);
      renderAuth(authRoutes(), "/login");
      await userEvent.type(screen.getByLabelText("Username"), "staff");
      await userEvent.type(screen.getByLabelText("Password"), "temporary");
      await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
      expect(
        await screen.findByRole("heading", { name: "Verify your sign-in" }),
      ).toBeInTheDocument();
      if (recovery)
        await userEvent.click(
          screen.getByRole("button", { name: "Use recovery code" }),
        );
      await userEvent.type(
        screen.getByLabelText(
          recovery ? "Recovery code" : "Authenticator code",
        ),
        recovery ? "ABCD-EFGH" : "123456",
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Verify and continue" }),
      );
      expect(await screen.findByText("staff-demo")).toBeInTheDocument();
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/auth/mfa/" + (recovery ? "recovery" : "verify"),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify(
            recovery ? { recovery_code: "ABCD-EFGH" } : { code: "123456" },
          ),
        }),
      );
    },
  );
  it("blocks an unauthenticated route", async () => {
    mockFetch(undefined, null);
    renderAuth(authRoutes(), "/dashboard");
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
  });
  it("permits authenticated navigation", async () => {
    mockFetch();
    renderAuth(authRoutes(), "/dashboard");
    expect(await screen.findByText("staff-demo")).toBeInTheDocument();
  });
  it("blocks permission protected content", async () => {
    mockFetch(undefined, { ...admin, roles: ["STAFF"], permissions: [] });
    renderAuth(
      <PermissionGuard permission="PATIENT_READ">
        <span>Private directory</span>
      </PermissionGuard>,
    );
    await waitFor(() =>
      expect(screen.getByText("Permission required")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Private directory")).not.toBeInTheDocument();
  });
  it("logs out with CSRF and removes private application state", async () => {
    document.cookie = "rhu_csrf=test-csrf; path=/";
    const fetch = mockFetch();
    renderAuth(<AppRoutes />, "/dashboard");
    await screen.findByText("Laboratory overview");
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Laboratory overview")).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/auth/logout",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf" }),
      }),
    );
  });
});
