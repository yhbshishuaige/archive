# archive

一个面向临时项目、CTF 题目、想法实验目录的本地归档工具。它依赖每个待归档目录中的 `.MY_README.md` 做人工说明，并用 `meta.json` 做系统管理。

## 安装

默认安装到 `/usr/bin/archive`：

```bash
cd /home/loo/test/archive
sudo sh install.sh
```

如果想先安装到别的位置测试：

```bash
sh install.sh /tmp/archive
/tmp/archive --help
```

## 常用命令

```bash
archive --set_base ~/my_archive
archive --set_workspace ~/workspace
archive --show_base
archive --show_workspace

archive --get_readme
archive --get_readme -f

archive --packed_folder ./demo
archive --packed_folder=./demo --tmp_base=~/my_archive
archive -p ./demo -b ~/my_archive
archive -p ./demo --no-zip
archive -pf ./demo

archive --search pwn ret2libc
archive -F pwn ret2libc
archive --unpack pwn_ret2libc_basic --workspace ~/workspace
archive --repair
```

配置文件固定为 `~/.archive`。每次归档成功后，工具会把生成的归档目录路径记录到这个配置文件中；`-F/--search` 只会搜索这些被记录过的归档目录。

如果改名或移动了默认 base，先重新设置 base，再修复记录：

```bash
archive --set_base ~/new_archive_base
archive --repair
```

卸载全局命令和配置文件：

```bash
sudo archive --uninstall -f
```

## `.MY_README.md` 模板

```markdown
# 归档说明

- 文件夹名称：
- 类型：
- 关键词：
- 状态：
- 简述：

## 详细记录
```

`文件夹名称：` 会被用于生成归档目录名。空格会替换为 `_`，非法路径字符会替换为 `_`。如果没有填写文件夹名称，工具会生成 `auto_` 前缀的名称。

## 归档结构

默认 zip 模式：

```text
archive_base/
  name/
    .MY_README.md
    content.zip
    meta.json
```

使用 `--no-zip` 时：

```text
archive_base/
  name/
    .MY_README.md
    files/
      ...
    meta.json
```
