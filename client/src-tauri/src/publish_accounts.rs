//! Local platform profiles. WebView2 owns Cookie persistence; IPC never exports cookies.
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
    sync::Mutex,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Manager, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use uuid::Uuid;

#[derive(Clone, Serialize, Deserialize, Debug, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Platform {
    Douyin,
    WechatChannels,
    Xiaohongshu,
}

impl Platform {
    fn origin(&self) -> &'static str {
        match self {
            Self::Douyin => "https://creator.douyin.com",
            Self::WechatChannels => "https://channels.weixin.qq.com",
            Self::Xiaohongshu => "https://creator.xiaohongshu.com",
        }
    }
}

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct LocalAccount {
    id: String,
    platform: Platform,
    platform_user_id: String,
    username: String,
    verified_at: u64,
}

#[derive(Deserialize)]
struct Identity {
    platform_user_id: String,
    username: String,
}

struct Login {
    owner: String,
    id: String,
    platform: Platform,
    started: Instant,
    existing: Option<LocalAccount>,
}

#[derive(Default)]
pub struct PublishAccounts {
    logins: Mutex<HashMap<String, Login>>,
    disk: Mutex<()>,
}

fn validate_owner(owner: &str) -> Result<(), String> {
    if owner.is_empty()
        || owner.len() > 96
        || !owner
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err("无效的用户标识".into());
    }
    Ok(())
}

fn root(app: &AppHandle, owner: &str) -> Result<PathBuf, String> {
    validate_owner(owner)?;
    // Encode case as bytes: Windows paths are case-insensitive, user IDs are not.
    let owner_dir: String = owner.bytes().map(|byte| format!("{byte:02x}")).collect();
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("publish-accounts")
        .join(owner_dir))
}

fn account_path(root: &Path, id: &str) -> Result<PathBuf, String> {
    let id = Uuid::parse_str(id).map_err(|_| "无效的账号标识")?;
    Ok(root.join(format!("{id}.json")))
}

fn main_only(window: &WebviewWindow) -> Result<(), String> {
    let origin = window
        .url()
        .map_err(|e| e.to_string())?
        .origin()
        .ascii_serialization();
    let local = matches!(
        origin.as_str(),
        "http://tauri.localhost" | "https://tauri.localhost"
    ) || (cfg!(debug_assertions) && origin == "http://127.0.0.1:5173");
    if window.label() != "main" || !local {
        return Err("仅允许本机主窗口管理发布账号".into());
    }
    Ok(())
}

fn read_accounts(root: &Path) -> Result<Vec<LocalAccount>, String> {
    if !root.exists() {
        return Ok(vec![]);
    }
    let mut accounts = vec![];
    for entry in fs::read_dir(root).map_err(|e| e.to_string())? {
        let path = entry.map_err(|e| e.to_string())?.path();
        if path.extension().and_then(|v| v.to_str()) != Some("json") {
            continue;
        }
        let data = fs::read(&path).map_err(|e| e.to_string())?;
        let account: LocalAccount =
            serde_json::from_slice(&data).map_err(|_| "本机账号记录损坏，请联系支持")?;
        if account_path(root, &account.id)? != path {
            return Err("本机账号记录不匹配".into());
        }
        accounts.push(account);
    }
    accounts.sort_by(|a, b| b.verified_at.cmp(&a.verified_at).then(a.id.cmp(&b.id)));
    Ok(accounts)
}

fn official_window(
    app: &AppHandle,
    dir: &Path,
    id: &str,
    platform: &Platform,
    clearing: bool,
) -> Result<WebviewWindow, String> {
    if !cfg!(windows) {
        return Err("本地扫码账号管理需要 Windows 桌面客户端".into());
    }
    Uuid::parse_str(id).map_err(|_| "无效的账号标识")?;
    let label = format!("publish-{id}");
    if app.get_webview_window(&label).is_some() {
        return Err("该账号的官方窗口已打开，请先关闭后重试".into());
    }
    let profile = dir.join(id).join("browser");
    fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
    let url = if clearing {
        "about:blank"
    } else {
        platform.origin()
    };
    WebviewWindowBuilder::new(
        app,
        label,
        WebviewUrl::External(url.parse().map_err(|_| "平台地址错误")?),
    )
    .visible(!clearing)
    .title("官方平台 · 扫码登录 / 发布")
    .inner_size(1080.0, 780.0)
    .data_directory(profile)
    .initialization_script(include_str!("publish_identity.js"))
    .build()
    .map_err(|e| e.to_string())
}

