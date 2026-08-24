import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { PairingApprovalCard } from "./PairingApprovalCard";

describe("PairingApprovalCard (FE-03 / T30)", () => {
  const mockPendingPairing = {
    id: "test-pairing-id",
    deviceFingerprint: "Android •••• XY78",
    slotNo: 2,
    createdAt: new Date(Date.now() - 3600_000).toISOString(), // 1 小时前创建
  };

  const mockOnApprove = vi.fn();
  const mockOnReject = vi.fn();

  function renderWithProps(props?: {
    onApprove?: () => void;
    onReject?: () => void;
  }) {
    render(
      <PairingApprovalCard
        pairing={mockPendingPairing}
        onApprove={props?.onApprove ?? mockOnApprove}
        onReject={props?.onReject ?? mockOnReject}
      />,
    );
  }

  it("displays masked device fingerprint without exposing plaintext identity", () => {
    renderWithProps();
    expect(screen.getByText(/Android \u2022\u2022\u2022\u2022 XY78/i)).toBeInTheDocument();
  });

  it("shows slot number clearly as Slot #2", () => {
    renderWithProps();
    expect(screen.getByText(/Slot #2/i)).toBeInTheDocument();
  });

  it("does not expose any plaintext secrets or tokens", () => {
    renderWithProps();
    expect(screen.queryByLabelText("device-token")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("session-token")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("pairing-secret")).not.toBeInTheDocument();
  });

  it("has approve button that calls onApprove callback with pairing ID", () => {
    renderWithProps();
    fireEvent.click(screen.getByRole("button", { name: /approve pairing/i }));
    expect(mockOnApprove).toHaveBeenCalledWith("test-pairing-id");
  });

  it("has reject button that calls onReject callback", () => {
    renderWithProps();
    fireEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(mockOnReject).toHaveBeenCalledTimes(1);
  });

  it("requires explicit confirmation before approving (no silent approval)", () => {
    const mockApprove = vi.fn();
    const mockReject = vi.fn();
    renderWithProps({ onApprove: mockApprove, onReject: mockReject });

    // Card exists but no automatic action occurs
    expect(screen.getByRole("article")).toBeInTheDocument();
    
    // Verify callbacks were NOT called during render
    expect(mockApprove).not.toHaveBeenCalled();
    expect(mockReject).not.toHaveBeenCalled();
    
    // Only after clicking approve does state change happen
    fireEvent.click(screen.getByRole("button", { name: /approve pairing/i }));
    expect(mockApprove).toHaveBeenCalledWith("test-pairing-id");
  });

  it("indicates pending status visually with appropriate messaging", () => {
    renderWithProps();
    expect(screen.getByText(/slot #2/i)).toBeInTheDocument();
    expect(screen.getByText(/waiting for your confirmation/i)).toBeInTheDocument();
  });
});
