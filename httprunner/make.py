import os
import shutil
import string
import subprocess
import sys
from typing import Dict, List, Optional, Set, Text, Tuple

import jinja2
from loguru import logger

from httprunner import __version__, exceptions
from httprunner.compat import (
    convert_variables,
    ensure_path_sep,
    ensure_testcase_v4,
    ensure_testcase_v4_api,
)
from httprunner.loader import (
    convert_relative_project_root_dir,
    load_folder_files,
    load_project_meta,
    load_test_file,
    load_testcase,
)
from httprunner.response import uniform_validator
from httprunner.utils import is_support_multiprocessing

""" cache converted pytest files, avoid duplicate making
"""
pytest_files_made_cache_mapping: Dict[Text, Text] = {}

""" save generated pytest files to run, except referenced testcase
"""
pytest_files_run_set: Set = set()

__TEMPLATE__ = jinja2.Template(
"""# NOTE: Generated By HttpRunner {{ version }}
# FROM: {{ testcase_path }}

{% if parameters or skip or marks %}
import pytest
{% endif %}
from httprunner import HttpRunner, Config, Step, RunRequest

{% if parameters %}
from httprunner import Parameters
{% endif %}

{% if reference_testcase %}
from httprunner import RunTestCase
{% endif %}

{% for import_str in imports_list %}
{{ import_str }}
{% endfor %}

class {{ class_name }}(HttpRunner):

    {% if skip %}
    @pytest.mark.skip(reason="{{ skip }}")
    {% endif %}

    {% if marks %}
    {% for mark in marks %}
    @pytest.mark.{{ mark }}
    {% endfor %}
    {% endif %}

    {% if parameters %}
    @pytest.mark.parametrize("param", Parameters({{ parameters }}))
    def test_start(self, param):
        super().test_start(param)
    {% else %}
    def test_start(self):
        super().test_start()
    {% endif %}

    config = {{ config_chain_style }}

    teststeps = [
        {% for step_chain_style in teststeps_chain_style %}
            {{ step_chain_style }},
        {% endfor %}
    ]

if __name__ == "__main__":
    {{ class_name }}().test_start()

"""
)


def __ensure_absolute(path: Text) -> Text:
    if path.startswith("./"):
        # Linux/Darwin, hrun ./test.yml
        path = path[2:]
    elif path.startswith(".\\"):
        # Windows, hrun .\\test.yml
        path = path[3:]

    path = ensure_path_sep(path)
    project_meta = load_project_meta(path)

    if os.path.isabs(path):
        absolute_path = path
    else:
        absolute_path = os.path.join(project_meta.RootDir, path)

    if not os.path.isfile(absolute_path):
        logger.error(f"Invalid testcase file path: {absolute_path}")
        sys.exit(1)

    return absolute_path


def ensure_file_abs_path_valid(file_abs_path: Text) -> Text:
    """ensure file path valid for pytest, handle cases when directory name includes dot/hyphen/space

    Args:
        file_abs_path: absolute file path

    Returns:
        ensured valid absolute file path

    """
    project_meta = load_project_meta(file_abs_path)
    raw_abs_file_name, file_suffix = os.path.splitext(file_abs_path)
    file_suffix = file_suffix.lower()

    raw_file_relative_name = convert_relative_project_root_dir(raw_abs_file_name)
    if raw_file_relative_name == "":
        return file_abs_path

    path_names = []
    for name in raw_file_relative_name.rstrip(os.sep).split(os.sep):

        if name[0] in string.digits:
            # ensure file name not startswith digit
            # 19 => T19, 2C => T2C
            name = f"T{name}"

        if name.startswith("."):
            # avoid ".csv" been converted to "_csv"
            pass
        else:
            # handle cases when directory name includes dot/hyphen/space
            name = name.replace(" ", "_").replace(".", "_").replace("-", "_")

        path_names.append(name)

    new_file_path = os.path.join(
        project_meta.RootDir, f"{os.sep.join(path_names)}{file_suffix}"
    )
    return new_file_path


def __ensure_testcase_module(path: Text):
    """ensure pytest files are in python module, generate __init__.py on demand"""
    init_file = os.path.join(os.path.dirname(path), "__init__.py")
    if os.path.isfile(init_file):
        return

    with open(init_file, "w", encoding="utf-8") as f:
        f.write("# NOTICE: Generated By HttpRunner. DO NOT EDIT!\n")


def convert_testcase_path(testcase_abs_path: Text) -> Tuple[Text, Text]:
    """convert single YAML/JSON testcase path to python file"""
    testcase_new_path = ensure_file_abs_path_valid(testcase_abs_path)

    dir_path = os.path.dirname(testcase_new_path)
    file_name, _ = os.path.splitext(os.path.basename(testcase_new_path))
    testcase_python_abs_path = os.path.join(dir_path, f"{file_name}_test.py")

    # convert title case, e.g. request_with_variables => RequestWithVariables
    name_in_title_case = file_name.title().replace("_", "")

    return testcase_python_abs_path, name_in_title_case


