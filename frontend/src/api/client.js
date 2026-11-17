// Single entry point for every HTTP call to the PyroScope Flask API.
//
// - In development the Vite proxy forwards "/api" to http://127.0.0.1:5000.
// - In production set VITE_API_BASE to the API origin (e.g. https://api...).
// - Errors are normalised into ApiError so the UI can render one error state.

const BASE_URL = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const DEFAULT_TIMEOUT_MS = 30000;

export class ApiError extends Error {
  constructor(message, { status = 0, code = "unknown", details = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isNetworkError() {
    return this.status === 0;
  }

  get isAborted() {
    return this.code === "aborted";
  }
}

function buildUrl(path, params) {
  const origin =
    typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const url = new URL(`${BASE_URL}${path}`, origin);

  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    url.searchParams.set(key, String(value));
  });

  // Keep relative URLs when BASE_URL is empty so the Vite proxy applies.
  return BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
}

async function parseBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function request(
  path,
  { method = "GET", params, body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = {}
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const forwardAbort = () => controller.abort();
  signal?.addEventListener("abort", forwardAbort);

  try {
    const response = await fetch(buildUrl(path, params), {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });

    const payload = await parseBody(response);

    if (!response.ok) {
      const error = payload?.error ?? {};
      throw new ApiError(
        error.message ?? `Request failed with status ${response.status}.`,
        {
          status: response.status,
          code: error.code ?? "http_error",
          details: error.details ?? payload,
        }
      );
    }

    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error?.name === "AbortError") {
      throw new ApiError("The request was cancelled.", { code: "aborted" });
    }
    throw new ApiError(
      "Cannot reach the API. Start the backend with `python -m flask --app app run`.",
      { status: 0, code: "network_error", details: error?.message }
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

export const get = (path, options) => request(path, options);

export const post = (path, body, options) =>
  request(path, { ...options, method: "POST", body });

// POST that returns a binary download. Errors are parsed as JSON first so a
// failed export shows the API message instead of downloading a corrupt file.
// Exports can exceed the generic 30s timeout, so they get a longer default.
export async function postBlob(path, body, { timeoutMs = 180000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!response.ok) {
      const payload = await parseBody(response);
      const error = payload?.error ?? {};
      throw new ApiError(
        error.message ?? `Request failed with status ${response.status}.`,
        {
          status: response.status,
          code: error.code ?? "http_error",
          details: error.details ?? payload,
        }
      );
    }

    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
    return {
      blob: await response.blob(),
      fileName: match?.[1] ?? "export.zip",
      exportId: response.headers.get("X-Export-Id"),
    };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error?.name === "AbortError") {
      throw new ApiError("The export timed out.", { code: "aborted" });
    }
    throw new ApiError("Cannot reach the API to create the export.", {
      status: 0,
      code: "network_error",
      details: error?.message,
    });
  } finally {
    clearTimeout(timer);
  }
}
