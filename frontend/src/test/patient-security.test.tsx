import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { RecoveryCodes } from "../pages/patient/Security";
import { renderAuth, respond } from "./helpers";
import {
  patientFetch,
  portal,
  limited,
  security,
  enrollment,
  codes,
  blobs,
} from "./patient.helpers";
async function startSetup() {
  await userEvent.click(
    await screen.findByRole("button", { name: "Start authenticator setup" }),
  );
  await screen.findByLabelText("Manual setup key");
}
async function confirmSetup() {
  await userEvent.type(screen.getByLabelText("Authenticator code"), "123456");
  await userEvent.click(
    screen.getByRole("button", { name: "Confirm authenticator" }),
  );
  await screen.findByRole("heading", { name: "Save your recovery codes" });
}
async function proof(submit: string) {
  await userEvent.type(
    screen.getByLabelText("Current password"),
    "test-password",
  );
  await userEvent.type(screen.getByLabelText("Authenticator code"), "123456");
  await userEvent.click(screen.getByRole("button", { name: submit }));
}
describe("authenticator enrollment", () => {
  it("enrolls only after user action, renders local QR and manual key", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/security")
        ? respond(limited)
        : p.endsWith("/enroll")
          ? respond(enrollment)
          : undefined,
    );
    const storage = vi.spyOn(Storage.prototype, "setItem");
    portal("/patient/setup-mfa");
    await screen.findByRole("button", { name: "Start authenticator setup" });
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/enroll"))).toBe(false);
    await startSetup();
    expect(screen.getByLabelText("Manual setup key")).toHaveValue(
      enrollment.secret,
    );
    expect(
      screen
        .getByRole("img", { name: "Authenticator setup QR code" })
        .tagName.toLowerCase(),
    ).toBe("svg");
    expect(document.querySelector(".enrollment-qr img")).toBeNull();
    expect(fetch.mock.calls.every(([p]) => p.startsWith("/api/v1/"))).toBe(
      true,
    );
    expect(storage).not.toHaveBeenCalled();
  });
  it("confirms TOTP, discards the setup key, and shows recovery codes once", async () => {
    let enabled = false;
    const fetch = patientFetch((p) =>
      p.endsWith("/security")
        ? respond(enabled ? security : limited)
        : p.endsWith("/enroll")
          ? respond(enrollment)
          : p.endsWith("/confirm")
            ? ((enabled = true),
              respond({ enabled: true, recovery_codes: codes }))
            : undefined,
    );
    const storage = vi.spyOn(Storage.prototype, "setItem");
    portal("/patient/setup-mfa");
    await startSetup();
    await confirmSetup();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/patient/mfa/totp/confirm",
      expect.objectContaining({ body: '{"code":"123456"}' }),
    );
    expect(
      screen.queryByDisplayValue(enrollment.secret),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "Authenticator setup QR code" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(codes[0])).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "I have saved my recovery codes securely.",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(
      await screen.findByRole("heading", { name: "Your patient portal" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(codes[0])).not.toBeInTheDocument();
    expect(storage).not.toHaveBeenCalled();
  });
  it("drops an enrollment secret when the page is left", async () => {
    patientFetch((p) =>
      p.endsWith("/security")
        ? respond(limited)
        : p.endsWith("/enroll")
          ? respond(enrollment)
          : undefined,
    );
    portal("/patient/setup-mfa");
    await startSetup();
    await userEvent.click(
      screen.getByRole("link", { name: "Verify a report" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Verify a laboratory report",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByDisplayValue(enrollment.secret),
    ).not.toBeInTheDocument();
  });
  it("clears confirmation codes immediately while the request is pending", async () => {
    let finish: (r: Response) => void = () => {};
    patientFetch((p) =>
      p.endsWith("/security")
        ? respond(limited)
        : p.endsWith("/enroll")
          ? respond(enrollment)
          : p.endsWith("/confirm")
            ? new Promise<Response>((resolve) => {
                finish = resolve;
              })
            : undefined,
    );
    portal("/patient/setup-mfa");
    await startSetup();
    await userEvent.type(screen.getByLabelText("Authenticator code"), "123456");
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm authenticator" }),
    );
    expect(screen.getByLabelText("Authenticator code")).toHaveValue("");
    expect(screen.getByLabelText("Authenticator code")).toBeDisabled();
    finish(respond({ detail: "private" }, 400));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not verify",
    );
  });
  it("shows safe enrollment errors without exposing response secrets", async () => {
    patientFetch((p) =>
      p.endsWith("/security")
        ? respond(limited)
        : p.endsWith("/enroll")
          ? respond({ detail: "encrypted-secret" }, 503)
          : undefined,
    );
    portal("/patient/setup-mfa");
    await userEvent.click(
      await screen.findByRole("button", { name: "Start authenticator setup" }),
    );
    expect(await screen.findByRole("alert")).not.toHaveTextContent(
      "encrypted-secret",
    );
  });
});
describe("one-time recovery-code handling", () => {
  it("copies codes only through an explicit local action", async () => {
    patientFetch();
    const user = userEvent.setup();
    const copy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderAuth(<RecoveryCodes codes={codes} onDone={async () => {}} />);
    expect(copy).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Copy codes" }));
    expect(copy).toHaveBeenCalledWith(codes.join("\n"));
    expect(
      screen.getByRole("list", { name: "One-time recovery codes" }),
    ).toHaveTextContent(codes[0]);
  });
  it("downloads a local text Blob and revokes it on unmount", async () => {
    patientFetch();
    const { create, revoke, click } = blobs();
    const view = renderAuth(
      <RecoveryCodes codes={codes} onDone={async () => {}} />,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Download codes" }),
    );
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledOnce();
    view.unmount();
    expect(revoke).toHaveBeenCalledWith("blob:test-private");
  });
  it("replaces displayed codes without retaining the previous set", () => {
    patientFetch();
    const view = renderAuth(
      <RecoveryCodes codes={codes} onDone={async () => {}} />,
    );
    view.rerender(
      <RecoveryCodes codes={["NEW-CODE-ONLY"]} onDone={async () => {}} />,
    );
    expect(screen.queryByText(codes[0])).not.toBeInTheDocument();
    expect(screen.getByText("NEW-CODE-ONLY")).toBeInTheDocument();
  });
});
describe("patient security settings", () => {
  it("shows security status and safe recovery-code count", async () => {
    patientFetch();
    portal("/patient/security");
    expect(
      await screen.findByRole("heading", { name: "Account security" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Unused recovery codes").nextSibling,
    ).toHaveTextContent("8");
    expect(
      screen.getByText("Authenticator enabled").nextSibling,
    ).toHaveTextContent("Yes");
    expect(
      screen.queryByDisplayValue(enrollment.secret),
    ).not.toBeInTheDocument();
  });
  it("warns before regeneration and submits password plus fresh TOTP", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/regenerate")
        ? respond({ recovery_codes: codes })
        : undefined,
    );
    const storage = vi.spyOn(Storage.prototype, "setItem");
    portal("/patient/security");
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Generate new recovery codes",
      }),
    );
    expect(
      screen.getByText(/Old unused recovery codes will stop working/),
    ).toBeInTheDocument();
    await proof("Replace recovery codes");
    expect(await screen.findByText(codes[0])).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/patient/mfa/recovery-codes/regenerate",
      expect.objectContaining({
        body: '{"password":"test-password","totp_code":"123456"}',
      }),
    );
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
    expect(storage).not.toHaveBeenCalled();
  });
  it.each([false, true])(
    "requires disable confirmation and proof recovery=%s",
    async (recovery) => {
      const fetch = patientFetch((p) =>
        p.endsWith("/disable") ? respond({ status: "ok" }) : undefined,
      );
      portal("/patient/security");
      await userEvent.click(
        await screen.findByRole("button", { name: "Disable authenticator" }),
      );
      const dialog = screen.getByRole("dialog", {
        name: "Disable authenticator",
      });
      expect(within(dialog).getByText(/sessions will end/)).toBeInTheDocument();
      expect(
        screen.queryByLabelText("Current password"),
      ).not.toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("checkbox", {
          name: "I understand and want to disable my authenticator.",
        }),
      );
      if (recovery)
        await userEvent.click(
          screen.getByRole("button", { name: "Use recovery code" }),
        );
      await userEvent.type(
        screen.getByLabelText("Current password"),
        "test-password",
      );
      await userEvent.type(
        screen.getByLabelText(
          recovery ? "Recovery code" : "Authenticator code",
        ),
        recovery ? "TEST-RECOVERY" : "123456",
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Confirm disable authenticator" }),
      );
      expect(
        await screen.findByRole("button", { name: "Sign in" }),
      ).toBeInTheDocument();
      expect(fetch).toHaveBeenCalledWith(
        "/api/v1/patient/mfa/disable",
        expect.objectContaining({
          body: JSON.stringify({
            password: "test-password",
            ...(recovery
              ? { recovery_code: "TEST-RECOVERY" }
              : { totp_code: "123456" }),
          }),
        }),
      );
      expect(
        screen.queryByRole("navigation", { name: "Patient navigation" }),
      ).not.toBeInTheDocument();
    },
  );
  it("locks the proof method and dialog while disabling is pending", async () => {
    let finish: (r: Response) => void = () => {};
    const fetch = patientFetch((p) =>
      p.endsWith("/disable")
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : undefined,
    );
    portal("/patient/security");
    await userEvent.click(
      await screen.findByRole("button", { name: "Disable authenticator" }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "I understand and want to disable my authenticator.",
      }),
    );
    await proof("Confirm disable authenticator");
    const switchProof = screen.getByRole("button", {
      name: "Use recovery code",
    });
    expect(switchProof).toBeDisabled();
    await userEvent.click(switchProof);
    expect(screen.queryByLabelText("Recovery code")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      fetch.mock.calls.filter(([p]) => p.endsWith("/disable")),
    ).toHaveLength(1);
    finish(respond({ detail: "private" }, 400));
    await screen.findByRole("alert");
    expect(switchProof).toBeEnabled();
    await userEvent.click(switchProof);
    expect(screen.getByLabelText("Recovery code")).toHaveValue("");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });
  it("requires matching new passwords", async () => {
    const fetch = patientFetch();
    portal("/patient/security");
    await userEvent.click(
      await screen.findByRole("button", { name: "Change password" }),
    );
    for (const [label, value] of [
      ["Current password", "current-test"],
      ["New password", "new-long-password"],
      ["Confirm new password", "different-password"],
    ])
      await userEvent.type(screen.getByLabelText(label), value);
    await userEvent.click(
      screen.getByRole("button", { name: "Update password" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "New passwords must match",
    );
    expect(fetch.mock.calls.some(([p]) => p.endsWith("/change-password"))).toBe(
      false,
    );
  });
  it("changes password, clears auth state, and returns to login", async () => {
    const fetch = patientFetch((p) =>
      p.endsWith("/change-password") ? respond({ status: "ok" }) : undefined,
    );
    portal("/patient/security");
    await userEvent.click(
      await screen.findByRole("button", { name: "Change password" }),
    );
    for (const [label, value] of [
      ["Current password", "current-test"],
      ["New password", "new-long-password"],
      ["Confirm new password", "new-long-password"],
    ])
      await userEvent.type(screen.getByLabelText(label), value);
    await userEvent.click(
      screen.getByRole("button", { name: "Update password" }),
    );
    expect(
      await screen.findByRole("button", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Password updated. Please sign in again."),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/auth/change-password",
      expect.objectContaining({
        body: '{"current_password":"current-test","new_password":"new-long-password"}',
      }),
    );
  });
});
