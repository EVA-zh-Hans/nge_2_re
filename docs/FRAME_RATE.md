- 2048.0 的 IEEE-754 单精度十六进制：0x45000000；在小端内存中的字节序：00 00 00 45
- 4096.0 的 IEEE-754 单精度十六进制：0x45800000；在小端内存中的字节序：00 00 80 45
我刚才研究的要点：

- 确认 2048.0/4096.0 这两个常量分别保存在常量区 0x89B5620 与 0x89B5624，供帧率配置使用
- 追踪 g_TimeStep（0x89EA26C）的写入点，只有 SetFrameRate(0x8819B54)会把它设成 2048.0 或 4096.0
- 主循环 GameLoop(0x8819B88) 每帧调用 Update_WaitVblank(0x88044B8)，其中根据 g_TargetFrameRateMode(0x8AFB8E0)在 30fps 模式下额外多等待一次 VBlank，从而把刷新率从 60 降到 30
- 你把该 Flag 设为 0 强制 60fps 后，3D 动画变快的原因是时间步长是固定步进：逻辑更新次数翻倍但动画/物理没有按 deltaTime 缩放，导致观感“加速”
 
新增：g_TargetFrameRateMode 直接/间接使用点
 
- 直接访问 g_TargetFrameRateMode 的函数
- GetTargetFrameRateMode(0x8819B48)：getter，直接返回 g_TargetFrameRateMode
- SetFrameRate(0x8819B54)：写 g_TargetFrameRateMode，按 30/60fps 切换 g_TimeStep(2048/4096)，返回旧模式
- GameLoop(0x8819B88)：把 g_TargetFrameRateMode 传给 Update_WaitVblank
- 间接使用（通过调用 SetFrameRate 或 GetTargetFrameRateMode 获取模式）
- SetFrameRate 的调用者（部分）：sub_881A4A0、sub_881A86C、sub_881A8F0、sub_881AA48、sub_881B2E0、sub_881B468、sub_881C24C、sub_8849FD8、sub_8884AF4、sub_8884D04、sub_88DA958、sub_88DE40C、sub_88DE604、sub_890DECC、sub_890FEBC、sub_8975690、sub_8975918、sub_8975A04、sub_897E814、sub_8980DE8、sub_8981800、sub_8981DD8、sub_8983188、sub_8983F30
- GetTargetFrameRateMode 的调用者（详细分析）：
  - sub_881B950 (UI 入场动画)：根据帧率调整 `v0` (增量步长)。30fps 时步长为 2，60fps 时为 1，确保动画在不同帧率下消耗的现实时间一致。
  - sub_881C24C (标题界面初始化)：在进入标题前强制调用 `SetFrameRate(0)` (60fps)，并在退出时恢复之前的帧率模式。
  - sub_8830B98 (文本打字机效果)：根据帧率计算字符显示的等待时间/速度。30fps 时 `v17=2`，60fps 时 `v17=1`，补偿帧率差异。
  - sub_884E690 (菜单/选择界面逻辑)：根据帧率调整菜单滑动动画的步长 (`v135`, `v138`) 和插值速度，确保 UI 交互流畅度在 30/60fps 下保持一致。
- 补充说明：

- 在 IDA/内存搜索时，匹配到的 00 00 00 45 与 00 00 80 45 就是 2048.0 与 4096.0 的小端字节序；这些值用于切换 30/60fps 的时间步长
- 方案方向是同时禁用 30fps 下的额外 VBlank 等待，并统一将 g_TimeStep 设为 4096.0，让所有界面保持 60fps，一并考虑把与步进绑定的动画系数做半速补偿，避免“加速”表现