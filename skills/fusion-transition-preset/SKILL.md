---
name: fusion-transition-preset
description: 把从 DaVinci Resolve（达芬奇）Fusion 页面复制出来的节点文本，转换成「编辑页转场预设」可直接使用的 .setting 宏文件。只要用户贴出一大段 `{ Tools = ordered() { ... MediaIn1 ... MediaOut1 ... } }` 的 Fusion 节点代码，或提到「做成转场预设 / 保存成 setting / 自制转场放进效果库 / Fusion 转场模板 / 拖到时间线转场上是黑的或 Fusion 里是空的」，就必须使用本技能，即使用户没说"宏"或"Macro"。
---

# Fusion 转场 → 预设（.setting 宏）

## 本机环境（固定路径，Windows）

本技能只装在当前 DaVinci Resolve 项目目录里，**只在本项目内生效**，不要用 Linux/macOS 路径。所有命令在 Windows + PowerShell 下执行：

| 用途 | 固定路径 |
|---|---|
| 项目根 | `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve` |
| 技能目录 | `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve\.dsh\skills\fusion-transition-preset` |
| 转换脚本 | `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve\.dsh\skills\fusion-transition-preset\scripts\fusion_to_macro.py` |
| 工作目录（输入/输出都放这里） | `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve\.dsh\work` |
| 输入文本 | `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve\.dsh\work\input.txt` |
| 输出预设 | `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve\.dsh\work\<预设名>.setting` |

- 工作目录不存在时先建：`New-Item -ItemType Directory -Force "<项目根>\.dsh\work"`。
- 脚本只用 Python 标准库；命令用 `python`，若不可用再试 `py -3`。
- 不要 `cd` 到别的盘符或临时目录，输入输出一律落在上面这个 `.dsh\work` 里。

## 为什么需要转换

在转场的 Fusion 页面里 Ctrl+A、Ctrl+C 复制出来的是**一堆散节点**，里面有 `MediaIn1`、`MediaIn2`、`MediaOut1`。
直接把它存成 .setting 放进转场模板目录，Resolve 能在效果库里显示，但拖到时间线上后 **Fusion 页面是空的、画面是黑的**。

能生效的预设都是 **MacroOperator（宏）**：对外只暴露两个图像输入（背景、前景）和一个输出，Resolve 靠这几个接口把转场前后两段画面接进来。
本技能的脚本就是把散节点包装成这种宏。这个宏结构已经在用户自己的 Resolve 上验证过能被识别并生效。

## 流程

1. **拿到输入**。用户会在对话里贴一整段 Fusion 文本。用 `write` 工具把它**原样**存成
   `C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve\.dsh\work\input.txt`（UTF-8），
   不要改动、不要总结、不要补全、不要重新排版。
   - 如果文本明显被截断（花括号不配对），让用户重新完整复制，不要自己补。
   - 如果里面没有 `MediaIn`，让用户回到**转场的 Fusion 页面**，Ctrl+A 全选后再复制（要把 MediaIn/MediaOut 一起选上）。
2. **取名**。预设名（宏名）问不到就用用户给的称呼，或 `Custom_Transition`。脚本会把中文和空格清理成下划线，文件名可以保留中文。
3. **运行脚本**（PowerShell，路径全部写死，不要再拼 `/mnt/...`）：

   ```powershell
   $root = "C:\Users\12625\Desktop\PROJECTS\plugins\DaVinci Resolve"
   python "$root\.dsh\skills\fusion-transition-preset\scripts\fusion_to_macro.py" `
       "$root\.dsh\work\input.txt" "$root\.dsh\work\<预设名>.setting" `
       --name <宏名> --labels "Background,Foreground"
   ```

   - 脚本把结果写成 UTF-8、无 BOM、LF 换行，符合 Resolve 读取习惯。
   - 控制台里中文若显示成乱码，只是控制台代码页问题，`.setting` 文件内容不受影响，不用重跑。
   - 想用中文接口名就传 `--labels "背景,前景"`（中文参数在 Windows 上能正常传入）。
   - 脚本报错时先看报错文本：花括号不配对 → 让用户重贴；没找到 MediaIn → 回流程第 1 步。
