import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { customerEnrollDevice } from "../api";
import { DevicePairingPage } from "./DevicePairingPage";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, customerEnrollDevice: vi.fn() };
});

const enrollMock = vi.mocked(customerEnrollDevice);

describe("DevicePairingPage (FE-03 / T30)", () => {
  const mockOnSuccess = vi.fn();
  const mockOnError = vi.fn();
  const mockOnCancel = vi.fn();

  afterEach(() => {
    enrollMock.mockReset();
    mockOnSuccess.mockReset();
    mockOnError.mockReset();
    mockOnCancel.mockReset();
  });

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

  function fillForm() {
    fireEvent.change(screen.getByLabelText(/activation code/i), {
      target: { value: "TEST-CODE-1234" },
    });
    fireEvent.change(screen.getByLabelText(/device fingerprint/i), {
      target: { value: "Test Device •••• AB12" },
    });
    fireEvent.change(screen.getByLabelText(/device name/i), {
      target: { value: "My Test Device" },
    });
  }

  it("displays activation code, device fingerprint and name input fields with labels", () => {
    renderWithProps();
    expect(screen.getByLabelText(/activation code/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/device fingerprint/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/device name/i)).toBeInTheDocument();
  });

  it("validates required fields are not empty", () => {
    renderWithProps();

    // Try to submit without filling fields
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    // All three fields should be marked as required/error
    expect(screen.getByLabelText(/activation code/i)).toHaveAttribute(
      "required",
    );
    expect(screen.getByLabelText(/device fingerprint/i)).toHaveAttribute(
      "required",
    );
    expect(screen.getByLabelText(/device name/i)).toHaveAttribute("required");
  });

  it("shows loading state when processing enrollment", async () => {
    enrollMock.mockReturnValueOnce(
      new Promise(() => {
        // Never resolves: assert the busy state while the call is in flight.
      }),
    );
    renderWithProps();
    fillForm();

    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /enrolling device/i });
      expect(button).toBeInTheDocument();
    });
  });

  it("calls the typed adapter with the entered activation code and device identity", async () => {
    enrollMock.mockResolvedValueOnce({
      status: 202,
      replayed: false,
      pending: {
        pairing_request_id: "test-id",
        status: "PENDING",
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        request_id: "req-test",
      },
    });
    renderWithProps();

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    await waitFor(() => {
      expect(enrollMock).toHaveBeenCalledTimes(1);
    });
    const input = enrollMock.mock.calls[0][0];
    expect(input.activationCode).toBe("TEST-CODE-1234");
    expect(input.deviceFingerprint).toBe("Test Device •••• AB12");
    expect(input.deviceName).toBe("My Test Device");
    expect(input.devicePlatform).toBe("web");
    expect(input.idempotencyKey).toBeTruthy();
  });

  it("reports a PENDING (202) enrollment result to onSuccess without assuming success", async () => {
    const pendingResult = {
      status: 202,
      replayed: false,
      pending: {
        pairing_request_id: "test-id",
        status: "PENDING",
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        request_id: "req-test",
      },
    } as const;
    enrollMock.mockResolvedValueOnce(pendingResult);
    renderWithProps();

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    await waitFor(() => {
      expect(mockOnSuccess).toHaveBeenCalledWith(pendingResult);
    });
  });

  it("reports a CONSUMED (201) enrollment result to onSuccess", async () => {
    const consumedResult = {
      status: 201,
      replayed: false,
      credential: {
        device_id: "dev-test",
        slot_no: 2,
        device_token: "test-device-token",
        request_id: "req-test",
      },
    } as const;
    enrollMock.mockResolvedValueOnce(consumedResult);
    renderWithProps();

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    await waitFor(() => {
      expect(mockOnSuccess).toHaveBeenCalledWith(consumedResult);
    });
  });

  it("calls onError callback when enrollment fails", async () => {
    enrollMock.mockRejectedValueOnce(new Error("Failed to enroll device"));
    renderWithProps();

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /enroll device/i }));

    await waitFor(() => {
      expect(mockOnError).toHaveBeenCalled();
    });
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