def format_pytest_with_black(*python_paths: Text):
    logger.info("format pytest cases with black ...")
    try:
        if is_support_multiprocessing() or len(python_paths) <= 1:
            subprocess.run(["black", *python_paths])
        else:
            logger.warning(
                "this system does not support multiprocessing well, format files one by one ..."
            )
            [subprocess.run(["black", path]) for path in python_paths]
    except subprocess.CalledProcessError as ex:
        logger.error(ex)
        sys.exit(1)
    except OSError:
        err_msg = """
missing dependency tool: black
install black manually and try again:
$ pip install black
"""
        logger.error(err_msg)
        sys.exit(1)


def make_config_chain_style(config: Dict) -> Text:
    config_chain_style = f'Config("{config["name"]}")'

    if config["variables"]:
        variables = config["variables"]
        config_chain_style += f".variables(**{variables})"

    if "base_url" in config:
        config_chain_style += f'.base_url("{config["base_url"]}")'

    if "verify" in config:
        config_chain_style += f'.verify({config["verify"]})'

    if "export" in config:
        config_chain_style += f'.export(*{config["export"]})'

    return config_chain_style


def make_config_skip(config: Dict) -> Optional[Text]:
    """处理config中的skip字段，返回skip的reason"""
    if config.get("skip") is None:
        return None
    reason: Text = config.get("skip").get("reason")
    return reason


def make_config_marks(config: Dict) -> Optional[Text]:
    """处理config中的marks字段，返回marks的列表"""
    if config.get("marks") is None:
        return None
    marks: List[str] = config["marks"]
    return marks


def make_request_chain_style(request: Dict) -> Text:
    method = request["method"].lower()
    url = request["url"]
    request_chain_style = f'.{method}("{url}")'

    if "params" in request:
        params = request["params"]
        request_chain_style += f".with_params(**{params})"

    if "headers" in request:
        headers = request["headers"]
        request_chain_style += f".with_headers(**{headers})"

    if "cookies" in request:
        cookies = request["cookies"]
        request_chain_style += f".with_cookies(**{cookies})"

    if "data" in request:
        data = request["data"]
        if isinstance(data, Text):
            data = f'"{data}"'
        request_chain_style += f".with_data({data})"

    if "json" in request:
        req_json = request["json"]
        if isinstance(req_json, Text):
            req_json = f'"{req_json}"'
        request_chain_style += f".with_json({req_json})"

    if "timeout" in request:
        timeout = request["timeout"]
        request_chain_style += f".set_timeout({timeout})"

    if "verify" in request:
        verify = request["verify"]
        request_chain_style += f".set_verify({verify})"

    if "allow_redirects" in request:
        allow_redirects = request["allow_redirects"]
        request_chain_style += f".set_allow_redirects({allow_redirects})"

    if "upload" in request:
        upload = request["upload"]
        request_chain_style += f".upload(**{upload})"

    return request_chain_style


