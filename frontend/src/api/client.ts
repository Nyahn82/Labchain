const messages: Record<number, string> = {
  401: "Your session has ended. Please sign in.",
  403: "You do not have permission to perform this action.",
  404: "This record could not be found.",
  409: "This action conflicts with the current record. Refresh and try again.",
  422: "Please check the form fields and try again.",
};
export class ApiError extends Error {
  constructor(
    public status: number,
    public fields: string[] = [],
  ) {
    super(
      messages[status] ||
        (status >= 500
          ? "The server could not complete the request. Please try again."
          : "Unable to connect. Check your connection and try again."),
    );
  }
}
export const csrfCookieName =
  import.meta.env.VITE_CSRF_COOKIE_NAME || "rhu_csrf";
export function csrfCookie() {
  const part = document.cookie
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(csrfCookieName + "="));
  try {
    return part
      ? decodeURIComponent(part.slice(csrfCookieName.length + 1))
      : "";
  } catch {
    return "";
  }
}
export interface Options {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  public?: boolean;
  blob?: boolean;
}
export async function api<T = unknown>(
  path: string,
  options: Options = {},
): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new Error("API paths must be relative.");
  const method = options.method || "GET";
  const headers: Record<string, string> = {
    Accept: options.blob ? "application/pdf" : "application/json",
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!options.public && !["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfCookie();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers,
      credentials: "include",
      cache: "no-store",
      signal: options.signal,
      body:
        options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(0);
  }
  if (options.signal?.aborted)
    throw new DOMException("Request cancelled", "AbortError");
  if (!response.ok) {
    let fields: string[] = [];
    if (response.status === 403 && !options.public) {
      try {
        const body = await response.clone().json();
        if (
          body.detail === "MFA_ENROLLMENT_REQUIRED" ||
          body.detail === "MFA_REQUIRED" ||
          body.detail === "MFA verification required."
        )
          window.dispatchEvent(
            new CustomEvent("patient-security-required", {
              detail:
                body.detail === "MFA verification required."
                  ? "MFA_REQUIRED"
                  : body.detail,
            }),
          );
      } catch {
        /* Only known policy codes are used; raw details are never displayed. */
      }
    }
    if (response.status === 422) {
      try {
        const data = await response.json();
        if (Array.isArray(data.detail))
          fields = data.detail
            .map((v: { loc?: unknown[] }) =>
              v.loc
                ?.filter((x) => typeof x === "string" && /^[a-z_]+$/.test(x))
                .slice(1)
                .join(" "),
            )
            .filter(Boolean);
      } catch {
        /* Generic validation message remains safe. */
      }
    }
    if (response.status === 401 && !options.public)
      window.dispatchEvent(new Event("session-expired"));
    const error = new ApiError(response.status, fields);
    if (response.status === 401 && options.public)
      error.message =
        "Sign-in failed. Check your credentials or verification code and try again.";
    throw error;
  }
  if (response.status === 204) return undefined as T;
  try {
    const data = await (options.blob ? response.blob() : response.json());
    if (options.signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    return data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(502);
  }
}
export async function pdf(
  path: string,
  filename: string,
  print = false,
  body?: unknown,
) {
  const blob = await api<Blob>(path, {
    blob: true,
    method: print ? "POST" : "GET",
    body,
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Delay cleanup until the browser has consumed the download navigation.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
