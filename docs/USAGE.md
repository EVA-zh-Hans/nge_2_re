# 使用方法


## 初次使用

### Windows

1. 安装 `MSYS2`
2. 打开 `MINGW64`终端
3. 安装 `uv`
   1. 运行 `pacman -Ss uv`
4. 克隆本仓库
   1. 目录位于 `C:\msys64\home\<user-name>\nge_2_re`
   2. 在该文件夹下创建 `temp` 目录，将提取出的游戏镜像命名为 `ULJS00064.iso` 并放入 `temp` 目录
5. 运行 `make full_build`
6. 在 `build` 目录下会生成打好补丁的ISO

### MacOS
1. 安装 `HomeBrew`
2. 安装 `uv`
   1. `brew install uv`
3. 克隆本仓库
4. 类似

### Linux (Ubuntu / Debian)

1. 安装系统依赖（示例适用于 Ubuntu/Debian）:

   ```sh
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip xdelta3 libuv1-dev
   ```

2. 推荐使用虚拟环境：

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -U pip
   pip install uv
   ```

   > 注：本项目的 Makefile 使用 `uv run` 来调用模块，安装 `uv` 可使 `uv run -m ...` 可用；也可改用 `python3 -m` 直接执行。

3. 克隆本仓库到工作目录并创建 `temp` 目录；将原始游戏镜像命名为 `ULJS00064.iso` 并放入 `temp`：

   ```sh
   git clone <repo-url>
   cd nge_2_re
   mkdir -p temp
   # 将 ULJS00064.iso 放到 temp/ 下
   ```

4. 运行完整构建：

   ```sh
   make full_build
   ```

5. 输出结果在 `build` 目录下，例如 `build/ULJS00064_patched.iso` 和 `build/ULJS00064_patch.xdelta`。

## 运行方式（命令行）

使用 Makefile 中封装的任务或直接使用 `uv run -m` / `python3 -m` 调用模块。

常见示例：

- 下载并合并 ParaTranz 翻译：

  ```sh
  AUTH_KEY=<your-api-key> make download_trans
  ```

- 导入下载的翻译：

  ```sh
  make import_trans
  ```

- 导出游戏资源：

  ```sh
  make export_all
  ```

- 仅重打 ISO（假如已经生成了替换后的游戏文件）：

  ```sh
  make repack_iso
  ```

- 完整流水线（从 ISO 抽取到生成补丁）：

  ```sh
  make full_build
  ```

## 常用 Make 目标说明

- `make init_db`：初始化/重建项目数据库（首次运行需要）。
- `make import_all`：导入所有游戏资源（hgar、文本、绑定、图片等）。
- `make download_trans`：从 ParaTranz 下载并合并翻译文件，使用 `AUTH_KEY` 环境变量提供 API 密钥。
- `make import_trans`：将下载好的翻译导入数据库。
- `make export_all`：生成替换后的二进制、文本和 hgar 文件，准备打包回 ISO。
- `make plugin`：编译插件并复制到导出目录（需要 `plugin` 子项目的构建工具）。
- `make decrypt_eboot`：使用 `pspdecrypt` 解密 EBOOT（依赖第三方工具）。
- `make patch_iso`：执行 `repack_iso` + `gen_xdelta`，产出 `*_patched.iso` 与 xdelta 补丁。

## 翻译调试

1. 下载翻译并预处理：

   ```sh
   AUTH_KEY=<your-api-key> make download_trans
   ```

2. 导入下载好的翻译：

   ```sh
   make import_trans
   ```

3. 导出游戏资源以便本地测试：

   ```sh
   make export_all
   ```

4. 若要只重新打包 ISO（已生成 `build/ULJS00064` 目录）：

   ```sh
   make repack_iso
   ```

## 故障排查（常见问题）

- 找不到 `uv run`：
  - 确认已安装 `uv`（推荐在虚拟环境中 `pip install uv`），或将 Makefile 中的 `UV_RUN` 改为 `python3 -m`。

- xdelta3/pspdecrypt 等工具缺失：
  - 安装系统包（例如 Ubuntu 上的 `xdelta3`），或查看 `third_party` 目录下的构建说明并运行对应的 `make`。

- ISO 未找到或名称错误：
  - 确保原始镜像位于 `temp/ULJS00064.iso`，Makefile 使用该路径进行抽取与对比生成补丁。

- 权限问题或文件被占用：
  - 在 Windows 下使用 MSYS2 的 MINGW64 终端运行，避免直接在原始 Windows 命令行中执行部分 POSIX 命令。

## 其他说明

- 如果你偏好不使用 `uv`，也可以把 Makefile 中的 `UV_RUN` 和 `PYTHON_MAIN` 替换为 `python3`（例如 `PYTHON_MAIN := python3 -m app.cli.main`）。
- 若需要构建第三方工具（如 `pspdecrypt`、`pgftool`），请进入 `third_party/*` 或 `plugin` 目录并按各自 `Makefile` 的说明构建。
- 更多详情请参阅项目根目录的 `README.md`。

### 翻译调试

1. 运行 `AUTH_KEY=<your-api-key> make download_trans` 下载翻译并进行预处理
2. 运行 `make import_trans` 导入下载好的翻译
3. 运行 `make export_all` 导出游戏资源文件