def make_teststep_chain_style(teststep: Dict) -> Text:
    if teststep.get("request"):
        step_info = f'RunRequest("{teststep["name"]}")'
    elif teststep.get("testcase"):
        step_info = f'RunTestCase("{teststep["name"]}")'
    else:
        raise exceptions.TestCaseFormatError(f"Invalid teststep: {teststep}")

    if "variables" in teststep:
        variables = teststep["variables"]
        step_info += f".with_variables(**{variables})"

    if "setup_hooks" in teststep:
        setup_hooks = teststep["setup_hooks"]
        for hook in setup_hooks:
            if isinstance(hook, Text):
                step_info += f'.setup_hook("{hook}")'
            elif isinstance(hook, Dict) and len(hook) == 1:
                assign_var_name, hook_content = list(hook.items())[0]
                step_info += f'.setup_hook("{hook_content}", "{assign_var_name}")'
            else:
                raise exceptions.TestCaseFormatError(f"Invalid setup hook: {hook}")

    if teststep.get("request"):
        step_info += make_request_chain_style(teststep["request"])
    elif teststep.get("testcase"):
        testcase = teststep["testcase"]
        call_ref_testcase = f".call({testcase})"
        step_info += call_ref_testcase

    if "teardown_hooks" in teststep:
        teardown_hooks = teststep["teardown_hooks"]
        for hook in teardown_hooks:
            if isinstance(hook, Text):
                step_info += f'.teardown_hook("{hook}")'
            elif isinstance(hook, Dict) and len(hook) == 1:
                assign_var_name, hook_content = list(hook.items())[0]
                step_info += f'.teardown_hook("{hook_content}", "{assign_var_name}")'
            else:
                raise exceptions.TestCaseFormatError(f"Invalid teardown hook: {hook}")

    if "extract" in teststep:
        # request step
        step_info += ".extract()"
        for extract_name, extract_path in teststep["extract"].items():
            if extract_path.startswith("regex:"):
                # 处理正则表达式提取
                regex_pattern = extract_path[6:]  # 去掉"regex:"前缀
                # 需要特殊处理下字符串字面量作为参数时的情况，避免函数调用报错
                regex_pattern = regex_pattern.replace("\\", "\\\\").replace("'", "\\'")
                step_info += f""".with_regex('{regex_pattern}', '{extract_name}')"""
            else:
                # 处理JMESPath提取
                step_info += f""".with_jmespath('{extract_path}', '{extract_name}')"""

    if "export" in teststep:
        # reference testcase step
        export: List[Text] = teststep["export"]
        step_info += f".export(*{export})"

    if "validate" in teststep:
        step_info += ".validate()"

        for v in teststep["validate"]:
            validator = uniform_validator(v)
            assert_method = validator["assert"]
            check = validator["check"]
            if '"' in check:
                # e.g. body."user-agent" => 'body."user-agent"'
                check = f"'{check}'"
            else:
                check = f'"{check}"'
            expect = validator["expect"]
            if isinstance(expect, Text):
                expect = f'"{expect}"'

            message = validator["message"]
            if message:
                step_info += f".assert_{assert_method}({check}, {expect}, '{message}')"
            else:
                step_info += f".assert_{assert_method}({check}, {expect})"

    return f"Step({step_info})"


def make_testcase(testcase: Dict, dir_path: Text = None) -> Text:
    """将字典格式的测试用例转换为pytest文件"""
    # ensure compatibility with testcase format v2/v3
    testcase = ensure_testcase_v4(testcase)

    # validate testcase format
    load_testcase(testcase)

    testcase_abs_path = __ensure_absolute(testcase["config"]["path"])
    logger.info(f"start to make testcase: {testcase_abs_path}")

    testcase_python_abs_path, testcase_cls_name = convert_testcase_path(
        testcase_abs_path
    )
    if dir_path:
        testcase_python_abs_path = os.path.join(
            dir_path, os.path.basename(testcase_python_abs_path)
        )

    global pytest_files_made_cache_mapping
    if testcase_python_abs_path in pytest_files_made_cache_mapping:
        return testcase_python_abs_path

    config = testcase["config"]
    config["path"] = testcase_abs_path
    config["variables"] = convert_variables(
        config.get("variables", {}), testcase_abs_path
    )

    # prepare reference testcase
    imports_list = []
    teststeps = testcase["teststeps"]
    for teststep in teststeps:
        if not teststep.get("testcase"):
            continue

        # make ref testcase pytest file
        ref_testcase_path = __ensure_absolute(teststep["testcase"])
        test_content = load_test_file(ref_testcase_path)

        if not isinstance(test_content, Dict):
            raise exceptions.TestCaseFormatError(f"Invalid teststep: {teststep}")

        # api in v2/v3 format, convert to v4 testcase
        if "request" in test_content and "name" in test_content:
            test_content = ensure_testcase_v4_api(test_content)

        test_content.setdefault("config", {})["path"] = ref_testcase_path
        ref_testcase_python_abs_path = make_testcase(test_content)

        # override testcase export
        ref_testcase_export: List = test_content["config"].get("export", [])
        if ref_testcase_export:
            step_export: List = teststep.setdefault("export", [])
            step_export.extend(ref_testcase_export)
            teststep["export"] = list(set(step_export))

        # prepare ref testcase class name
        ref_testcase_cls_name = pytest_files_made_cache_mapping[
            ref_testcase_python_abs_path
        ]
        teststep["testcase"] = ref_testcase_cls_name

        # prepare import ref testcase
        ref_testcase_python_relative_path = convert_relative_project_root_dir(
            ref_testcase_python_abs_path
        )
        ref_module_name, _ = os.path.splitext(ref_testcase_python_relative_path)
        ref_module_name = ref_module_name.replace(os.sep, ".")
        import_expr = f"from {ref_module_name} import TestCase{ref_testcase_cls_name} as {ref_testcase_cls_name}"
        if import_expr not in imports_list:
            imports_list.append(import_expr)

    testcase_path = convert_relative_project_root_dir(testcase_abs_path)
    # current file compared to ProjectRootDir
    diff_levels = len(testcase_path.split(os.sep))
    if len(imports_list) > 0 and diff_levels > 0:
        parent = ".parent" * diff_levels
        import_deps = f"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__){parent}))
