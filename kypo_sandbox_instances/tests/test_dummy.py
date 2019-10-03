import pytest


class TestDummy:

    @pytest.mark.tryfirst
    def test_always_true(self):
        assert True
