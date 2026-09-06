# VENDOR-NOTES — douyin_publisher

- 来源：https://github.com/phlong026/douyin_publisher （commit `f61418d`，2026-08-18）
- 授权背景：该仓库与本项目同属所有者 phlong026，作为 C5 发布能力的协议实现供应商源码引入。
- 接口性质：非官方协议复刻（creator.douyin.com 抓包），平台改版即可能失效；登录态（Cookie
  + security_sdk）由用户在界面手工粘贴，服务端 Fernet 加密保存，永不入库明文/日志。

## 拷贝内容

| 文件 | 说明 |
| --- | --- |
| `publish.py` | DouyinPublisher / check_login；**已删除 `main()`（原文件内含硬编码客户广告文案与 OSS URL）与 `__main__` 块**；三处内部 import 改为包内相对导入 |
| `publish_options.py` | PublishOptions 参数模型 |
| `sign_params.py` | msToken / a_bogus / ticket-guard 风控签名（Node 子进程池） |
| `http_client.py` | curl_cffi TLS 指纹会话 |
| `_reverse/bdms.min.js`、`_reverse/sdk-glue.js` | 运行时必需的逆向 bundle（a_bogus 虚拟机与 mssdk 映射）；其余 `_reverse` 参考产物**未引入**——其中 `ucenter_ticket.umd.js` 含 PEM 密钥头模板字符串，会触发静态凭据扫描，且运行时并不需要 |
| `sign_a_bogus/`、`sign_mssdk/` | Node 签名脚本（运行时依赖 Node.js ≥ 18） |

## 未拷贝（及原因）

- `main.py` 入口示例（硬编码业务内容）、`cookies.example.txt`、`security_sdk.example.json`、
  `session_dtrait.example.txt`、`options.json`、README/FLOWCHART、`requirements.txt`
  （依赖统一收口到 `server/pyproject.toml`）。

## 本仓库改造点

1. `publish.py`：删除 `main()` / `__main__`；`from sign_params/publish_options/http_client import`
   → 相对导入。
2. 运行依赖：`requests`、`curl-cffi`、`cryptography`（已在 pyproject）+ 外部 **Node.js ≥ 18**
   （部署前置条件，缺失时适配层 fail-fast）。

## 已知运行约束

- `sign_params.py` 通过 `Path(__file__).parent` 定位 JS 目录，目录树必须整体保留。
- 凭据一律经 `douyin_adapter.py` 以参数注入（构造函数本就支持），不再读取任何文件。
- `publish_images`（图文发布）本仓库未使用，对应代码未验证。