fn clear_profile(window: &WebviewWindow) -> Result<(), String> {
    #[cfg(windows)]
    {
        use webview2_com::{
            ClearBrowsingDataCompletedHandler,
            Microsoft::Web::WebView2::Win32::{ICoreWebView2Profile2, ICoreWebView2_13},
        };
        use windows_core::Interface;
        let (send, receive) = std::sync::mpsc::channel();
        window
            .with_webview(move |webview| {
                let completed = send.clone();
                let result: windows_core::Result<()> = (|| unsafe {
                    webview
                        .controller()
                        .CoreWebView2()?
                        .cast::<ICoreWebView2_13>()?
                        .Profile()?
                        .cast::<ICoreWebView2Profile2>()?
                        .ClearBrowsingDataAll(&ClearBrowsingDataCompletedHandler::create(Box::new(
                            move |result| {
                                let _ = completed.send(result.map_err(|error| error.to_string()));
                                Ok(())
                            },
                        )))
                })();
                if let Err(error) = result {
                    let _ = send.send(Err(error.to_string()));
                }
            })
            .map_err(|error| error.to_string())?;
        // Commands using this function run off the UI thread; completion runs on it.
        receive
            .recv_timeout(Duration::from_secs(30))
            .map_err(|_| "清除本机登录状态超时，请重试")?
    }
    #[cfg(not(windows))]
    {
        let _ = window;
        Err("本机账号清理需要 Windows 桌面客户端".into())
    }
}

pub fn close_all_windows(app: &AppHandle) {
    for (label, window) in app.webview_windows() {
        if label.starts_with("publish-") {
            let _ = window.close();
        }
    }
}

#[tauri::command]
pub async fn list_local_publish_accounts(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, PublishAccounts>,
    owner: String,
) -> Result<Vec<LocalAccount>, String> {
    main_only(&window)?;
    let _lock = state.disk.lock().map_err(|_| "账号存储忙，请重试")?;
    read_accounts(&root(&app, &owner)?)
}

#[tauri::command]
pub async fn start_local_publish_login(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, PublishAccounts>,
    owner: String,
    platform: Platform,
    account_id: Option<String>,
) -> Result<String, String> {
    main_only(&window)?;
    let dir = root(&app, &owner)?;
    let mut logins = state.logins.lock().map_err(|_| "扫码会话忙，请重试")?;
    // Closed windows from an interrupted UI session do not block the next login.
    logins.retain(|_, login| {
        app.get_webview_window(&format!("publish-{}", login.id))
            .is_some()
    });
    if logins.values().any(|login| login.owner == owner) {
        return Err("请先完成或取消当前扫码".into());
    }
    let _lock = state.disk.lock().map_err(|_| "账号存储忙，请重试")?;
    let existing = match account_id {
        Some(id) => Some(
            read_accounts(&dir)?
                .into_iter()
                .find(|a| a.id == id && a.platform == platform)
                .ok_or("账号不存在")?,
        ),
        None => None,
    };
    let id = existing
        .as_ref()
        .map(|a| a.id.clone())
        .unwrap_or_else(|| Uuid::new_v4().to_string());
    official_window(&app, &dir, &id, &platform, false)?;
    logins.insert(
        id.clone(),
        Login {
            owner,
            id: id.clone(),
            platform,
            started: Instant::now(),
            existing,
        },
    );
    Ok(id)
}

