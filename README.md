# archive

更好的管理知识库，包括打包，查找，取出等功能

整理零散的知识让人头疼，尤其是当他们互不相干，数量庞大的时候，将其打包放到知识库中是容易的，但想要重新拿出来研究时，会遇到找不到的情况。。。为了避免每次在寻找上面浪费时间，我引入了.MY_README.md文件，想要实现类似高级语言中函数的注释的功能，方便寻找，于是便产生了这个项目
安装和用法都非常简单，希望帮助到有需要的人😙😙😙


## 安装

### linux

```bash
git clone https://github.com/yhbshishuaige/archive.git
cd ./archive
chmod +x ./install.sh
sudo ./install.sh
```

默认安装到`/usr/bin/archive`，但是`install.sh`支持自定义到任何路径，如果只是想要尝试一下的话`./install.sh /your/path`

## 使用

**第一次使用需要设置base和workspace**

- 也可以在执行时作为参数指定

```bash
archive --set_base ~/your/base
archive --set_workspace ~/your/workspace
archive --set_base ~/your/base --set_workspace ~/your/workspace
```

![](./img/set.png)

**归档**

- .MY_README.md文件只要存在即可，里面可以放任何东西，格式并不会影响到程序执行

```bash
# 获得.MY_README.md
archive -g
archive -pf ./
```

![](./img/myreadme.png)

![](./img/pack.png)

**查找**

- 这是整个文件系统的核心，当你在保存的时候花费一点时间写一点注释到.MY_README.md文件，会对你的寻找提供巨大帮助，在有大量零散知识点的时候，这很有必要

```bash
archive -F "源码" "文件管理系统"
```

![](./img/search.png)

**解包到工作区**

- 随时可以拿出刀工作区中继续你的工作

```bash
archive -u /example/path
```

![](./img/unpack.png)

**查看帮助**

- help参数是最有帮助的，对于一个健壮的程序，我坚信

```bash
archive --help
```
![](./img/help.png)

**当base的名称变化的时候，可以更新.archive中已经保存的路径**

- 这个功能是为了方便对知识库进行迁移，比如你原来的知识库名称是name1，但后来换成了name2，使用--repair参数可以很好的进行迁移，因为在~/.archive文件中的已保存路径并不是使用静态的绝对路径，而是拼接了知识库base和文件name，这意味着你可以随意的更改知识库名称，前提是需要先使用--set_base修改知识库路径为新的路径

- 当然了，也可以直接删除~/.archive进行重置（如果认为上面的功能真的很鸡肋）

```bash
archive --repair
```

**查看配置**

- 提供查询当前配置的参数，你也可以通过cat ~/.archive查看，选择你喜欢的

```bash
archive -c
archive --show_base
archive --show_workspace
```

![](./img/show.png)

**删除**

- 提供删除功能，这个项目总共会在你的电脑上保存两个文件，一个是/usr/bin/archive，另一个是~/.archive，十分轻量，如果不喜欢，随时删除，他不会在你的电脑上其他位置出现，如果你使用的是默认配置（喜欢折腾的人不会使用这个项目好像也(）

```bash
archive --uninstall -f
```

![](./img/del.png)

## `.MY_README.md` 

```markdown
# 归档说明

- 文件夹名称：你希望创建的名称，若为空则会自动创建加上前缀auto_
- 类型：
- 关键词：
- 状态：
- 简述：
```

## 要求

- ubuntu18默认python是3.7无法使用这个垃圾项目（

python版本 >= 3.8
