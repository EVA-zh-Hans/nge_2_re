# 汉化演职员表

`credits.json` 是追加到原版 Staff Roll 尾部的汉化演职员清单。

- `title`：职责标题，独占一行并显示分隔线。
- `names`：姓名列表，每两个姓名组成左右两列；奇数个姓名时，最后一个居中显示。
- 单个图集最多使用 12 个物理行：每个标题占 1 行，每两个姓名占 1 行。

运行 `make generate_staff_roll` 会生成 `staff21.hpt`、预览图和 PRX 使用的
`generated_staff_roll.h`。运行 `make inject_staff_roll` 会把图集注入已导出的
`build/ULJS00064/PSP_GAME/USRDIR/game/staff.har`。
