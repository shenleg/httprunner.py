# 二次开发改动记录
1. `v4.3.5.1` `httprunner make` 增加一个命令行参数 `--output-dir`，可以指定输出的 pytest 测试文件的目录
2. `v4.3.5.2` 支持不同环境的 .env 文件，使用时需要手动设置环境变量
    * 比如设置 `ENV=test`，则对应 `config/.env.test` 文件