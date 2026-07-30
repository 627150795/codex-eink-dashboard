# 中间态交付：安全加固 + 激进项决策门

时间：2026-07-21  
范围：SKD-CLOCK / DA14585 / Codex 墨水屏监控  
原则：**先吃满 PC 端收益；固件侧只调研到可决策，不写机。**

---

## A. 安全项已落地（本轮代码）

路径：`outputs/codex-eink-dashboard/`

### 问题（日志证据）

`logs/dashboard.log` 约 17 小时样本：

| 指标 | 值 |
|---|---|
| uploaded | 214 |
| unchanged | 97 |
| retry | 24 |
| upload 占比 | ~63% |
| 最长连续上传 | 36 次 |

根因：

1. `_once()` **每次轮询先 `probe()`**，与 README「哈希相同不扫蓝牙」不符。  
2. 竖版 `BAT x.xV` 用原始毫伏电压渲染；`3.47` 与 `3.41` 等会改变位图 → 整屏全刷。  
3. 上传与状态读取分两次连接，GATT 瞬时错误时重试面偏窄。

### 改动

| 文件 | 内容 |
|---|---|
| `src/codex_eink/cli.py` | 内容优先路径：先本地渲染+digest；未变则零 BLE；需上传时单连接 status→量化电压→写图 |
| `src/codex_eink/service.py` | `quantize_battery_voltage()` 0.1V 步长 + 0.08V 滞回；`FrameCache` 持久化 `battery_display` |
| `src/codex_eink/ble.py` | `with_client()` 统一重试；上传默认 `retries=2`；`write_packets` 可复用已读 status |
| 测试/文档 | `test_service` / `test_render` / README / ACCEPTANCE 同步 |

### 期望收益（不刷机天花板）

- 无内容变化时：轮询只做本机会话/额度读取，**不扫 BLE、不耗设备广播窗口**  
- 电压在 0.1V 档内抖动：不再触发上传  
- 物理全刷时长不变（原厂波形）  
- 任务/额度真变化时：仍整帧 23 包上传

### 验证

```powershell
cd outputs\codex-eink-dashboard
.\.venv\Scripts\python -m unittest discover -s tests -v
.\start.ps1 once
# 连续 unchanged 时 Windows 蓝牙应无明显扫描尖峰；日志应以 unchanged 为主
```

---

## B. 激进项调研（到决策门为止）

### 候选基线

- 仓库：https://github.com/T-Anh17/eink_da14585_104x212  
- 分支：`main`；语言 C；**stars=0**；forks=5；**license=null**  
- 最近 push：2026-07-03  
- 基于 Dialog **SDK_6.0.18.1182.1** + Keil uVision5 + **J-Link SWD**（README 明确，不是随便 OTA）  
- 关键驱动：`EPD_2in13_V2.c/.h`（Waveshare 2.13 V2 派生）  
  - 分辨率宏：`WIDTH 104` / `HEIGHT 212`  
  - 全刷/局刷：`EPD_2IN13_V2_FULL` / `PART`  
  - 局刷 API：`DisplayPart` / `DisplayPartBaseImage` / `TurnOnDisplayPart` / `EPD_SetWindow`  
  - 引脚注释：POWER P2.3，BUSY P2.0，RST P0.7，DC P0.5，CS P2.1，SCLK P0.0，SDI P0.6  

### BLE 不兼容（确认）

自定义 128-bit UUID（例如 service 侧 `0x1f10` 风格 / `DEF_SVC2_*`），**不是**现网 `0xFF00/0xFF01/0xFF02` + `0x60/0x61/0x62`。  
`user_custs1_impl.c` 多处在图片相关命令路径把 `is_part = 0`（回全刷），局刷状态机存在但**默认上传路径不保证局刷**。

### 原厂烧录/OTA 约束

- 全量烧录：J-Link（VCC/GND/SWC/SWD），原厂推荐 J-Link 7.88j + JFlash  
- OTA 文档硬警告：非本站全量固件初始化后直接 OTA → **变砖**  
- 因此：任何自定义固件必须以 **SWD 备份 + SWD 烧录** 为前提，禁止拿第三方 hex 直接走原厂网页 OTA

### 编译可行性（纸面，本机未装 Keil）

| 需求 | 状态 |
|---|---|
| Keil uVision5 | 需本机安装（未在本轮验证） |
| Dialog/Renesas SDK 6.0.18.1182.1 | 需从 Renesas 下载并按仓库目录布局放置 |
| 仓库工程树 | 约 1853 文件，含完整 `ble_app_ota` 工程骨架 |
| 许可证 | 无 SPDX；自用研究可，再分发/商用需自担 |
| 一键 Release 固件 | **无** |

---

## C. SWD 备份清单（动手刷机前的硬门槛）

在考虑任何非原厂固件之前，**全部勾选**才允许进入编译/烧录试验：

1. [ ] 已有可用 **J-Link**（优先原厂推荐 7.88j）与线材  
2. [ ] 能对照原厂图找到 DA14585 **VCC / GND / SWDIO / SWCLK**（及可选 RESET）  
3. [ ] 用 J-Flash / commander 读出并保存至少：  
   - 完整 flash 镜像（命名含日期与设备 MAC，例如 `skd-clock-AABBCCDDEEFF-fw1.8-full-YYYYMMDD.bin`）  
   - OTP/配置区（若工具可见）  
4. [ ] 在同一台机器上完成一次 **擦除→写回备份→设备恢复原厂 BLE 名与协议** 的回环验证  
5. [ ] 备份文件异地再存一份（网盘/另一块盘）  
6. [ ] 确认 EPD 控制器丝印/型号与 `EPD_2in13_V2` 兼容，或接受“引脚/控制器不对则停工”  
7. [ ] 接受残影/寿命风险与无厂商支持  

**任一项未完成 → 停在安全项，禁止写机。**

---

## D. 刷机 / 停手决策表

| 条件 | 动作 |
|---|---|
| 无 J-Link 或无法 SWD 备份回环 | **停手**，只用 PC 端方案 |
| 拆机后引脚与 `EPD_2in13_V2.h` 严重不符且无法重映射 | **停手** 或改为纯驱动研究，不写此设备 |
| 控制器不是 SSD16xx/UC81xx 同类、无参考 LUT | **停手**（工作量失控） |
| 备份回环成功 + 引脚匹配 + Keil/SDK 能编过参考工程 | 允许进入「只收图不刷新」兼容固件试验 |
| 想用原厂网页 OTA 刷第三方固件 | **禁止** |
| 局刷实测残影不可接受且全刷无法清 | 回滚原厂，回到安全项 |
| 仅想少刷屏/更稳 | **不必刷机**；本轮安全加固已是主路径 |

### 若未来开闸，建议阶段（仍属后续，非本轮）

1. 编译 `T-Anh17` 原样，SWD 烧到**备用同款板**（若有）  
2. 移植 UUID/命令到 `0xFF00` + `0x60/61/62`，先只收缓冲不 `TurnOnDisplay`  
3. 再开局刷 + 每 N 次强制全刷  
4. 记录全刷/局刷秒表、残影照片、电流  

---

## E. 当前推荐站位

| 轨道 | 状态 |
|---|---|
| 安全项 | **已加固并应作为日常方案** |
| 激进项 | **调研完成；决策门未打开**（缺 SWD 备份回环与引脚实物确认） |
| 用户体验预期 | 刷新更少、更稳；**不会**变成局刷快屏 |

下一步若只选一件事：观察加固后 24h 日志的 `uploaded/unchanged/retry` 比例，确认 upload 占比从 ~63% 明显下降。
