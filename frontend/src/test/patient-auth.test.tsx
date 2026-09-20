import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { accessStage } from "../auth/PatientAccess";
import { admin, page, respond } from "./helpers";
import {
  patientUser,
  patientFetch,
  portal,
  limited,
  security,
  profile,
} from "./patient.helpers";
async function activate(confirm = "long-test-password") {
  await userEvent.type(
    screen.getByLabelText("Activation token"),
    "manual-test-token",
  );
  await userEvent.type(screen.getByLabelText("Username"), "chosen-user");
  await userEvent.type(screen.getByLabelText("Password"), "long-test-password");
  await userEvent.type(screen.getByLabelText("Confirm password"), confirm);
  await userEvent.click(
    screen.getByRole("button", { name: "Activate account" }),
  );
}
async function login() {
  await userEvent.type(screen.getByLabelText("Username"), "patient-test");
  await userEvent.type(screen.getByLabelText("Password"), "test-password");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}
describe("activation", () => {
  it("renders labeled activation fields without role selection", () => {
    patientFetch(undefined, null);
    portal("/patient/activate");
    expect(screen.getByLabelText("Activation token")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "minLength",
      "12",
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
  it("requires matching passwords and clears submitted secrets", async () => {
    const fetch = patientFetch(undefined, null);
    portal("/patient/activate");
    await activate("different-password");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Passwords must match",
    );
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/activate"))).toBe(false);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Activation token")).toHaveValue("");
  });
  it("submits only allowed activation fields without persistence, then offers login", async () => {
    const fetch = patientFetch(() => respond({}), null);
    const storage = vi.spyOn(Storage.prototype, "setItem");
    portal("/patient/activate");
    await activate();
    expect(
      await screen.findByRole("heading", { name: "Activation complete" }),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/patient/activate",
      expect.objectContaining({
        body: '{"activation_token":"manual-test-token","username":"chosen-user","password":"long-test-password"}',
        credentials: "include",
      }),
    );
    expect(storage).not.toHaveBeenCalled();
    expect(
      screen.queryByDisplayValue("manual-test-token"),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Go to login" }));
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
  });
  it.each([400, 409, 422])(
    "shows safe activation failure for %s",
    async (status) => {
      patientFetch(
        (_, o) =>
          o.method === "POST"
            ? respond({ detail: "private token hash SQL" }, status)
            : undefined,
        null,
      );
      portal("/patient/activate");
      await activate();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Activation could not be completed",
      );
      expect(screen.getByRole("alert")).not.toHaveTextContent("SQL");
    },
  );
});
describe("role-aware patient sign-in", () => {
  it.each([true, false])(
    "uses auth/me identity to select patient=%s destination",
    async (patient) => {
      let signed = false;
      const fetch = vi.fn((path: string) =>
        Promise.resolve(
          path.endsWith("/auth/me")
            ? respond(
                signed ? (patient ? patientUser : admin) : {},
                signed ? 200 : 401,
              )
            : path.endsWith("/auth/login")
              ? ((signed = true),
                respond({ roles: patient ? ["SYSTEM_ADMIN"] : ["PATIENT"] }))
              : path.endsWith("/patient/security")
                ? respond(security)
                : path.endsWith("/patient/me")
                  ? respond(profile)
                  : respond(page([])),
        ),
      );
      vi.stubGlobal("fetch", fetch);
      portal("/patient/login");
      await login();
      expect(
        await screen.findByRole("heading", {
          name: patient ? "Your patient portal" : "Laboratory overview",
        }),
      ).toBeInTheDocument();
    },
  );
  it.each([false, true])(
    "handles patient MFA challenge recovery=%s",
    async (recovery) => {
      let signed = false;
      const fetch = vi.fn((path: string) =>
        Promise.resolve(
          path.endsWith("/auth/me")
            ? respond(signed ? patientUser : {}, signed ? 200 : 401)
            : path.endsWith("/auth/login")
              ? respond({ mfa_required: true }, 202)
              : path.includes("/auth/mfa/")
                ? ((signed = true), respond({}))
                : path.endsWith("/patient/security")
                  ? respond(security)
                  : path.endsWith("/patient/me")
                    ? respond(profile)
                    : respond(page([])),
        ),
      );
      vi.stubGlobal("fetch", fetch);
      const storage = vi.spyOn(Storage.prototype, "setItem");
      portal("/patient/login");
      await login();
      expect(
        await screen.findByRole("heading", { name: "Verify your sign-in" }),
      ).toBeInTheDocument();
      expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
      if (recovery)
        await userEvent.click(
          screen.getByRole("button", { name: "Use recovery code" }),
        );
      await userEvent.type(
        screen.getByLabelText(
          recovery ? "Recovery code" : "Authenticator code",
        ),
        recovery ? "TEST-RECOVERY" : "123456",
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Verify and continue" }),
      );
      expect(
        await screen.findByRole("heading", { name: "Your patient portal" }),
      ).toBeInTheDocument();
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/auth/mfa/" + (recovery ? "recovery" : "verify"),
        expect.objectContaining({
          body: recovery
            ? '{"recovery_code":"TEST-RECOVERY"}'
            : '{"code":"123456"}',
        }),
      );
      expect(storage).not.toHaveBeenCalled();
    },
  );
  it("shows generic invalid MFA message and clears the code", async () => {
    patientFetch(
      () => respond({ detail: "MFA challenge internal hash" }, 401),
      null,
    );
    portal("/patient/mfa");
    await userEvent.type(screen.getByLabelText("Authenticator code"), "123456");
    await userEvent.click(
      screen.getByRole("button", { name: "Verify and continue" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign-in failed",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("internal");
    expect(screen.getByLabelText("Authenticator code")).toHaveValue("");
  });
});
describe("patient policy guards", () => {
  it("blocks anonymous patient pages", async () => {
    const fetch = patientFetch(undefined, null);
    portal("/patient/reports");
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      fetch.mock.calls.some(([p]) => p.startsWith("/api/v1/patient/reports")),
    ).toBe(false);
  });
  it("routes staff to their existing workspace", async () => {
    patientFetch(undefined, admin);
    portal("/patient");
    expect(
      await screen.findByRole("heading", { name: "Laboratory overview" }),
    ).toBeInTheDocument();
  });
  it("routes patients away from staff routes", async () => {
    patientFetch();
    portal("/patients");
    expect(
      await screen.findByRole("heading", { name: "Your patient portal" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Main navigation" }),
    ).not.toBeInTheDocument();
  });
  it("requires MFA setup before any clinical fetch", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/security") ? respond(limited) : undefined,
    );
    portal("/patient/reports");
    expect(
      await screen.findByRole("heading", { name: "Set up your authenticator" }),
    ).toBeInTheDocument();
    expect(fetch.mock.calls.some(([p]) => p.includes("/patient/reports"))).toBe(
      false,
    );
  });
  it("allows reports when backend MFA policy is optional", async () => {
    patientFetch((p) =>
      p.endsWith("/security")
        ? respond({ ...limited, mfa_required: false })
        : undefined,
    );
    portal("/patient/reports");
    expect(await screen.findByText("RPT-007")).toBeInTheDocument();
  });
  it("returns unverified enabled sessions to login without a loop", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/security")
        ? respond({ ...security, mfa_verified_for_current_session: false })
        : undefined,
    );
    portal("/patient");
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Please sign in again and verify/),
    ).toBeInTheDocument();
    expect(
      fetch.mock.calls.filter(([p]) => p.endsWith("/patient/security")),
    ).toHaveLength(1);
  });
  it.each([
    "MFA_ENROLLMENT_REQUIRED",
    "MFA_REQUIRED",
    "MFA verification required.",
  ])("handles authoritative policy error %s", async (code) => {
    patientFetch((p) =>
      p.includes("/patient/reports?")
        ? respond({ detail: code }, 403)
        : undefined,
    );
    portal("/patient/reports");
    if (code !== "MFA_ENROLLMENT_REQUIRED")
      expect(
        await screen.findByRole("button", { name: "Sign in" }),
      ).toBeInTheDocument();
    else
      expect(
        await screen.findByRole("button", {
          name: "Start authenticator setup",
        }),
      ).toBeInTheDocument();
  });
  it("clears patient state after an expired clinical session", async () => {
    patientFetch((p) =>
      p.includes("/patient/reports?") ? respond({}, 401) : undefined,
    );
    portal("/patient/reports");
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Patient navigation" }),
    ).not.toBeInTheDocument();
  });
  it("logs out using cookie CSRF and clears the patient shell", async () => {
    document.cookie = "rhu_csrf=patient-csrf; path=/";
    const fetch = patientFetch();
    portal();
    await userEvent.click(
      await screen.findByRole("button", { name: "Log out" }),
    );
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/auth/logout",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-CSRF-Token": "patient-csrf" }),
      }),
    );
  });
  it("models all relevant access stages explicitly", () => {
    expect(accessStage(null, true)).toBe("UNKNOWN");
    expect(accessStage(null, false)).toBe("UNAUTHENTICATED");
    expect(accessStage(admin, false)).toBe("AUTHENTICATED_STAFF");
    expect(accessStage(patientUser, false, limited)).toBe(
      "PASSWORD_AUTHENTICATED_MFA_SETUP_REQUIRED",
    );
    expect(
      accessStage(patientUser, false, {
        ...security,
        mfa_verified_for_current_session: false,
      }),
    ).toBe("MFA_CHALLENGE");
    expect(accessStage(patientUser, false, security)).toBe(
      "AUTHENTICATED_PATIENT",
    );
  });
});

it.each([401, 200])(
  "ignores a delayed pre-login bootstrap response with status %s",
  async (status) => {
    let complete: (value: Response) => void = () => {};
    let meCalls = 0;
    const fetch = vi.fn((path: string) => {
      if (path.endsWith("/auth/me")) {
        meCalls++;
        return meCalls === 1
          ? new Promise<Response>((resolve) => {
              complete = resolve;
            })
          : Promise.resolve(respond(patientUser));
      }
      return Promise.resolve(
        path.endsWith("/patient/security")
          ? respond(security)
          : path.endsWith("/patient/me")
            ? respond(profile)
            : path.endsWith("/auth/login")
              ? respond({})
              : respond(page([])),
      );
    });
    vi.stubGlobal("fetch", fetch);
    portal("/patient/login");
    await login();
    expect(
      await screen.findByRole("heading", { name: "Your patient portal" }),
    ).toBeInTheDocument();
    await act(async () => {
      complete(respond(status === 200 ? admin : {}, status));
    });
    expect(
      screen.getByRole("heading", { name: "Your patient portal" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Laboratory overview" }),
    ).not.toBeInTheDocument();
  },
);
