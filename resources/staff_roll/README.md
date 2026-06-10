# 汉化演职员表

`credits.json` 是追加到原版 Staff Roll 尾部的汉化演职员清单。

- `title`：职责标题，独占一行并显示分隔线。
- `names`：姓名列表，每两个姓名组成左右两列；奇数个姓名时，最后一个居中显示。
- 每个标题占 1 个物理行，每两个姓名占 1 个物理行。
- 生成器每 12 个物理行自动切分一个 HGPT，并依次命名为 `staff21.hpt`、
  `staff22.hpt`、`staff23.hpt` 等；职位组允许跨图集，但游戏显示保持连续。
- 单条文字超出所属区域时会单独缩小字号，其他条目仍使用清单中的字号。

运行 `make generate_staff_roll` 会生成所有 `staffNN.hpt`、各图集预览、
总预览 `staff_roll.png`、元数据和 PRX 使用的 `generated_staff_roll.h`。
运行 `make inject_staff_roll` 会把全部图集注入已导出的
`build/ULJS00064/PSP_GAME/USRDIR/game/staff.har`，并清理已不再需要的旧扩展图集。
