import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
const sourceRoot = resolve(import.meta.dirname, "..");
const files = readdirSync(sourceRoot, { recursive: true })
  .map(String)
  .filter((name) => /\.(tsx?|css)$/.test(name) && !name.startsWith("test/"));
const source = files
  .map((name) => readFileSync(resolve(sourceRoot, name), "utf8"))
  .join("\n");
describe("frontend security boundaries", () => {
  it("has no persistent auth/record storage or HTML injection sinks", () => {
    expect(source).not.toMatch(
      /\b(localStorage|sessionStorage|dangerouslySetInnerHTML)\b/,
    );
  });
  it("exposes only the public CSRF cookie name as browser configuration", () => {
    const names = [...source.matchAll(/import\.meta\.env\.([A-Z_]+)/g)].map(
      (m) => m[1],
    );
    expect(names).toEqual(["VITE_CSRF_COOKIE_NAME"]);
    expect(source).not.toMatch(
      /process\.env|BEGIN [A-Z ]*PRIVATE KEY|MFA_ENCRYPTION_KEY|DB_PASSWORD/,
    );
    const html = readFileSync(resolve(sourceRoot, "../index.html"), "utf8");
    expect(html).not.toMatch(/<script[^>]+src=["']https?:/);
  });
  it("does not expose a malformed success response body in error messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("private SQL stack contents")),
    );
    await expect(api("/patients")).rejects.toMatchObject({
      status: 502,
      message: "The server could not complete the request. Please try again.",
    });
  });
});