#[tauri::command]
pub async fn check_local_publish_login(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, PublishAccounts>,
    owner: String,
    login_id: String,
) -> Result<Option<LocalAccount>, String> {
    main_only(&window)?;
    let dir = root(&app, &owner)?;
    let platform = {
        let logins = state.logins.lock().map_err(|_| "扫码会话忙，请重试")?;
        let login = logins
            .get(&login_id)
            .filter(|v| v.owner == owner)
            .ok_or("扫码会话不存在")?;
        if login.started.elapsed() > Duration::from_secs(300) {
            return Err("扫码已超时，请取消并重新扫码".into());
        }
        login.platform.clone()
    };
    let official = app
        .get_webview_window(&format!("publish-{login_id}"))
        .ok_or("官方窗口已关闭，请重新扫码")?;
    if official
        .url()
        .map_err(|e| e.to_string())?
        .origin()
        .ascii_serialization()
        != platform.origin()
    {
        return Ok(None);
    }
    let (send, receive) = std::sync::mpsc::channel();
    let script = format!(
        "location.origin === {} ? (window.__xiangshuPublishIdentity || null) : null",
        serde_json::to_string(platform.origin()).map_err(|e| e.to_string())?
    );
    official
        .eval_with_callback(script, move |value| {
            let _ = send.send(value);
        })
        .map_err(|e| e.to_string())?;
    let value =
        tauri::async_runtime::spawn_blocking(move || receive.recv_timeout(Duration::from_secs(5)))
            .await
            .map_err(|e| e.to_string())?
            .map_err(|_| "官方页面未响应，请稍后重试")?;
    let Some(identity) =
        serde_json::from_str::<Option<Identity>>(&value).map_err(|_| "平台账号信息解析失败")?
    else {
        return Ok(None);
    };
    if identity.username.trim().is_empty()
        || identity.platform_user_id.trim().is_empty()
        || identity.username.len() > 1024
        || identity.platform_user_id.len() > 1024
    {
        return Err("平台返回的账号信息不完整".into());
    }
    let mut logins = state.logins.lock().map_err(|_| "扫码会话忙，请重试")?;
    let login = logins
        .get(&login_id)
        .filter(|v| v.owner == owner)
        .ok_or("扫码会话已取消")?;
    if let Some(previous) = &login.existing {
        if previous.platform_user_id != identity.platform_user_id {
            official
                .navigate("about:blank".parse().map_err(|_| "页面地址错误")?)
                .map_err(|e| e.to_string())?;
            clear_profile(&official)?;
            official.close().map_err(|e| e.to_string())?;
            fs::remove_file(account_path(&dir, &login_id)?).map_err(|e| e.to_string())?;
            logins.remove(&login_id);
            return Err("扫码账号与原账号不同，已清除该登录状态；请取消并重新添加账号".into());
        }
    }
    let _lock = state.disk.lock().map_err(|_| "账号存储忙，请重试")?;
    if read_accounts(&dir)?.iter().any(|a| {
        a.platform == platform
            && a.platform_user_id == identity.platform_user_id
            && a.id != login_id
    }) {
        return Err("该平台账号已连接，请使用已有账号重新验证".into());
    }
    let account = LocalAccount {
        id: login_id.clone(),
        platform,
        platform_user_id: identity.platform_user_id,
        username: identity.username.trim().into(),
        verified_at: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_secs(),
    };
    let bytes = serde_json::to_vec(&account).map_err(|e| e.to_string())?;
    super::customer_credentials::write_file_atomically(&account_path(&dir, &login_id)?, &bytes)
        .map_err(|e| e.to_string())?;
    official.close().map_err(|e| e.to_string())?;
    logins.remove(&login_id);
    Ok(Some(account))
}

