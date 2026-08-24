import type { CustomerCredentialStore } from "./useCustomerSession";

/** 最小挂载用的浏览器凭据存储(§14 过渡实现)。
 *
 * 内存实现 —— 不落 localStorage/sessionStorage,红线(禁止明文 secret 进
 * Web Storage)之下安全,但重启后回到激活页。T29 桌面 Tauri 桥
 * (Keychain/DPAPI)合并后由桥接实现替换;浏览器客户入口最终走同源
 * HttpOnly cookie(§14)。
 */
export function createBrowserCustomerCredentialStore(): CustomerCredentialStore {
  let deviceToken: string | null = null;
  let sessionToken: string | null = null;
  // 设备实例标识不是 secret(服务端只存摘要),此处仍仅内存生成:
  // 桌面端由 T29 安全桥提供稳定实例(§14"生成并读取稳定的
  // device_instance_id")。
  const instanceId = crypto.randomUUID();

  return {
    async loadDeviceCredentialToken() {
      return deviceToken;
    },
    async loadSessionToken() {
      return sessionToken;
    },
    async saveActivation(nextDeviceToken, nextSessionToken) {
      deviceToken = nextDeviceToken;
      sessionToken = nextSessionToken;
    },
    async saveSessionToken(nextSessionToken) {
      sessionToken = nextSessionToken;
    },
    async clearSessionToken() {
      sessionToken = null;
    },
    async clearAllCredentials() {
      deviceToken = null;
      sessionToken = null;
    },
    async deviceInstanceId() {
      return instanceId;
    },
    devicePlatform() {
      return "web";
    },
  };
}
