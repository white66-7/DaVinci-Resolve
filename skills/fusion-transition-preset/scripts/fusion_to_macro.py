#!/usr/bin/env python3
"""
fusion_to_macro.py - 把从 Fusion 页面复制出来的节点文本，转换成
DaVinci Resolve「编辑页转场预设」可用的 .setting（MacroOperator 宏）文件。

用法:
    python fusion_to_macro.py INPUT.txt OUTPUT.setting [--name MacroName]
                              [--labels "Background,Foreground"]

输入: Fusion 里 Ctrl+A、Ctrl+C 复制出的整段文本（形如 `{ Tools = ordered() { ... } }`）。
输出: 带两个图像输入（背景=前一个片段，前景=后一个片段）和一个输出的宏。

转换规则:
  1. MediaIn 节点 -> 删除，改成宏的 InstanceInput（按 Layer 0/1 排序）
  2. MediaOut 节点 -> 删除，改成宏的 InstanceOutput
  3. AudioDisplay (Left/Right) -> 删除
  4. 有 ViewInfo 的节点 -> 放进宏内部 Tools
  5. 没有 ViewInfo 的（样条、LUT、Vector 等修改器）-> 放在宏外面的顶层 Tools
  6. 一个 MediaIn 被多个节点使用 -> 自动插入一个直通 Transform 节点再暴露
只用标准库，无需安装任何东西。
"""
import argparse
import re
import sys

IDENT = r"[^\W\d]\w*"


# ----------------------------------------------------------------- 文本解析
def match_brace(s, i):
    """s[i] 必须是 '{'，返回与之配对的 '}' 的下标（跳过字符串里的括号）。"""
    assert s[i] == "{"
    depth = 0
    in_str = False
    j = i
    n = len(s)
    while j < n:
        c = s[j]
        if in_str:
            if c == "\\":
                j += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "-" and s.startswith("--", j):  # Lua 行注释
                k = s.find("\n", j)
                j = n if k < 0 else k
                continue
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j
        j += 1
    raise ValueError("花括号不配对：输入文本可能被截断，请重新完整复制。")


NODE_RE = re.compile(
    r'\s*(?:\["(?P<q>[^"]+)"\]|(?P<b>' + IDENT + r'))\s*=\s*(?P<type>' + IDENT + r')\s*\{'
)


