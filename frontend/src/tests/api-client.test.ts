import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "@/api/client";

describe("api client errors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("preserves backend error code and body request id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: "STATE_CONFLICT", message: "Nope", request_id: "body-id" },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(api.listProjects()).rejects.toMatchObject({
      status: 409,
      code: "STATE_CONFLICT",
      requestId: "body-id",
      message: "Nope (request id: body-id)",
    } satisfies Partial<ApiError>);
  });

  it("falls back to X-Request-ID header", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "HTTP_ERROR", message: "Failed" } }), {
          status: 500,
          headers: { "Content-Type": "application/json", "X-Request-ID": "header-id" },
        }),
      ),
    );

    await expect(api.listProjects()).rejects.toMatchObject({
      status: 500,
      code: "HTTP_ERROR",
      requestId: "header-id",
      message: "Failed (request id: header-id)",
    } satisfies Partial<ApiError>);
  });
});
