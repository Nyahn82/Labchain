import { describe, it, expect, vi } from "vitest";
import { api, ApiError, csrfCookie, pdf } from "../api/client";
import { respond } from "./helpers";
describe("same-origin API boundary", () => {
  it("includes cookies and does not cache authenticated data", async () => {
    const fetch = vi
      .fn()
      .mockImplementation(() => Promise.resolve(respond({})));
    vi.stubGlobal("fetch", fetch);
    await api("/patients");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/patients",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });
  it.each(["POST", "PUT", "PATCH", "DELETE"])(
    "adds CSRF on %s",
    async (method) => {
      document.cookie = "rhu_csrf=encoded%20token; path=/";
      const fetch = vi
        .fn()
        .mockImplementation(() => Promise.resolve(respond({})));
      vi.stubGlobal("fetch", fetch);
      await api("/patients", { method, body: { name: "Safe" } });
      expect(fetch.mock.calls[0][1].headers["X-CSRF-Token"]).toBe(
        "encoded token",
      );
    },
  );
  it("does not add CSRF to GET or public login", async () => {
    document.cookie = "rhu_csrf=token; path=/";
    const fetch = vi
      .fn()
      .mockImplementation(() => Promise.resolve(respond({})));
    vi.stubGlobal("fetch", fetch);
    await api("/patients");
    await api("/auth/login", { method: "POST", public: true });
    for (const call of fetch.mock.calls)
      expect(call[1].headers).not.toHaveProperty("X-CSRF-Token");
  });
  it.each([401, 403, 404, 409, 422, 500])(
    "standardizes %s without raw server details",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            respond({ detail: "SQL private stack password" }, status),
          ),
      );
      await expect(api("/patients")).rejects.toMatchObject({ status });
      await api("/patients").catch((e) =>
        expect(e.message).not.toMatch(/SQL|stack|password/),
      );
    },
  );
  it("extracts validation field names without input values", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          respond(
            {
              detail: [
                {
                  loc: ["body", "birth_date"],
                  input: "secret",
                  msg: "private",
                },
              ],
            },
            422,
          ),
        ),
    );
    await expect(api("/patients")).rejects.toMatchObject({
      fields: ["birth_date"],
    });
  });
  it("signals expired authenticated sessions", async () => {
    const listener = vi.fn();
    window.addEventListener("session-expired", listener);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({}, 401)));
    await api("/patients").catch(() => {});
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener("session-expired", listener);
  });
  it("does not signal expiration for an invalid public login", async () => {
    const listener = vi.fn();
    window.addEventListener("session-expired", listener);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({}, 401)));
    await api("/auth/login", { public: true }).catch(() => {});
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener("session-expired", listener);
  });
  it("handles network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private")));
    await expect(api("/patients")).rejects.toBeInstanceOf(ApiError);
  });
  it("handles malformed cookie encoding", () => {
    document.cookie = "rhu_csrf=%invalid; path=/";
    expect(csrfCookie()).toBe("");
  });
  it.each(["https://example.com", "//example.com"])(
    "rejects external API path %s",
    async (path) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      await expect(api(path)).rejects.toThrow("relative");
      expect(fetch).not.toHaveBeenCalled();
    },
  );
  it("downloads a PDF through authenticated API and revokes temporary URL", async () => {
    vi.useFakeTimers();
    const create = vi.fn().mockReturnValue("blob:test");
    const revoke = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }),
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const fetch = vi.fn().mockResolvedValue(new Response("PDF"));
    vi.stubGlobal("fetch", fetch);
    await pdf("/reports/1/pdf", "report.pdf");
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/reports/1/pdf");
    expect(create).toHaveBeenCalledOnce();
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledWith("blob:test");
    vi.useRealTimers();
  });
});
