import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DevicePairingPage } from "./DevicePairingPage";

// Extend window object for global fetch mock in tests
declare const window: Window & {
  fetch: typeof globalThis.fetch;
};

describe("DevicePairingPage (FE-03 / T30)", () => {
  const mockOnSuccess = vi.fn();
  const mockOnError = vi.fn();
  const mockOnCancel = vi.fn();

  function renderWithProps(props?: {
    onSuccess?: () => void;
    onError?: () => void;
    onCancel?: () => void;
  }) {
    render(
      <DevicePairingPage
        onSuccess={props?.onSuccess ?? mockOnSuccess}
        onError={props?.onError ?? mockOnError}
        onCancel={props?.onCancel ?? mockOnCancel}
      />,
    );
  }

  it("displays device fingerprint input field with label", () => {
    renderWithProps();
    expect(screen.getByLabelText(/device fingerprint/i)).toBeInTheDocument();
  });

  it("displays device name input field with label", () => {
    renderWithProps();
    expect(screen.getByLabelText(/device name/i)).toBeInTheDocument();
  });

  it("validates required fields are not empty", () => {
    renderWithProps();

    // Try to submit without filling fields
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    // Both fields should be marked as required/error
    expect(screen.getByLabelText(/device fingerprint/i)).toHaveAttribute(
      "required",
    );
    expect(screen.getByLabelText(/device name/i)).toHaveAttribute("required");
  });

  it("shows loading state when processing enrollment", async () => {
    const mockAsyncOnSuccess = vi.fn();
    renderWithProps({ onSuccess: mockAsyncOnSuccess });

    // Fill in the form
    fireEvent.change(screen.getByLabelText(/device fingerprint/i), {
      target: { value: "Test Device •••• AB12" },
    });
    fireEvent.change(screen.getByLabelText(/device name/i), {
      target: { value: "My Test Device" },
    });

    // Click enroll before API call completes
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    // Should show busy/loading state
    await waitFor(() => {
      const button = screen.getByRole("button", { name: /enrolling device/i });
      expect(button).toBeInTheDocument();
    });
  });

  it("calls onSuccess callback when enrollment completes successfully", async () => {
    const mockSuccess = vi.fn();
    const originalFetch = window.fetch;

    try {
      // Mock fetch to return success response
      window.fetch = vi.fn().mockResolvedValueOnce({
        ok: true,
        status: 202,
        json: vi.fn().mockResolvedValueOnce({
          pairing_request_id: "test-id",
          status: "pending",
          expires_at: new Date(Date.now() + 3600_000).toISOString(),
        }),
      });

      renderWithProps({ onSuccess: mockSuccess });

      // Fill in the form
      fireEvent.change(screen.getByLabelText(/device fingerprint/i), {
        target: { value: "Test Device •••• AB12" },
      });
      fireEvent.change(screen.getByLabelText(/device name/i), {
        target: { value: "My Test Device" },
      });

      // Submit
      fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

      // Wait for async operation
      await waitFor(
        () => {
          expect(mockSuccess).toHaveBeenCalled();
        },
        { timeout: 1000 },
      );
    } finally {
      window.fetch = originalFetch;
    }
  });

  it("calls onError callback when enrollment fails", async () => {
    const mockError = vi.fn();
    const originalFetch = window.fetch;

    try {
      // Mock fetch to return error response
      window.fetch = vi.fn().mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: vi
          .fn()
          .mockResolvedValueOnce({ message: "Invalid activation code" }),
      });

      renderWithProps({ onError: mockError });

      // Fill in the form
      fireEvent.change(screen.getByLabelText(/device fingerprint/i), {
        target: { value: "Test Device •••• AB12" },
      });
      fireEvent.change(screen.getByLabelText(/device name/i), {
        target: { value: "My Test Device" },
      });

      // Submit
      fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

      // Wait for async operation and error handling
      await waitFor(
        () => {
          expect(mockError).toHaveBeenCalled();
        },
        { timeout: 1000 },
      );
    } finally {
      window.fetch = originalFetch;
    }
  });

  it("has cancel button that calls onCancel callback", () => {
    renderWithProps();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(mockOnCancel).toHaveBeenCalledTimes(1);
  });

  it("does not expose any plaintext secrets or tokens in UI", () => {
    renderWithProps();

    // No sensitive fields should be visible
    expect(
      screen.queryByLabelText(/activation-code-secret/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/pairing-token/i)).not.toBeInTheDocument();
  });
});