"""
        imports_list.insert(0, import_deps)

    data = {
        "version": __version__,
        "testcase_path": testcase_path,
        "class_name": f"TestCase{testcase_cls_name}",
        "imports_list": imports_list,
        "config_chain_style": make_config_chain_style(config),
        "skip": make_config_skip(config),
        "marks": make_config_marks(config),
        "parameters": config.get("parameters"),
        "reference_testcase": any(step.get("testcase") for step in teststeps),
        "teststeps_chain_style": [
            make_teststep_chain_style(step) for step in teststeps
        ],
    }
    content = __TEMPLATE__.render(data)

    # ensure new file's directory exists
    dir_path = os.path.dirname(testcase_python_abs_path)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    with open(testcase_python_abs_path, "w", encoding="utf-8") as f:
        f.write(content)

    pytest_files_made_cache_mapping[testcase_python_abs_path] = testcase_cls_name
    __ensure_testcase_module(testcase_python_abs_path)

    logger.info(f"generated testcase: {testcase_python_abs_path}")

    return testcase_python_abs_path


def __make(tests_path: Text, output_dir: Text = None):
    """make testcase(s) with testcase/folder absolute path
        generated pytest file path will be cached in pytest_files_made_cache_mapping

    Args:
        tests_path: should be in absolute path
        output_dir: directory to save generated pytest files

    """
    logger.info(f"make path: {tests_path}")
    test_files = []
    if os.path.isdir(tests_path):
        files_list = load_folder_files(tests_path)
        test_files.extend(files_list)
    elif os.path.isfile(tests_path):
        test_files.append(tests_path)
    else:
        raise exceptions.TestcaseNotFound(f"Invalid tests path: {tests_path}")

    for test_file in test_files:
        if test_file.lower().endswith("_test.py"):
            pytest_files_run_set.add(test_file)
            continue

        try:
            # 解析测试用例文件，转换为字典
            test_content = load_test_file(test_file)
        except (exceptions.FileNotFound, exceptions.FileFormatError) as ex:
            logger.warning(f"Invalid test file: {test_file}\n{type(ex).__name__}: {ex}")
            continue

        if not isinstance(test_content, Dict):
            logger.warning(
                f"Invalid test file: {test_file}\n"
                f"reason: test content not in dict format."
            )
            continue

        # api in v2/v3 format, convert to v4 testcase
        if "request" in test_content and "name" in test_content:
            test_content = ensure_testcase_v4_api(test_content)

        if "config" not in test_content:
            logger.warning(
                f"Invalid testcase file: {test_file}\nreason: missing config part."
            )
            continue
        elif not isinstance(test_content["config"], Dict):
            logger.warning(
                f"Invalid testcase file: {test_file}\n"
                f"reason: config should be dict type, got {test_content['config']}"
            )
            continue

        # ensure path absolute
        test_content.setdefault("config", {})["path"] = test_file

        # invalid format
        if "teststeps" not in test_content:
            logger.warning(f"Invalid testcase file: {test_file}")

        # testcase
        try:
            testcase_pytest_path = make_testcase(test_content, output_dir)
            pytest_files_run_set.add(testcase_pytest_path)
        except exceptions.TestCaseFormatError as ex:
            logger.warning(
                f"Invalid testcase file: {test_file}\n{type(ex).__name__}: {ex}"
            )
            continue



def main_make(tests_paths: List[Text], output_dir: Text = None) -> List[Text]:
    if not tests_paths:
        return []

    # 确保输出目录存在
    if output_dir:
        output_dir = ensure_path_sep(output_dir)
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.getcwd(), output_dir)

        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
            os.makedirs(output_dir)

    for tests_path in tests_paths:
        tests_path = ensure_path_sep(tests_path)
        if not os.path.isabs(tests_path):
            tests_path = os.path.join(os.getcwd(), tests_path)

        try:
            __make(tests_path, output_dir)
        except exceptions.MyBaseError as ex:
            logger.error(ex)
            sys.exit(1)

    # format pytest files
    pytest_files_format_list = pytest_files_made_cache_mapping.keys()
    format_pytest_with_black(*pytest_files_format_list)

    return list(pytest_files_run_set)


def init_make_parser(subparsers):
    """make testcases: parse command line options and run commands."""
    parser = subparsers.add_parser(
        "make",
        help="Convert YAML/JSON testcases to pytest cases.",
    )
    parser.add_argument(
        "testcase_path", nargs="*", help="Specify YAML/JSON testcase file/folder path"
    )
    parser.add_argument(
        "--output-dir", "-o",
        dest="output_dir",
        help="Specify output directory for generated pytest files"
    )

    return parser
