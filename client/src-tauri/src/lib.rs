mod customer_credentials;
mod video_downloads;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(video_downloads::VideoDownloads::default())
        .invoke_handler(tauri::generate_handler![
            customer_credentials::customer_device_instance_id,
            customer_credentials::customer_save_credentials,
            customer_credentials::customer_load_credentials,
            customer_credentials::customer_clear_session_token,
            customer_credentials::customer_clear_all_credentials,
            video_downloads::choose_video_download,
            video_downloads::start_video_download,
            video_downloads::cancel_video_download,
            video_downloads::get_video_download_status,
            video_downloads::open_video_download_folder,
        ])
        .setup(|_app| {
            let main = _app
                .config()
                .app
                .windows
                .iter()
                .find(|config| config.label == "main")
                .ok_or("main window configuration is missing")?;
            tauri::WebviewWindowBuilder::from_config(_app, main)?
                .on_download(video_downloads::on_download)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build desktop application")
        .run(|_app_handle, _event| {});
}
