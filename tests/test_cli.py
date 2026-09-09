"""Unit tests for the CLI interface (cli.py)."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from cli import (
    _cmd_add,
    _cmd_add_rule,
    _cmd_check,
    _cmd_list,
    _cmd_list_rules,
    _cmd_pause,
    _cmd_remove,
    _cmd_resume,
    build_parser,
)
from database import Database, Product


def test_build_parser_arguments():
    parser = build_parser()
    # Test add command
    args_add = parser.parse_args(["add", "--url", "https://amazon.in/dp/123", "--target-price", "1500"])
    assert args_add.command == "add"
    assert args_add.url == "https://amazon.in/dp/123"
    assert args_add.target_price == 1500.0

    # Test list command
    args_list = parser.parse_args(["list", "--all"])
    assert args_list.command == "list"
    assert args_list.all is True

    # Test remove command
    args_rem = parser.parse_args(["remove", "--id", "5"])
    assert args_rem.command == "remove"
    assert args_rem.id == 5

    # Test pause & resume
    args_pause = parser.parse_args(["pause", "--id", "3"])
    assert args_pause.command == "pause"
    assert args_pause.id == 3

    # Test add-rule
    args_rule = parser.parse_args(["add-rule", "--name", "Custom Deal", "--query", "sony headphones", "--min-discount", "50"])
    assert args_rule.command == "add-rule"
    assert args_rule.name == "Custom Deal"
    assert args_rule.query == "sony headphones"
    assert args_rule.min_discount == 50.0

    # Test list-rules
    args_lr = parser.parse_args(["list-rules"])
    assert args_lr.command == "list-rules"

    # Test scan-deals
    args_sd = parser.parse_args(["scan-deals", "--collection", "g-shock", "--min-discount", "60"])
    assert args_sd.command == "scan-deals"
    assert args_sd.collection == "g-shock"
    assert args_sd.min_discount == 60.0


@pytest.mark.asyncio
async def test_cmd_add_validation():
    parser = build_parser()
    # Missing both target-price and percent-drop -> error code 2
    args = parser.parse_args(["add", "--url", "https://amazon.in/dp/123"])
    ret = await _cmd_add(args)
    assert ret == 2

    # Invalid URL scheme -> error code 2
    args_bad_url = parser.parse_args(["add", "--url", "ftp://amazon.in/dp/123", "--target-price", "1000"])
    ret_bad = await _cmd_add(args_bad_url)
    assert ret_bad == 2


@pytest.mark.asyncio
async def test_cmd_list_output(capsys):
    parser = build_parser()
    args = parser.parse_args(["list"])

    with patch("database.Database.initialize", new_callable=AsyncMock), \
         patch("database.Database.close", new_callable=AsyncMock), \
         patch("database.Database.get_products", new_callable=AsyncMock) as mock_gp:
        mock_gp.return_value = [
            Product(
                id=1,
                url="https://amazon.in/dp/B001",
                platform="amazon",
                title="Casio G-Shock GBD-300",
                initial_price=3995.0,
                current_price=3995.0,
                target_price=3500.0,
                percentage_drop_target=None,
                last_checked=None,
                is_active=True,
                last_notified_price=None,
            )
        ]
        ret = await _cmd_list(args)
        assert ret == 0
        captured = capsys.readouterr()
        assert "Casio G-Shock GBD-300" in captured.out
        assert "INR 3500" in captured.out


@pytest.mark.asyncio
async def test_cmd_remove_and_pause_resume():
    parser = build_parser()

    with patch("database.Database.initialize", new_callable=AsyncMock), \
         patch("database.Database.close", new_callable=AsyncMock), \
         patch("database.Database.get_product", new_callable=AsyncMock) as mock_gp, \
         patch("database.Database.remove_product", new_callable=AsyncMock) as mock_rem, \
         patch("database.Database.set_active", new_callable=AsyncMock) as mock_sa:

        prod = Product(id=1, url="https://amazon.in/p", platform="amazon", title="Test", initial_price=100, current_price=100, target_price=80, percentage_drop_target=None, last_checked=None, is_active=True, last_notified_price=None)
        mock_gp.return_value = prod

        # Remove
        args_rem = parser.parse_args(["remove", "--id", "1"])
        ret_rem = await _cmd_remove(args_rem)
        assert ret_rem == 0
        mock_rem.assert_called_with(1)

        # Pause
        args_pause = parser.parse_args(["pause", "--id", "1"])
        ret_pause = await _cmd_pause(args_pause)
        assert ret_pause == 0
        mock_sa.assert_called_with(1, False)

        # Resume
        args_res = parser.parse_args(["resume", "--id", "1"])
        ret_res = await _cmd_resume(args_res)
        assert ret_res == 0
        mock_sa.assert_called_with(1, True)


@pytest.mark.asyncio
async def test_cmd_add_rule_and_list_rules(capsys):
    parser = build_parser()

    with patch("database.Database.initialize", new_callable=AsyncMock), \
         patch("database.Database.close", new_callable=AsyncMock), \
         patch("database.Database.add_custom_rule", new_callable=AsyncMock) as mock_ar, \
         patch("database.Database.get_custom_rules", new_callable=AsyncMock) as mock_gcr:

        mock_ar.return_value = 10
        mock_gcr.return_value = [{"id": 10, "name": "Test Rule", "query": "test query", "category": "Tech", "min_discount": 70.0, "is_active": 1}]

        # Add rule
        args_add = parser.parse_args(["add-rule", "--name", "Test Rule", "--query", "test query"])
        ret_add = await _cmd_add_rule(args_add)
        assert ret_add == 0
        mock_ar.assert_called_once()

        # List rules
        args_list = parser.parse_args(["list-rules"])
        ret_list = await _cmd_list_rules(args_list)
        assert ret_list == 0
        captured = capsys.readouterr()
        assert "Pre-configured Master Radar Rules" in captured.out
        assert "Custom User Sniper Rules" in captured.out
        assert "Test Rule" in captured.out