4. **读脚本输出**，向用户确认三件事：
   - 宏输入：`Input1`（背景 = 前一个片段 = 原 MediaIn Layer 0）、`Input2`（前景 = 后一个片段 = Layer 1）分别接到了哪个节点；
   - 宏输出接的是哪个节点；
   - 有没有「注意:」警告，原样转告用户。
5. **交付**：用 `present` 工具把 `.dsh\work\<预设名>.setting` 发给用户，然后用中文给出安装步骤（见下）。回复末尾以文字收尾。

## 安装步骤（发给用户）

1. 把 .setting 放进 Resolve 的转场模板目录下的一个自定义文件夹（Windows）：
   `C:\Users\12625\AppData\Roaming\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Transitions\<自定义文件夹>\`
   （用户之前能用的预设放在哪就放同一级；若目录不存在，先用资源管理器建好同名的 `Transitions` 子文件夹。）
2. 同名旧文件先删掉或移走，避免效果库里出现重复的转场。
3. **完全退出并重启 Resolve**，在编辑页效果库的转场里找到它，拖到两个片段之间。

> macOS 用户则是 `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/Edit/Transitions/<自定义文件夹>/`，本机用不到。

## 脚本做了什么（需要向用户解释时用）

| 原节点 | 处理 |
|---|---|
| `MediaIn1/2`（按 Layer 0、1 排序） | 删除，改成宏的两个 InstanceInput |
| `MediaOut1` | 删除，改成宏的 InstanceOutput |
| `Left`/`Right`（AudioDisplay） | 删除 |
| 有 `ViewInfo` 的节点 | 放进宏内部 |
| 没有 `ViewInfo` 的修改器（样条、LUT、Vector 等） | 放在宏外面的顶层，和能用的预设保持一致 |
| 一个 MediaIn 被多个节点共用 | 自动插入直通 Transform（`In1_Pass`）再暴露 |

**节点参数和表达式一律不改**。脚本只负责打包。

## 常见问题

- **拖上去 Fusion 里还是空的**：先确认文件在转场模板目录里、已完全重启 Resolve；再确认用户用的是本技能生成的文件而不是直接复制出来的原始文本。仍然不行，请用户截一张 Fusion 节点图。
- **前后画面顺序反了**：Dissolve 的 Mix 为 0 时显示背景。如果转场变成后一个片段先出现，说明 Layer 0 / Layer 1 对应反了，或表达式方向反了。不要猜，先问用户原来在 Fusion 页面里看到的顺序，再决定交换两个 `InstanceInput` 的 `SourceOp`，或改 Mix 表达式。
- **节奏不对 / 动画停在某个状态**：表达式里的 `time/comp.RenderEnd` 是按转场长度归一化的，这一点我没法在沙箱里验证，需要用户在时间线上预览。
- **想要中文输入名**：用 `--labels "背景,前景"`，中文名可以正常使用。
- **脚本报「没找到 MediaIn」**：见流程第 1 步。
- **路径相关报错**：确认命令里的路径确实是 `C:\...\.dsh\work\...` 这种 Windows 反斜杠形式，且 `.dsh\work` 目录已存在；不要写成 `/home/...` 或 `/mnt/...`。

## 注意

- 本技能只装在当前项目（`<项目根>\.dsh\skills`），换到别的项目目录就不生效；确实要全局可用才复制到 `C:\Users\12625\.dsh\skills\`，不要擅自搬动。
- 只在用户要求时才改节点参数；发现明显问题（比如两个通道的缩放符号相同）可以提醒，但不要擅自修改。
- 不要声称已在 Resolve 里测试过生成的文件，沙箱里没有 Resolve。可以说「结构与能正常加载的预设一致」。
- 用户的 Fusion 文本里常有中文（节点名、MEDIA_NAME），这是正常的，脚本能处理。
