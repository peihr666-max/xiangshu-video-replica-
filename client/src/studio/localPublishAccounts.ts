import { invoke, isTauri } from "@tauri-apps/api/core";
import type { PublishPlatform } from "./PlatformLogo";

export type LocalPublishAccount = {
  id: string;
  platform: PublishPlatform;
  platform_user_id: string;
  username: string;
  verified_at: number;
};
export const canUseLocalPublishAccounts = () => isTauri();
async function command<T>(
  name: string,
  args: Record<string, unknown>,
): Promise<T> {
  if (!isTauri())
    throw new Error(
      "请使用 Windows 桌面客户端扫码连接账号，本机登录状态不会同步到网页。",
    );
  try {
    return await invoke<T>(name, args);
  } catch (error) {
    throw error instanceof Error ? error : new Error(String(error));
  }
}
export const listLocalPublishAccounts = (owner: string) =>
  command<LocalPublishAccount[]>("list_local_publish_accounts", { owner });
export const startLocalPublishLogin = (
  owner: string,
  platform: PublishPlatform,
  accountId?: string,
) =>
  command<string>("start_local_publish_login", {
    owner,
    platform,
    accountId: accountId ?? null,
  });
export const checkLocalPublishLogin = (owner: string, loginId: string) =>
  command<LocalPublishAccount | null>("check_local_publish_login", {
    owner,
    loginId,
  });
export const cancelLocalPublishLogin = (owner: string, loginId: string) =>
  command<void>("cancel_local_publish_login", { owner, loginId });
export const removeLocalPublishAccount = (owner: string, accountId: string) =>
  command<void>("remove_local_publish_account", { owner, accountId });
export const openLocalPublishAccount = (owner: string, accountId: string) =>
  command<void>("open_local_publish_account", { owner, accountId });
