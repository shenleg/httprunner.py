import pytest

if __name__=="__main__":
    pytest.main(['-vs','httprunner\make_test.py::TestMake::test_make_testcase_with_outputdir'])
    # pytest.main(['-vs','test_case_pytest'])