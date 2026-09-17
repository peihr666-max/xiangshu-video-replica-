# 桌面打包图标黑底修正验证（2026-09-17）

## 变更边界

- 源文件：`client/src-tauri/app-icon.svg`
- 唯一矢量改动：在原有 Logo 与两行文字之前增加覆盖 512×512 画布的 `#000` 背景矩形。
- 原有 Logo、文字 path、渐变、坐标和缩放参数均未修改；`git diff` 中 SVG 仅新增一行 `<rect width="512" height="512" fill="#000" />`。
- 使用仓库现有 `@tauri-apps/cli` 从 SVG 重新生成桌面端顶层图标；没有复制或修改 Android、iOS 图标。

## 图 3 同版确认

- 用户提供的图 3：128×128，alpha 可见边界 `(15, 4, 114, 121)`。
- 变更前仓库 `128x128.png`：128×128，alpha 可见边界 `(15, 4, 114, 121)`。
- 两图按可见区域归一化后 RGB 差异 RMS 为 `0.0 / 255`，确认图 3 与本次修正前图标为同一版 Logo 与两排文字。

## PNG 验证

所有 15 个顶层 PNG 均为完全不透明（alpha extrema `255,255`），四角均为 `(0,0,0,255)`。

| 文件 | 尺寸 | SHA-256 |
| --- | ---: | --- |
| `128x128.png` | 128×128 | `029494666285d475e37e0bab8e08f6e2e8e0471443f8e99f963e317124ffd7aa` |
| `128x128@2x.png` | 256×256 | `6cd6540c41ace79b0fa14b226f725fc7aaa779354aeed48d2fa67e65cc2c87ff` |
| `32x32.png` | 32×32 | `f6cee21af930632e53b4961e2900a47021e68a804d6af8579038b84c20b1e971` |
| `64x64.png` | 64×64 | `16ee10faf1e2585e7c7d5105a5f7f52af80c500aba4462a222f31b87828cb22e` |
| `Square107x107Logo.png` | 107×107 | `5cd559efd3535ce6365731dd4a3e85db5e6206bb4e66e83ca559a0d6d1db8ed6` |
| `Square142x142Logo.png` | 142×142 | `4bbf12d856e2f513d98f971496cb4790274388f00fa5fb6e8506b257b14ee132` |
| `Square150x150Logo.png` | 150×150 | `406096b650471246ce5f279efa51ed520efff2a8a548ff1dca31b99541a0c72f` |
| `Square284x284Logo.png` | 284×284 | `3aa94ea73b50a8005ff9e906155c5937aaf33423e6c57d687fadbf5c77f8a763` |
| `Square30x30Logo.png` | 30×30 | `9e4edfc4735f29064513fc21fbf2e9d9b85f177af874c4c172f7dc9db6846cce` |
| `Square310x310Logo.png` | 310×310 | `505a37d598ab419a16cefccbfc4261d693b69ada24d72d5deaf196a494c19b1b` |
| `Square44x44Logo.png` | 44×44 | `47ebc12a0cb171dd892071caee5ff1a9b9b4d4391d94d0b8b94e238f0f996bb6` |
| `Square71x71Logo.png` | 71×71 | `24116075c0e60489305d9eb36845f4103bf6020abb0fdeaea3769d276c3676ee` |
| `Square89x89Logo.png` | 89×89 | `7f38ce511a07761d0feb799711fe58decb64759b3615fbff5e51b6b532576690` |
| `StoreLogo.png` | 50×50 | `5a7fec7439daec6d78ce576aeb642121b6d1f18a6cd78bd4b06a16ebd647243e` |
| `icon.png` | 512×512 | `8cc5e214bd8cadecd3f63ee61046a6baa293760354591b01b236e36c281198d6` |

## 容器格式验证

- `icon.ico` SHA-256：`d6bfd7adaf0230d16258147866c6ff264b5c3d6112ff0173ea15d56675dcfe91`；包含 16、24、32、48、64、256 像素六档，逐档检查均完全不透明且四角纯黑。
- `icon.icns` SHA-256：`18285cd65209156c0fb524dfde070b35a7d3fed82ea3a255b01a64961fa521b4`；包含 16、32、128、256、512 的 1x/2x 表示，逐档检查均完全不透明且四角纯黑。
- `app-icon.svg` SHA-256：`de141912e29961d34cd0e8c416524e67d8aa327c03e529ae1df7778e058eac7c`。

## 视觉与范围检查

- `view_image` 检查 512×512 与 128×128 成品：黑色背景完整，金色 Logo 与“众墅之家 / AI 即创”布局未改变，没有裁切。
- `git diff --check` 通过。
- 常见密钥模式扫描无命中。
- Android、iOS、`tauri.conf.json`、`client/package.json` 无本任务差异。
