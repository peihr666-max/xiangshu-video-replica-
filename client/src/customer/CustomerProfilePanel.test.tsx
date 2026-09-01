import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CustomerDeviceListResponse, CustomerProfile } from "../api";
import { CustomerProfilePanel } from "./CustomerProfilePanel";
import type { CustomerCredentialStore } from "./useCustomerSession";

const profile: CustomerProfile = {
  user_id: "user-1",
  username: "customer-1",
  display_name: "李丽",
  joined_at: "2026-08-01T00:00:00Z",
  activation_code_masked: "XS04-ABCD••••WXYZ",
  activation_status: "ACTIVE",
  activated_at: "2026-08-02T00:00:00Z",
  device_slots_used: 1,
  device_slots_total: 2,
};

const devices: CustomerDeviceListResponse = {
  slots: [
    {
      slot_no: 1,
      device: {
        id: "device-1",
        slot_no: 1,
        display_name: "工作电脑 •••• AB12",
        platform: "windows",
        status: "BOUND",
        bound_at: "2026-08-02T00:00:00Z",
        last_active_at: "2026-08-27T00:00:00Z",
        unbound_at: null,
        revoked_at: null,
        is_current: true,
      },
    },
    { slot_no: 2, device: null },
  ],
  history: [],
  pending_pairings: [],
};

const store: CustomerCredentialStore = {
  loadDeviceCredentialToken: vi.fn().mockResolvedValue(null),
  loadSessionToken: vi.fn().mockResolvedValue(null),
  saveActivation: vi.fn().mockResolvedValue(undefined),
  saveSessionToken: vi.fn().mockResolvedValue(undefined),
  clearSessionToken: vi.fn().mockResolvedValue(undefined),
  clearAllCredentials: vi.fn().mockResolvedValue(undefined),
  deviceInstanceId: vi.fn().mockResolvedValue("test-instance-id"),
  devicePlatform: () => "windows",
};

describe("CustomerProfilePanel", () => {
  const defaultProps = {
    deviceError: "",
    devices,
    onApprovePairing: vi.fn(),
    onDismissPairing: vi.fn(),
    onProfileUpdated: vi.fn(),
    onRecharge: vi.fn(),
    onRefreshDevices: vi.fn().mockResolvedValue(undefined),
    onResetActivationCode: vi.fn(),
    onSessionExpired: vi.fn(),
    onUnbind: vi.fn(),
    onUpdateProfile: vi.fn(),
    profile,
    store,
    walletRefreshKey: 0,
  };

  it("groups account, activation and device details in the personal centre", () => {
    render(<CustomerProfilePanel {...defaultProps} />);

    expect(screen.getByRole("heading", { name: "李丽" })).toBeInTheDocument();
    expect(screen.getByText("XS04-ABCD••••WXYZ")).toBeInTheDocument();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "设备管理" }));
    expect(defaultProps.onRefreshDevices).toHaveBeenCalled();
    expect(screen.getByText("工作电脑 •••• AB12")).toBeInTheDocument();
    expect(screen.getByText(/还没有绑定设备/)).toBeInTheDocument();
  });

  it("edits the display name while keeping the account number read-only", async () => {
    const onUpdateProfile = vi.fn().mockResolvedValue({
      ...profile,
      display_name: "丽丽工作室",
    });
    const onProfileUpdated = vi.fn();
    render(
      <CustomerProfilePanel
        {...defaultProps}
        onProfileUpdated={onProfileUpdated}
        onUpdateProfile={onUpdateProfile}
      />,
    );

    expect(screen.getByText("customer-1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "丽丽工作室" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存个人资料" }));

    await waitFor(() =>
      expect(onUpdateProfile).toHaveBeenCalledWith("丽丽工作室"),
    );
    expect(onProfileUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ display_name: "丽丽工作室" }),
    );
  });

  it("shows the replacement activation code once after a confirmed reset", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onResetActivationCode = vi.fn().mockResolvedValue({
      activation_code: "XS04-NEWCODE-NEWCODE-NEWCODE-NEWCODE",
      masked_code: "XS04-NEWC***-*******-*******-***CODE",
    });
    render(
      <CustomerProfilePanel
        {...defaultProps}
        onResetActivationCode={onResetActivationCode}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "重置激活码" }));

    expect(
      await screen.findByText("XS04-NEWCODE-NEWCODE-NEWCODE-NEWCODE"),
    ).toBeInTheDocument();
    expect(screen.getByText(/新激活码仅显示这一次/)).toBeInTheDocument();
  });
});
