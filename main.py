import pytest

from httprunner.make import main_make


def test_make():
    path = ["test_case_yaml"]
    output_dir = "test_case_pytest"
    main_make(path, output_dir)

if __name__=="__main__":
    test_make()

    # 跳过测试
    pytest.main(['-vs','test_case_pytest'])

    # 标记测试
    # pytest.main(['-vs','test_case_pytest', '-m', 'smoke'])