def parse_tools(text):
    """返回 [(name, type, node_text), ...]，保持原顺序。"""
    m = re.search(r"Tools\s*=\s*ordered\(\)\s*\{", text)
    if not m:
        raise ValueError("没找到 `Tools = ordered() {`，这不像是从 Fusion 复制出来的节点文本。")
    open_i = m.end() - 1
    close_i = match_brace(text, open_i)
    body = text[open_i + 1:close_i]

    nodes = []
    pos = 0
    while True:
        # 跳过空白和逗号
        while pos < len(body) and body[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(body):
            break
        mm = NODE_RE.match(body, pos)
        if not mm:
            raise ValueError("无法解析的内容（位置 %d）：%r" % (pos, body[pos:pos + 60]))
        name = mm.group("q") or mm.group("b")
        brace_i = mm.end() - 1
        end_i = match_brace(body, brace_i)
        node_text = body[mm.start():end_i + 1].strip()
        nodes.append((name, mm.group("type"), node_text))
        pos = end_i + 1
    return nodes


# ----------------------------------------------------------------- 辅助
def has_viewinfo(t):
    return re.search(r"ViewInfo\s*=\s*(OperatorInfo|GroupInfo|UnderlayInfo)", t) is not None


def node_pos(t):
    m = re.search(r"Pos\s*=\s*\{\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\}", t)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def media_in_order(name, text):
    m = re.search(r'Layer\s*=\s*Input\s*\{\s*Value\s*=\s*"?(\d+)"?', text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) - 1 if m else 0


def lua_key(name):
    return name if re.fullmatch(IDENT, name) else '["%s"]' % name


def safe_macro_name(s):
    s = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", s)).strip("_")
    if not s or not re.match(r"[A-Za-z_]", s):
        s = "T_" + s
    return s


def indent_block(t, tabs):
    """去掉节点原有的缩进，再整体缩进 tabs 个制表符（仅为美观，Fusion 不关心缩进）。"""
    lines = t.split("\n")
    rest = [ln for ln in lines[1:] if ln.strip()]
    base = min((len(ln) - len(ln.lstrip("\t")) for ln in rest), default=0)
    # 最后一行是节点的收尾 `}`，它的缩进就是节点原本的基准缩进
    last = lines[-1]
    base = min(base, len(last) - len(last.lstrip("\t"))) if len(lines) > 1 else 0
    out = [lines[0]] + [ln[base:] if ln.startswith("\t" * base) else ln for ln in lines[1:]]
    pad = "\t" * tabs
    return "\n".join(pad + ln for ln in out)


# ----------------------------------------------------------------- 转换
def convert(text, macro_name, labels):
    warnings = []
    nodes = parse_tools(text)
    names = [n for n, _, _ in nodes]

    media_ins = [(n, t) for n, ty, t in nodes if ty == "MediaIn"]
    media_outs = [(n, t) for n, ty, t in nodes if ty == "MediaOut"]
    if not media_ins:
        raise ValueError("没找到 MediaIn 节点。请在转场的 Fusion 页面里复制（那里才有 MediaIn1/MediaIn2）。")
    if len(media_ins) == 1:
        warnings.append("只找到 1 个 MediaIn：生成的宏只有 1 个输入，更像「效果」而不是「转场」。")
    media_ins.sort(key=lambda x: media_in_order(*x))
    mi_names = [n for n, _ in media_ins]

    drop_types = {"MediaIn", "MediaOut", "AudioDisplay"}
    kept = [(n, ty, t) for n, ty, t in nodes if ty not in drop_types]
    inner = [(n, ty, t) for n, ty, t in kept if has_viewinfo(t)]
    outer = [(n, ty, t) for n, ty, t in kept if not has_viewinfo(t)]
    inner_names = {n for n, _, _ in inner}

    # ---- 输出节点
    out_src = None
    if media_outs:
        m = re.search(r'SourceOp\s*=\s*"([^"]+)"', media_outs[0][1])
        if m and m.group(1) in inner_names:
            out_src = m.group(1)
    if out_src is None:
        referenced = set(re.findall(r'SourceOp\s*=\s*"([^"]+)"', "\n".join(t for _, _, t in kept)))
        free = [n for n, _, _ in inner if n not in referenced]
        if free:
            out_src = free[-1]
            warnings.append("没找到可用的 MediaOut 连接，已猜测输出节点为 %s。" % out_src)
        else:
            raise ValueError("无法确定输出节点（MediaOut 没连到有效节点）。")

    # ---- 处理每个 MediaIn 的下游
    inner_text = {n: t for n, _, t in inner}
    extra_nodes = []        # 新插入的直通节点文本
    instance_inputs = []    # (SourceOp, Source)

    for idx, mi in enumerate(mi_names):
        pat = re.compile(
            r"(?P<key>" + IDENT + r"|\[\"[^\"]+\"\])\s*=\s*Input\s*\{\s*"
            r"SourceOp\s*=\s*\"" + re.escape(mi) + r"\"\s*,\s*Source\s*=\s*\"Output\"\s*,?\s*\}\s*,?"
        )
        consumers = []
        for n in list(inner_text):
            for m in pat.finditer(inner_text[n]):
                consumers.append((n, m.group("key")))
        for n, _, t in outer:
            if re.search(r'SourceOp\s*=\s*"%s"' % re.escape(mi), t):
                warnings.append("修改器 %s 引用了 %s，未处理，请手动检查。" % (n, mi))

        if not consumers:
            warnings.append("%s 没有被任何节点使用，已忽略。" % mi)
            continue

        if len(consumers) == 1:
            n, key = consumers[0]
            inner_text[n] = pat.sub("", inner_text[n], count=1)
            instance_inputs.append((n, key))
        else:
            pass_name = "In%d_Pass" % (idx + 1)
            while pass_name in names or pass_name in inner_text:
                pass_name += "_"
            for n, _ in consumers:
                inner_text[n] = re.sub(
                    r'(SourceOp\s*=\s*")' + re.escape(mi) + r'(")', r"\g<1>" + pass_name + r"\g<2>", inner_text[n]
                )
            x, y = node_pos([t for n, t in media_ins if n == mi][0])
            extra_nodes.append(
                "%s = Transform {\n\tViewInfo = OperatorInfo { Pos = { %s, %s } },\n}" % (pass_name, x, y)
            )
            instance_inputs.append((pass_name, "Input"))
            warnings.append("%s 被 %d 个节点使用，已插入直通节点 %s。" % (mi, len(consumers), pass_name))

    # ---- 检查悬空引用
    all_names = set(inner_text) | {n for n, _, _ in outer} | {re.match(r"\w+", t).group(0) for t in extra_nodes}
    refs = set()
    for t in list(inner_text.values()) + [t for _, _, t in outer]:
        refs |= set(re.findall(r'SourceOp\s*=\s*"([^"]+)"', t))
    dangling = sorted(r for r in refs if r not in all_names)
    if dangling:
        warnings.append("以下 SourceOp 指向不存在的节点（可能无害，但值得检查）：" + ", ".join(dangling))

    if any("comp.RenderEnd" in t for t in inner_text.values()):
        warnings.append("表达式里用了 comp.RenderEnd：宏里按转场长度归一化，请在时间线上实际预览一遍节奏。")

    # ---- 组装
    pieces_in = []
    for n, ty, t in inner:
        pieces_in.append(indent_block(inner_text[n], 4) + ",")
    for t in extra_nodes:
        pieces_in.append(indent_block(t, 4) + ",")
    inner_block = "\n".join(pieces_in)

    inputs_block = []
    for i, (src, key) in enumerate(instance_inputs):
        label = labels[i] if i < len(labels) else "Input%d" % (i + 1)
        inputs_block.append(
            '\t\t\t\tInput%d = InstanceInput {\n\t\t\t\t\tSourceOp = "%s",\n\t\t\t\t\tSource = "%s",\n\t\t\t\t\tName = "%s",\n\t\t\t\t},'
            % (i + 1, src, key.strip('[]"'), label)
        )

    outer_block = "\n".join(indent_block(t, 2) + "," for _, _, t in outer)

    out = (
        "{\n\tTools = ordered() {\n"
        "\t\t%(name)s = MacroOperator {\n"
        "\t\t\tCtrlWZoom = false,\n"
        "\t\t\tNameSet = true,\n"
        "\t\t\tInputs = ordered() {\n%(inputs)s\n\t\t\t},\n"
        "\t\t\tOutputs = {\n"
        "\t\t\t\tOutput1 = InstanceOutput {\n"
        "\t\t\t\t\tSourceOp = \"%(out)s\",\n"
        "\t\t\t\t\tSource = \"Output\",\n"
        "\t\t\t\t},\n"
        "\t\t\t},\n"
        "\t\t\tViewInfo = GroupInfo {\n"
        "\t\t\t\tPos = { 310.583, 127.849 },\n"
        "\t\t\t\tFlags = {\n"
        "\t\t\t\t\tAllowPan = false,\n"
        "\t\t\t\t\tGridSnap = true,\n"
        "\t\t\t\t\tAutoSnap = true,\n"
        "\t\t\t\t\tRemoveRouters = true,\n"
        "\t\t\t\t},\n"
        "\t\t\t\tSize = { 498, 168.598, 255.333, 61.9548 },\n"
        "\t\t\t\tDirection = \"Horizontal\",\n"
        "\t\t\t\tPipeStyle = \"Direct\",\n"
        "\t\t\t\tScale = 1,\n"
        "\t\t\t\tOffset = { 0, 0 },\n"
        "\t\t\t},\n"
        "\t\t\tTools = ordered() {\n%(inner)s\n\t\t\t},\n"
        "\t\t},\n"
        "%(outer)s%(outer_nl)s"
        "\t},\n}\n"
    ) % {
        "name": macro_name,
        "inputs": "\n".join(inputs_block),
        "out": out_src,
        "inner": inner_block,
        "outer": outer_block,
        "outer_nl": "\n" if outer_block else "",
    }

    # ---- 自检
    if out.count("{") != out.count("}"):
        raise ValueError("生成结果花括号不配对，转换失败。")
    summary = {
        "inputs": instance_inputs,
        "output": out_src,
        "inner": [n for n, _, _ in inner] + [re.match(r"\w+", t).group(0) for t in extra_nodes],
        "outer": [n for n, _, _ in outer],
        "dropped": [n for n, ty, _ in nodes if ty in drop_types],
    }
    return out, summary, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--name", default="Custom_Transition", help="宏名称（仅字母数字下划线，会自动清理）")
    ap.add_argument("--labels", default="Background,Foreground", help="两个输入的显示名，逗号分隔")
    a = ap.parse_args()

    with open(a.input, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")

    try:
        out, summary, warnings = convert(text, safe_macro_name(a.name), [x.strip() for x in a.labels.split(",")])
    except ValueError as e:
        print("转换失败：%s" % e, file=sys.stderr)
        sys.exit(1)

    with open(a.output, "w", encoding="utf-8", newline="\n") as f:  # UTF-8，无 BOM
        f.write(out)

    print("OK ->", a.output)
    print("宏输入  :", ", ".join("Input%d=%s.%s" % (i + 1, s, k) for i, (s, k) in enumerate(summary["inputs"])))
    print("宏输出  :", summary["output"])
    print("内部节点:", ", ".join(summary["inner"]))
    print("外部修改器:", ", ".join(summary["outer"]) or "(无)")
    print("已删除  :", ", ".join(summary["dropped"]))
    for w in warnings:
        print("注意:", w)


if __name__ == "__main__":
    main()
