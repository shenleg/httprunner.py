# 介绍
基于 v4.3.5 版本更改，个人习惯使用 pytest 运行用例，所以会围绕着 pytest 来更改

PS：修改基本靠AI，我提需求AI写，我负责核对和测试。感谢AI。

# 二次开发改动记录
1. `v4.3.5.1`
    * `httprunner make` 增加一个命令行参数 `--output-dir`，可以指定输出的 pytest 测试文件的目录
2. `v4.3.5.2`
    * 支持不同环境的 .env 文件，使用时需要手动设置环境变量，比如设置 `ENV=test`，则对应 `config/.env.test` 文件
    * 修复 `v4.3.5.1` 的问题，现在会先把目录清空再重新生成
    * 修复日志中文乱码
3. `v4.3.5.3`
    * 支持从响应文本中使用正则表达式提取变量了，使用参考 `test_case_yaml\test_regex_extract.yml`

# todo
1. yaml中支持pytest的mark标记
2. yaml中支持测试用例级别标记，报告中展示、筛选
