__version__ = "v4.3.5"
__description__ = "One-stop solution for HTTP(S) testing."

import os

from httprunner.config import Config
from httprunner.loader import load_dot_env_file
from httprunner.parser import parse_parameters as Parameters
from httprunner.runner import HttpRunner
from httprunner.step import Step
from httprunner.step_request import RunRequest
from httprunner.step_sql_request import (
    RunSqlRequest,
    StepSqlRequestExtraction,
    StepSqlRequestValidation,
)
from httprunner.step_testcase import RunTestCase
from httprunner.step_thrift_request import (
    RunThriftRequest,
    StepThriftRequestExtraction,
    StepThriftRequestValidation,
)
from httprunner.utils import init_stdout_logger


__all__ = [
    "__version__",
    "__description__",
    "HttpRunner",
    "Config",
    "Step",
    "RunRequest",
    "RunSqlRequest",
    "StepSqlRequestValidation",
    "StepSqlRequestExtraction",
    "RunTestCase",
    "Parameters",
    "RunThriftRequest",
    "StepThriftRequestValidation",
    "StepThriftRequestExtraction",
]


# 加载环境变量文件，此时还未初始化日志记录器，所以有日志
base_path = os.getcwd()
env_file = ".env" if os.getenv("ENV") is None else ".env.{}".format(os.getenv("ENV"))
dot_env_path = os.path.join(base_path, "config", env_file)
dot_env = load_dot_env_file(dot_env_path)
if dot_env:
    os.environ["ENV_LOADED"] = "True"

# 初始化日志记录器
init_stdout_logger()
