import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { patientFetch, portal } from "./patient.helpers";
import { respond } from "./helpers";
describe("public verification", () => {
  it("accepts only a verification token without requiring authentication", async () => {
    const fetch = patientFetch(
      (p) =>
        p.startsWith("/api/v1/verify/")
          ? respond({ status: "NOT_FOUND", message: "" })
          : undefined,
      null,
    );
    portal("/verify");
    expect(screen.getByLabelText("Verification token")).toBeInTheDocument();
    expect(screen.queryByLabelText("Patient name")).not.toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText("Verification token"),
      "OPAQUE-TOKEN",
    );
    await userEvent.click(screen.getByRole("button", { name: "Check report" }));
    expect(
      await screen.findByRole("heading", {
        name: "Verification record not found.",
      }),
    ).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/verify/OPAQUE-TOKEN",
      expect.objectContaining({ method: "GET" }),
    );
  });
  it.each([
    ["VERIFIED", "Verified report"],
    ["REVOKED", "Report revoked / no longer current"],
    ["ALTERED", "Report integrity warning"],
    ["NOT_FOUND", "Verification record not found."],
  ])(
    "renders a textual %s state using only public fields",
    async (status, title) => {
      patientFetch(
        (p) =>
          p.startsWith("/api/v1/verify/")
            ? respond({
                status,
                issuing_facility: "Public Laboratory",
                report_date: "2026-09-20",
                version: 2,
                message: "PRIVATE-MESSAGE",
                patient_name: "PRIVATE-PATIENT",
                patient_code: "PRIVATE-CODE",
                result_value: "PRIVATE-RESULT",
                report_hash: "PRIVATE-HASH",
                pdf_path: "PRIVATE-PATH",
                report_id: 99,
              })
            : undefined,
        null,
      );
      portal("/verify/TOKEN");
      expect(
        await screen.findByRole("heading", { name: title }),
      ).toBeInTheDocument();
      expect(document.body).not.toHaveTextContent(/PRIVATE-/);
      if (status !== "NOT_FOUND") {
        expect(screen.getByText("Public Laboratory")).toBeInTheDocument();
        expect(screen.getByText("2026-09-20")).toBeInTheDocument();
      } else
        expect(screen.queryByText("Public Laboratory")).not.toBeInTheDocument();
      if (status === "ALTERED")
        expect(
          screen.getByText(
            "The stored report artifact does not match its integrity record.",
          ),
        ).toBeInTheDocument();
    },
  );
  it("remains public even if auth bootstrap is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          path.endsWith("/auth/me")
            ? respond({}, 503)
            : respond({ status: "VERIFIED", message: "" }),
        ),
      ),
    );
    portal("/verify/TOKEN");
    expect(
      await screen.findByRole("heading", { name: "Verified report" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sign in" }),
    ).not.toBeInTheDocument();
  });
  it("shows a neutral record-not-found state for a missing endpoint record", async () => {
    patientFetch(
      (p) =>
        p.startsWith("/api/v1/verify/")
          ? respond({ detail: "private" }, 404)
          : undefined,
      null,
    );
    portal("/verify/TOKEN");
    expect(
      await screen.findByRole("heading", {
        name: "Verification record not found.",
      }),
    ).toBeInTheDocument();
  });
  it.each(["resubmit", "retry button"])(
    "can retry a failed verification using %s",
    async (method) => {
      let attempts = 0;
      const fetch = patientFetch(
        (p) =>
          p.endsWith("/verify/RETRY-TOKEN")
            ? ++attempts === 1
              ? respond({ detail: "private" }, 503)
              : respond({ status: "VERIFIED", message: "" })
            : undefined,
        null,
      );
      portal("/verify/RETRY-TOKEN");
      await screen.findByRole("alert");
      if (method === "resubmit") {
        await userEvent.type(
          screen.getByLabelText("Verification token"),
          "RETRY-TOKEN",
        );
        await userEvent.click(
          screen.getByRole("button", { name: "Check report" }),
        );
      } else {
        await userEvent.click(
          screen.getByRole("button", { name: "Try again" }),
        );
      }
      expect(
        await screen.findByRole("heading", { name: "Verified report" }),
      ).toBeInTheDocument();
      expect(
        fetch.mock.calls.filter(([p]) => p.endsWith("/verify/RETRY-TOKEN")),
      ).toHaveLength(2);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
  it("never shows raw verification failures", async () => {
    patientFetch(
      (p) =>
        p.startsWith("/api/v1/verify/")
          ? respond({ detail: "SQL PRIVATE" }, 503)
          : undefined,
      null,
    );
    portal("/verify/TOKEN");
    expect(await screen.findByRole("alert")).not.toHaveTextContent("PRIVATE");
  });
});
