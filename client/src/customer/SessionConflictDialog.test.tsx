import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionConflictDialog } from "./SessionConflictDialog";

describe("SessionConflictDialog (FE-03 / T30)", () => {
  const baseMockConflict = {
    deviceNameMasked: "iPhone •••• AB12",
    leaseExpiresAt: new Date(Date.now() + 1800_000).toISOString(), // 30 分钟后过期
    slotNo: 2,
  };

  function renderWithProps({
    onCancel,
    onSwitch,
  }: {
    onCancel?: () => void;
    onSwitch?: () => void;
  }) {
    return render(
      <SessionConflictDialog
        conflict={baseMockConflict}
        onCancel={onCancel ?? vi.fn()}
        onSwitch={onSwitch ?? vi.fn()}
      />,
    );
  }

  it("displays masked device name without revealing plaintext identity", () => {
    renderWithProps({});
    expect(
      screen.getByText(/iPhone \u2022\u2022\u2022\u2022 AB12/i),
    ).toBeInTheDocument();
  });

  it("shows lease expiry time in human-readable format", async () => {
    renderWithProps({});
    await waitFor(() => {
      const text = screen.getByText(/lease expires at/i);
      expect(text).toBeInTheDocument();
    });
  });

  it("does not expose any plaintext secrets or full device fingerprint", () => {
    renderWithProps({});
    expect(screen.queryByLabelText("device-token")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("session-token")).not.toBeInTheDocument();
  });

  it("has cancel button that calls onCancel callback", () => {
    const mockOnCancel = vi.fn();
    renderWithProps({ onCancel: mockOnCancel });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(mockOnCancel).toHaveBeenCalledTimes(1);
  });

  it("has confirm switch button that calls onSwitch callback", () => {
    const mockOnSwitch = vi.fn();
    renderWithProps({ onSwitch: mockOnSwitch });
    fireEvent.click(
      screen.getByRole("button", { name: /switch to this device/i }),
    );
    expect(mockOnSwitch).toHaveBeenCalledTimes(1);
  });

  it("requires explicit user confirmation before switching (no silent takeover)", () => {
    const mockOnSwitch = vi.fn();
    const mockOnCancel = vi.fn();
    renderWithProps({ onCancel: mockOnCancel, onSwitch: mockOnSwitch });

    // Dialog exists but no automatic action occurs
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    // Verify callbacks were NOT called during render
    expect(mockOnSwitch).not.toHaveBeenCalled();
    expect(mockOnCancel).not.toHaveBeenCalled();

    // Only after clicking does state change happen
    fireEvent.click(
      screen.getByRole("button", { name: /switch to this device/i }),
    );
    expect(mockOnSwitch).toHaveBeenCalledTimes(1);
  });
});
