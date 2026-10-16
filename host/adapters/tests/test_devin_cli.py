from roam_approve_adapters.devin_cli import DevinCliAdapter, summarize, to_ascii


def parse(event):
    return DevinCliAdapter().parse(event)


def test_parse_exec_command() -> None:
    req = parse(
        {
            "tool_name": "exec",
            "session_id": "sess-1",
            "tool_input": {"command": "ls -la"},
        }
    )
    assert req is not None
    assert req.agent == "devin-cli"
    assert req.title == "exec"
    assert req.session_id == "sess-1"
    assert req.lines == ["ls -la"]


def test_parse_write_file_path() -> None:
    req = parse(
        {
            "tool_name": "write",
            "session_id": "s2",
            "tool_input": {"file_path": "/tmp/x.txt", "content": "secret body"},
        }
    )
    assert req is not None
    assert req.title == "write"
    assert req.lines == ["/tmp/x.txt"]


def test_parse_edit_file_path() -> None:
    req = parse(
        {
            "tool_name": "edit",
            "session_id": "s3",
            "tool_input": {"file_path": "/a/b.py"},
        }
    )
    assert req is not None
    assert req.lines == ["/a/b.py"]


def test_parse_empty_command_falls_back_to_file_path() -> None:
    req = parse(
        {
            "tool_name": "exec",
            "session_id": "s",
            "tool_input": {"command": "", "file_path": "/tmp/a.txt"},
        }
    )
    assert req is not None
    assert req.lines == ["/tmp/a.txt"]


def test_parse_command_takes_precedence_over_file_path() -> None:
    req = parse(
        {
            "tool_name": "exec",
            "session_id": "s4",
            "tool_input": {"command": "echo hi", "file_path": "/tmp/x"},
        }
    )
    assert req is not None
    assert req.lines == ["echo hi"]


def test_parse_missing_tool_name() -> None:
    assert parse({"session_id": "s"}) is None
    assert parse({"tool_name": ""}) is None
    assert parse({"tool_name": 1}) is None


def test_parse_non_dict() -> None:
    assert parse("exec") is None
    assert parse(None) is None
    assert parse([1]) is None


def test_parse_missing_session_id() -> None:
    req = parse({"tool_name": "exec", "tool_input": {"command": "x"}})
    assert req is not None
    assert req.session_id == "unknown"


def test_parse_tool_input_without_command_or_file_path() -> None:
    req = parse({"tool_name": "exec", "tool_input": {"other": 1}})
    assert req is not None
    assert req.lines == []


def test_multiline_command() -> None:
    req = parse(
        {
            "tool_name": "exec",
            "session_id": "s",
            "tool_input": {"command": "echo one\necho two"},
        }
    )
    assert req is not None
    assert req.lines == ["echo one", "echo two"]


def test_long_command_truncation() -> None:
    long_cmd = "x" * 200
    lines = summarize(long_cmd)
    assert len(lines) == 6
    assert all(len(line) <= 20 for line in lines)
    assert lines[-1].endswith("...")


def test_multiline_overflow_keeps_six_with_ellipsis() -> None:
    text = "\n".join(f"line{i:03d}" for i in range(20))
    lines = summarize(text)
    assert len(lines) == 6
    assert all(len(line) <= 20 for line in lines)
    assert lines[-1].endswith("...")


def test_summarize_empty_lines_dropped_and_tabs() -> None:
    lines = summarize("a\n\n\tb\r\nc")
    assert lines == ["a", " b", "c"]


def test_marker_is_never_split_across_lines() -> None:
    lines = summarize('git commit -m "ログイン処理を修正"')
    assert lines == ['git commit -m "', '<JA:9>"']
    assert all(line.isascii() for line in lines)


def test_japanese_file_path() -> None:
    req = parse(
        {
            "tool_name": "write",
            "session_id": "s",
            "tool_input": {"file_path": "docs/設計メモ.md"},
        }
    )
    assert req is not None
    assert req.lines == ["docs/<JA:4>.md"]


def test_multiple_runs_and_full_width_space_are_japanese() -> None:
    assert to_ascii("echo 完了　です && ls 結果") == "echo <JA:5> && ls <JA:2>"


def test_full_width_ascii_lookalike_is_flagged_as_unknown() -> None:
    assert to_ascii("ｒｍ -rf /") == "<?:2> -rf /"


def test_emoji_and_mixed_runs_are_flagged_as_unknown() -> None:
    assert to_ascii("echo 👨‍👩‍👧") == "echo <?:5>"
    assert to_ascii("echo 完了✅") == "echo <?:3>"


def test_nfd_text_is_normalized_before_counting() -> None:
    decomposed = "\u304b\u3099"
    assert to_ascii(decomposed) == "<JA:1>"


def test_control_characters_become_spaces() -> None:
    assert to_ascii("a\x1bb\x7fc") == "a b c"


def test_title_is_ascii_safe() -> None:
    req = parse({"tool_name": "実行", "tool_input": {"command": "ls"}})
    assert req is not None
    assert req.title == "<JA:2>"


def test_overflow_ellipsis_does_not_cut_marker() -> None:
    text = "\n".join(["x"] * 5 + ["a" * 12 + "ログイン処理を修正です", "y"])
    lines = summarize(text)
    assert len(lines) == 6
    assert lines[-1] == "a" * 12 + "..."
    assert all(len(line) <= 20 and line.isascii() for line in lines)


def test_render_approved() -> None:
    out, code = DevinCliAdapter().render("approved")
    assert out == '{"decision":"approve"}'
    assert code == 0


def test_render_rejected() -> None:
    out, code = DevinCliAdapter().render("rejected")
    assert out == '{"decision":"block","reason":"Rejected on M5StickC"}'
    assert code == 0


def test_render_expired_pending_unreachable() -> None:
    adapter = DevinCliAdapter()
    for result in ("expired", "pending", "unreachable"):
        out, code = adapter.render(result)
        assert out == ""
        assert code == 0
