# 桌面品牌图标生成记录（2026-09-17）

## 范围

- Worktree: `/Users/honor.pei/Documents/订单项目/.worktrees/BRAND-IDENTITY-20260917`
- 分支：`fix/brand-identity-20260917`
- 源 Logo：`client/public/studio/logo-mark.svg`
- 目标：透明背景；上方为现有金色 Logo；下方两排为“众墅之家”“AI 即创”。
- 未修改 Android/iOS 图标、产品标识、安装路径或 Tauri 配置。
- 未提交 Git commit。

## 生成方式

生成脚本：`/tmp/generate-brand-icon-20260917.py`

脚本使用系统已有 `/System/Library/Fonts/STHeiti Medium.ttc` 的 Heiti SC Medium 字形，通过系统 Python 现有 `fontTools 4.60.2` 转为 SVG path。成品 SVG 不包含 `<text>`，运行和打包不依赖系统字体。Logo 的四条 `d` 路径逐字复用前端源文件。

```bash
python3 /tmp/generate-brand-icon-20260917.py client/src-tauri/app-icon.svg
final_icon_dir=$(mktemp -d /tmp/brand-icon-render-v2-final-XXXXXX)
node /Users/honor.pei/Documents/订单项目/乡墅爆款短视频复刻/node_modules/@tauri-apps/cli/tauri.js icon client/src-tauri/app-icon.svg -o "$final_icon_dir"
for icon_file in 128x128.png 128x128@2x.png 32x32.png 64x64.png Square107x107Logo.png Square142x142Logo.png Square150x150Logo.png Square284x284Logo.png Square30x30Logo.png Square310x310Logo.png Square44x44Logo.png Square71x71Logo.png Square89x89Logo.png StoreLogo.png icon.icns icon.ico icon.png; do
  cp "$final_icon_dir/$icon_file" "client/src-tauri/icons/$icon_file"
done
```

最终 Tauri 生成目录：`/tmp/brand-icon-render-v2-final-IPg9cC`

仅将该目录下已跟踪的顶层桌面资源复制回 `client/src-tauri/icons/`：15 个 PNG，以及 `icon.ico`、`icon.icns`。没有复制生成的 `android/` 与 `ios/` 子目录。

## 第二轮可读性调整

- 调整前视觉结论：`/tmp/brand-icon-review-v1.json`。
- “众墅之家”字号由 76 增至 100，基线为 350，成品宽度约 400 像素。
- “AI 即创”字号由 70 增至 112，基线最终为 467；首次使用 475 时，30×30 下采样图底部触边，因此上移 8 像素保留透明安全区。
- 两行文字增加 `#17150c` 细轮廓，采用 `paint-order="stroke fill"`；轮廓宽度换算到 512 图约为 2.4–2.7 像素。
- 保持透明背景，没有增加方底。
- 浅色背景复核图：`/tmp/brand-icon-light-background-v2-final.png`。

## 验证

- `client/src-tauri/app-icon.svg` 前四条路径与 `client/public/studio/logo-mark.svg` 完全相等。
- SVG 不含 `<text>`，所有名称均为内嵌矢量轮廓。
- 15 个 PNG 尺寸逐一与文件名/平台规格一致，外围均保留透明像素，没有裁切。512 图 alpha 边界为 `(59, 16, 452, 481)`。
- ICO 尺寸：16、24、32、48、64、256。
- ICNS 尺寸：16、32、128、256、512，含 1x/2x 表示。
- `git diff --check` 通过。
- 变更 SVG 常见密钥模式扫描无命中。
- 已用 `view_image` 检查透明背景的 512、128、64 像素成品；文字明显增大，居中关系正确。
- 已将 128、64 像素成品叠到 `#f4f2e9` 与白色背景复查，深色细轮廓能分离金色字形和浅色桌面背景。
- `git status` 确认 Android/iOS 目录、`tauri.conf.json` 与 `client/package.json` 无本任务变更。

关键文件 SHA-256：

```text
b6109d6297680cb399889c1a844aaa9fea5c6cd3aa6061e5d9b51d9471c70be2  client/src-tauri/app-icon.svg
6f26eb0186a9555b3f82bd95b2fab50cfe704f937cedbd5dd830aaa57e7c45fa  client/src-tauri/icons/32x32.png
a30cd10af055d5d31488ff75e7f753008a0da2d422a9559a9a9103034c86f26d  client/src-tauri/icons/64x64.png
b24b3f3db3004fa19890f9a89430fc95d348d5234e38a4b410af9a4c3d5b2c5d  client/src-tauri/icons/128x128.png
ae2ae00d35f992ac5ab4885000173fe348d97424d860eaf45094ed6d1f54e3e1  client/src-tauri/icons/128x128@2x.png
2f05b1330cdb3ab0f629c5b724b804683d46fad4bbd6e47add815790d8f85529  client/src-tauri/icons/icon.png
458a49ed1081c1afde683a85964d32d7828886e6d3cacd1fa7a357b3e0fa6978  client/src-tauri/icons/icon.ico
46588bfcfa11cbbf3ceb18cbc0fd1fefe54929569b1664f348ecb1f2c4cc1cb2  client/src-tauri/icons/icon.icns
```