#[tauri::command]
pub async fn cancel_local_publish_login(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, PublishAccounts>,
    owner: String,
    login_id: String,
) -> Result<(), String> {
    main_only(&window)?;
    let dir = root(&app, &owner)?;
    let mut logins = state.logins.lock().map_err(|_| "扫码会话忙，请重试")?;
    if let Some(login) = logins.get(&login_id).filter(|v| v.owner == owner) {
        let opened = app.get_webview_window(&format!("publish-{}", login.id));
        if login.existing.is_none() {
            let official = match opened {
                Some(official) => {
                    official
                        .navigate("about:blank".parse().map_err(|_| "页面地址错误")?)
                        .map_err(|e| e.to_string())?;
                    official
                }
                None => official_window(&app, &dir, &login.id, &login.platform, true)?,
            };
            if let Err(error) = clear_profile(&official) {
                let _ = official.close();
                return Err(error);
            }
            official.close().map_err(|e| e.to_string())?;
            // A failed close after metadata persistence can leave a pending login.
            // Cancel must remove that partial record only after clearing succeeds.
            let _lock = state.disk.lock().map_err(|_| "账号存储忙，请重试")?;
            let metadata = account_path(&dir, &login.id)?;
            if metadata.exists() {
                fs::remove_file(metadata).map_err(|e| e.to_string())?;
            }
        } else if let Some(official) = opened {
            official.close().map_err(|e| e.to_string())?;
        }
        logins.remove(&login_id);
    }
    Ok(())
}

#[tauri::command]
pub async fn open_local_publish_account(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, PublishAccounts>,
    owner: String,
    account_id: String,
) -> Result<(), String> {
    main_only(&window)?;
    let dir = root(&app, &owner)?;
    let _lock = state.disk.lock().map_err(|_| "账号存储忙，请重试")?;
    let account = read_accounts(&dir)?
        .into_iter()
        .find(|a| a.id == account_id)
        .ok_or("账号不存在，请重新扫码")?;
    official_window(&app, &dir, &account.id, &account.platform, false)?;
    Ok(())
}

#[tauri::command]
pub async fn remove_local_publish_account(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, PublishAccounts>,
    owner: String,
    account_id: String,
) -> Result<(), String> {
    main_only(&window)?;
    let dir = root(&app, &owner)?;
    let logins = state.logins.lock().map_err(|_| "扫码会话忙，请重试")?;
    if logins.contains_key(&account_id) {
        return Err("请先取消该账号的扫码会话".into());
    }
    let _lock = state.disk.lock().map_err(|_| "账号存储忙，请重试")?;
    let account = read_accounts(&dir)?
        .into_iter()
        .find(|a| a.id == account_id)
        .ok_or("账号不存在")?;
    // Clear only this exact WebView2 profile; no cookies are read into Rust or JS.
    let official = official_window(&app, &dir, &account.id, &account.platform, true)?;
    if let Err(error) = clear_profile(&official) {
        let _ = official.close();
        return Err(error);
    }
    official.close().map_err(|e| e.to_string())?;
    fs::remove_file(account_path(&dir, &account.id)?).map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn owner_and_account_paths_cannot_escape_profile_root() {
        for invalid in [
            "",
            "..",
            "../alice",
            "alice/bob",
            "C:\\alice",
            " alice",
            "a.b",
        ] {
            assert!(validate_owner(invalid).is_err());
        }
        assert!(validate_owner("customer_1-a").is_ok());
        let base = Path::new("profiles");
        assert!(account_path(base, "../alice").is_err());
        let id = Uuid::new_v4().to_string();
        assert_eq!(
            account_path(base, &id).unwrap(),
            base.join(format!("{id}.json"))
        );
    }
    #[test]
    fn index_never_contains_credentials_and_is_isolated_per_owner() {
        let root = std::env::temp_dir().join(format!("publish-test-{}", Uuid::new_v4()));
        let a = root.join("alice");
        let b = root.join("bob");
        let account = LocalAccount {
            id: Uuid::new_v4().to_string(),
            platform: Platform::Douyin,
            platform_user_id: "synthetic-uid".into(),
            username: "测试昵称".into(),
            verified_at: 1,
        };
        let bytes = serde_json::to_vec(&account).unwrap();
        super::super::customer_credentials::write_file_atomically(
            &account_path(&a, &account.id).unwrap(),
            &bytes,
        )
        .unwrap();
        assert_eq!(read_accounts(&a).unwrap()[0].username, "测试昵称");
        assert!(read_accounts(&b).unwrap().is_empty());
        assert!(!String::from_utf8(bytes).unwrap().contains("cookie"));
        fs::remove_file(account_path(&a, &account.id).unwrap()).unwrap();
        fs::remove_dir(a).unwrap();
        fs::remove_dir(root).unwrap();
    }
}
