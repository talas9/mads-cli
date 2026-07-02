"""Offline/CI-safe tests for mads-cli's organic-content feature (posts/comments/page
update). Mirrors tests/test_mads.py's patterns:
  * simple single-call ops mock `graph_request`/`graph_request_with_page_token` directly
    (see TestGetPageAccessToken in test_mads.py)
  * the 2-step Instagram publish flow uses a call-count/path-indexed fake mock
    (see TestMutatePartialProgress in test_mads.py), including a partial-failure case
    that must surface the orphaned `creation_id` rather than lose it
  * `--dry-run` must make zero API calls
  * mutually-exclusive-flag validation errors

No real network calls — every HTTP-touching test mocks either `mads_lib.posts`/
`mads_lib.comments`'s `graph_request_with_page_token`/`graph_request` references directly,
matching the codebase's established per-module mocking convention.
"""
import json

import pytest
from click.testing import CliRunner

import mads_lib.comments
import mads_lib.posts
from mads_lib.cli import cli
from mads_lib.output import EXIT_CODES

runner = CliRunner()


# ─────────────────────────────────────────────────────────────────────────
# posts.py — simple single-call library functions
# ─────────────────────────────────────────────────────────────────────────


class TestCreatePagePost:
    def test_requires_at_least_one_of_message_link(self):
        with pytest.raises(ValueError, match="at least one of message/link"):
            mads_lib.posts.create_page_post("106391075531104")

    def test_success_posts_message_and_link_via_page_token_helper(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append((page_id, method, path, kwargs.get("json_body")))
            return {"id": "postid_1"}

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake)

        result = mads_lib.posts.create_page_post(
            "106391075531104", message="hello world", link="https://talas.ae/?branch=qz3",
        )
        assert result == {"id": "postid_1"}
        assert calls == [(
            "106391075531104", "POST", "106391075531104/feed",
            {"message": "hello world", "link": "https://talas.ae/?branch=qz3"},
        )]

    def test_schedule_time_too_soon_raises_before_any_call(self, monkeypatch):
        import time

        def fail_if_called(*a, **k):
            raise AssertionError("graph_request_with_page_token must not be called")

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fail_if_called)

        with pytest.raises(ValueError, match="too soon"):
            mads_lib.posts.create_page_post(
                "106391075531104", message="hi", scheduled_publish_time=int(time.time()) + 60,
            )

    def test_schedule_time_too_far_out_raises_before_any_call(self, monkeypatch):
        import time

        def fail_if_called(*a, **k):
            raise AssertionError("graph_request_with_page_token must not be called")

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fail_if_called)

        with pytest.raises(ValueError, match="too far out"):
            mads_lib.posts.create_page_post(
                "106391075531104", message="hi",
                scheduled_publish_time=int(time.time()) + 40 * 24 * 60 * 60,
            )

    def test_valid_schedule_time_within_feed_window_sends_scheduled_fields(self, monkeypatch):
        import time

        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append(kwargs.get("json_body"))
            return {"id": "postid_2"}

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake)

        ts = int(time.time()) + 3600  # 1 hour out, well within 10min-30day
        mads_lib.posts.create_page_post("106391075531104", message="hi", scheduled_publish_time=ts)
        assert calls[0]["published"] is False
        assert calls[0]["scheduled_publish_time"] == ts


class TestCreatePageVideoPostSchedulingWindow:
    """Video posts get a much wider (~6 month) scheduling window than feed posts —
    confirm the two windows are genuinely independent, not sharing one constant."""

    def test_video_window_allows_a_schedule_time_that_would_fail_for_a_feed_post(self, monkeypatch):
        import time

        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append(kwargs.get("json_body"))
            return {"id": "video_1"}

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake)

        ts = int(time.time()) + 60 * 24 * 60 * 60  # 60 days out — invalid for feed, valid for video
        with pytest.raises(ValueError, match="too far out"):
            mads_lib.posts.create_page_post("106391075531104", message="hi", scheduled_publish_time=ts)

        mads_lib.posts.create_page_video_post(
            "106391075531104", "https://example.com/video.mp4", message="hi", scheduled_publish_time=ts,
        )
        assert calls[0]["scheduled_publish_time"] == ts
        assert calls[0]["description"] == "hi"


class TestCreatePagePhotoPost:
    def test_url_input_sends_url_param_via_json_body(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append((path, kwargs.get("json_body"), kwargs.get("files")))
            return {"id": "photo_1"}

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake)

        mads_lib.posts.create_page_photo_post("106391075531104", "https://example.com/a.jpg", message="caption")
        path, json_body, files = calls[0]
        assert path == "106391075531104/photos"
        assert json_body == {"message": "caption", "url": "https://example.com/a.jpg"}
        assert files is None

    def test_local_path_not_found_raises_value_error(self):
        with pytest.raises(ValueError, match="local file not found"):
            mads_lib.posts.create_page_photo_post("106391075531104", "/nonexistent/path.jpg")


class TestDeletePost:
    def test_facebook_platform_calls_delete(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append((page_id, method, path))
            return {"success": True}

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake)

        result = mads_lib.posts.delete_post("106391075531104_999", "106391075531104")
        assert result == {"success": True}
        assert calls == [("106391075531104", "DELETE", "106391075531104_999")]

    def test_instagram_platform_refuses_with_clear_error(self):
        with pytest.raises(ValueError, match="Instagram media deletion is not a documented"):
            mads_lib.posts.delete_post("179999999", "106391075531104", platform="instagram")

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError, match="platform must be"):
            mads_lib.posts.delete_post("1", "2", platform="bogus")


# ─────────────────────────────────────────────────────────────────────────
# posts.py — Instagram 2-step publish flow (call-count/path-indexed fake)
# ─────────────────────────────────────────────────────────────────────────


class TestIgContainerAndPublish:
    def test_create_ig_container_requires_exactly_one_of_image_video_url(self):
        with pytest.raises(ValueError, match="pass exactly one of"):
            mads_lib.posts.create_ig_container("ig_1", page_id="page_1")
        with pytest.raises(ValueError, match="pass exactly one of"):
            mads_lib.posts.create_ig_container(
                "ig_1", page_id="page_1",
                image_url="https://example.com/a.jpg", video_url="https://example.com/a.mp4",
            )

    def test_create_ig_container_rejects_invalid_media_type(self):
        with pytest.raises(ValueError, match="media_type must be one of"):
            mads_lib.posts.create_ig_container(
                "ig_1", page_id="page_1", image_url="https://example.com/a.jpg", media_type="BOGUS",
            )

    def test_two_step_flow_success(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append(path)
            if path.endswith("/media"):
                return {"id": "container_123"}
            if path.endswith("/media_publish"):
                return {"id": "published_456"}
            raise AssertionError(f"unexpected path {path}")

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake)

        container = mads_lib.posts.create_ig_container(
            "ig_1", caption="hi", image_url="https://example.com/a.jpg", page_id="page_1",
        )
        assert container == {"id": "container_123"}
        published = mads_lib.posts.publish_ig_container("ig_1", "container_123", page_id="page_1")
        assert published == {"id": "published_456"}
        assert calls == ["ig_1/media", "ig_1/media_publish"]

    def test_page_id_auto_resolved_via_me_accounts_when_omitted(self, monkeypatch):
        monkeypatch.setattr(mads_lib.posts, "get_access_token", lambda: "user-token")

        def fake_graph_request(method, path, **kwargs):
            assert path == "me/accounts"
            return {"data": [
                {"id": "page_1", "name": "Talas", "instagram_business_account": {"id": "ig_1"}},
                {"id": "page_2", "name": "Other"},
            ]}

        monkeypatch.setattr(mads_lib.posts, "graph_request", fake_graph_request)

        resolve_calls = []

        def fake_page_token(page_id, method, path, **kwargs):
            resolve_calls.append(page_id)
            return {"id": "container_999"}

        monkeypatch.setattr(mads_lib.posts, "graph_request_with_page_token", fake_page_token)

        result = mads_lib.posts.create_ig_container("ig_1", image_url="https://example.com/a.jpg")
        assert result == {"id": "container_999"}
        assert resolve_calls == ["page_1"]

    def test_page_id_resolution_failure_raises_clear_error(self, monkeypatch):
        monkeypatch.setattr(mads_lib.posts, "get_access_token", lambda: "user-token")

        def fake_graph_request(method, path, **kwargs):
            return {"data": [{"id": "page_2", "name": "Other"}]}

        monkeypatch.setattr(mads_lib.posts, "graph_request", fake_graph_request)

        with pytest.raises(ValueError, match="Could not resolve a Page"):
            mads_lib.posts.create_ig_container("ig_1", image_url="https://example.com/a.jpg")


# ─────────────────────────────────────────────────────────────────────────
# CLI: `post create-ig` — 2-step flow, dry-run, mutually-exclusive flags
# ─────────────────────────────────────────────────────────────────────────


class TestPostCreateIgCli:
    def test_two_step_success_surfaces_creation_id(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append(path)
            if path.endswith("/media"):
                return {"id": "container_abc"}
            if path.endswith("/media_publish"):
                return {"id": "published_xyz"}
            raise AssertionError(f"unexpected path {path}")

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fake)

        result = runner.invoke(cli, [
            "post", "create-ig",
            "--ig-account-id", "ig_1", "--page-id", "page_1",
            "--caption", "hello", "--image-url", "https://example.com/a.jpg",
            "--yes", "--json",
        ])
        assert result.exit_code == 0, result.output
        assert len(calls) == 2
        assert "container_abc" in result.output

    def test_partial_failure_surfaces_orphaned_creation_id(self, monkeypatch):
        def fake(page_id, method, path, **kwargs):
            if path.endswith("/media"):
                return {"id": "container_orphan"}
            if path.endswith("/media_publish"):
                raise SystemExit(EXIT_CODES["API"])
            raise AssertionError(f"unexpected path {path}")

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fake)

        result = runner.invoke(cli, [
            "post", "create-ig",
            "--ig-account-id", "ig_1", "--page-id", "page_1",
            "--caption", "hello", "--image-url", "https://example.com/a.jpg",
            "--yes",
        ])
        assert result.exit_code == EXIT_CODES["API"]
        assert "container_orphan" in result.output
        assert "orphaned" in result.output

    def test_requires_exactly_one_of_image_video_url(self):
        result = runner.invoke(cli, [
            "post", "create-ig",
            "--ig-account-id", "ig_1", "--page-id", "page_1", "--caption", "hi",
            "--yes",
        ])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

        result2 = runner.invoke(cli, [
            "post", "create-ig",
            "--ig-account-id", "ig_1", "--page-id", "page_1", "--caption", "hi",
            "--image-url", "https://example.com/a.jpg",
            "--video-url", "https://example.com/a.mp4",
            "--yes",
        ])
        assert result2.exit_code == EXIT_CODES["VALIDATION"]

    def test_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fail_if_called)

        result = runner.invoke(cli, [
            "post", "create-ig",
            "--ig-account-id", "ig_1", "--page-id", "page_1",
            "--caption", "hi", "--image-url", "https://example.com/a.jpg",
            "--dry-run",
        ])
        assert result.exit_code == 0, result.output


class TestPostCreateCli:
    def test_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fail_if_called)

        result = runner.invoke(cli, [
            "post", "create", "--page-id", "page_1", "--message", "hi", "--dry-run",
        ])
        assert result.exit_code == 0, result.output

    def test_requires_message_or_link(self):
        result = runner.invoke(cli, ["post", "create", "--page-id", "page_1", "--yes"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_message_and_caption_file_mutually_exclusive(self, tmp_path):
        caption_file = tmp_path / "caption.txt"
        caption_file.write_text("from file")
        result = runner.invoke(cli, [
            "post", "create", "--page-id", "page_1",
            "--message", "hi", "--caption-file", str(caption_file), "--yes",
        ])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_success_via_cli(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append(kwargs.get("json_body"))
            return {"id": "postid_cli_1"}

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fake)

        result = runner.invoke(cli, [
            "post", "create", "--page-id", "page_1", "--message", "hi", "--yes", "--json",
        ])
        assert result.exit_code == 0, result.output
        # Not a bare json.loads(result.output): _auto_log()'s best-effort changelog write
        # prints its own "Database not found" notice to stderr first in this fake
        # DB-less test scope (mirrors mads_lib.db.get_db(); see TestAutoLogSurvivesMissingDB
        # in test_mads.py) — CliRunner mixes stdout+stderr into result.output, so the JSON
        # payload isn't the only thing in it. Extract just the JSON object instead.
        payload = json.loads(result.output[result.output.index("{"):])
        assert payload["id"] == "postid_cli_1"
        assert calls == [{"message": "hi"}]


class TestPostListCli:
    def test_requires_exactly_one_of_page_id_ig_account_id(self):
        result = runner.invoke(cli, ["post", "list"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

        result2 = runner.invoke(cli, ["post", "list", "--page-id", "p1", "--ig-account-id", "ig1"])
        assert result2.exit_code == EXIT_CODES["VALIDATION"]

    def test_page_id_lists_via_feed_edge(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append(path)
            return {"data": [{"id": "post_1", "message": "hi"}]}

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fake)

        result = runner.invoke(cli, ["post", "list", "--page-id", "page_1", "--json"])
        assert result.exit_code == 0, result.output
        assert calls == ["page_1/feed"]


class TestPostDeleteCli:
    def test_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fail_if_called)

        result = runner.invoke(cli, [
            "post", "delete", "post_1", "--page-id", "page_1", "--dry-run",
        ])
        assert result.exit_code == 0, result.output

    def test_success(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append((page_id, method, path))
            return {"success": True}

        monkeypatch.setattr("mads_lib.posts.graph_request_with_page_token", fake)

        result = runner.invoke(cli, [
            "post", "delete", "post_1", "--page-id", "page_1", "--yes",
        ])
        assert result.exit_code == 0, result.output
        assert calls == [("page_1", "DELETE", "post_1")]


# ─────────────────────────────────────────────────────────────────────────
# comments.py — library functions
# ─────────────────────────────────────────────────────────────────────────


class TestCommentsLibrary:
    def test_list_comments_without_page_id_uses_general_token_path(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("params")))
            return {"data": []}

        monkeypatch.setattr(mads_lib.comments, "graph_request", fake_graph_request)

        mads_lib.comments.list_comments("post_1", limit=10)
        assert calls == [("GET", "post_1/comments", {"fields": mads_lib.comments.DEFAULT_COMMENT_FIELDS, "limit": 10})]

    def test_list_comments_with_page_id_uses_page_token_helper(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append((page_id, method, path))
            return {"data": []}

        monkeypatch.setattr(mads_lib.comments, "graph_request_with_page_token", fake)

        mads_lib.comments.list_comments("post_1", page_id="page_1")
        assert calls == [("page_1", "GET", "post_1/comments")]

    def test_reply_comment_requires_message(self):
        with pytest.raises(ValueError, match="message is required"):
            mads_lib.comments.reply_comment(post_id="post_1", message="")

    def test_reply_comment_requires_exactly_one_of_post_comment(self):
        with pytest.raises(ValueError, match="pass exactly one of"):
            mads_lib.comments.reply_comment(message="hi")
        with pytest.raises(ValueError, match="pass exactly one of"):
            mads_lib.comments.reply_comment(post_id="p1", comment_id="c1", message="hi")

    def test_reply_comment_top_level_posts_to_post_id_comments(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("json_body")))
            return {"id": "cmt_1"}

        monkeypatch.setattr(mads_lib.comments, "graph_request", fake_graph_request)

        result = mads_lib.comments.reply_comment(post_id="post_1", message="nice!")
        assert result == {"id": "cmt_1"}
        assert calls == [("POST", "post_1/comments", {"message": "nice!"})]

    def test_reply_comment_threaded_posts_to_comment_id_comments(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append((method, path))
            return {"id": "cmt_2"}

        monkeypatch.setattr(mads_lib.comments, "graph_request", fake_graph_request)

        mads_lib.comments.reply_comment(comment_id="cmt_1", message="thanks!")
        assert calls == [("POST", "cmt_1/comments")]

    def test_hide_comment_sends_is_hidden_true(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("json_body")))
            return {"success": True}

        monkeypatch.setattr(mads_lib.comments, "graph_request", fake_graph_request)

        mads_lib.comments.hide_comment("cmt_1")
        assert calls == [("POST", "cmt_1", {"is_hidden": True})]

    def test_hide_comment_unhide_sends_is_hidden_false(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append(kwargs.get("json_body"))
            return {"success": True}

        monkeypatch.setattr(mads_lib.comments, "graph_request", fake_graph_request)

        mads_lib.comments.hide_comment("cmt_1", hide=False)
        assert calls == [{"is_hidden": False}]

    def test_delete_comment(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append((method, path))
            return {"success": True}

        monkeypatch.setattr(mads_lib.comments, "graph_request", fake_graph_request)

        mads_lib.comments.delete_comment("cmt_1")
        assert calls == [("DELETE", "cmt_1")]


# ─────────────────────────────────────────────────────────────────────────
# CLI: comment group
# ─────────────────────────────────────────────────────────────────────────


class TestCommentCli:
    def test_list_requires_exactly_one_of_post_id_media_id(self):
        result = runner.invoke(cli, ["comment", "list"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

        result2 = runner.invoke(cli, ["comment", "list", "--post-id", "p1", "--media-id", "m1"])
        assert result2.exit_code == EXIT_CODES["VALIDATION"]

    def test_reply_requires_exactly_one_of_post_id_comment_id(self):
        result = runner.invoke(cli, ["comment", "reply", "--message", "hi", "--yes"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

        result2 = runner.invoke(cli, [
            "comment", "reply", "--post-id", "p1", "--comment-id", "c1", "--message", "hi", "--yes",
        ])
        assert result2.exit_code == EXIT_CODES["VALIDATION"]

    def test_reply_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.comments.graph_request", fail_if_called)

        result = runner.invoke(cli, [
            "comment", "reply", "--post-id", "p1", "--message", "hi", "--dry-run",
        ])
        assert result.exit_code == 0, result.output

    def test_reply_success(self, monkeypatch):
        def fake_graph_request(method, path, **kwargs):
            return {"id": "cmt_cli_1"}

        monkeypatch.setattr("mads_lib.comments.graph_request", fake_graph_request)

        result = runner.invoke(cli, [
            "comment", "reply", "--post-id", "p1", "--message", "hi", "--yes", "--json",
        ])
        assert result.exit_code == 0, result.output
        # See TestPostCreateCli.test_success_via_cli for why this isn't a bare
        # json.loads(result.output).
        assert json.loads(result.output[result.output.index("{"):])["id"] == "cmt_cli_1"

    def test_hide_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.comments.graph_request", fail_if_called)

        result = runner.invoke(cli, ["comment", "hide", "cmt_1", "--dry-run"])
        assert result.exit_code == 0, result.output

    def test_hide_and_unhide_success(self, monkeypatch):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append(kwargs.get("json_body"))
            return {"success": True}

        monkeypatch.setattr("mads_lib.comments.graph_request", fake_graph_request)

        result = runner.invoke(cli, ["comment", "hide", "cmt_1", "--yes"])
        assert result.exit_code == 0, result.output
        result2 = runner.invoke(cli, ["comment", "hide", "cmt_1", "--unhide", "--yes"])
        assert result2.exit_code == 0, result2.output
        assert calls == [{"is_hidden": True}, {"is_hidden": False}]

    def test_delete_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.comments.graph_request", fail_if_called)

        result = runner.invoke(cli, ["comment", "delete", "cmt_1", "--dry-run"])
        assert result.exit_code == 0, result.output

    def test_delete_success(self, monkeypatch):
        def fake_graph_request(method, path, **kwargs):
            return {"success": True}

        monkeypatch.setattr("mads_lib.comments.graph_request", fake_graph_request)

        result = runner.invoke(cli, ["comment", "delete", "cmt_1", "--yes"])
        assert result.exit_code == 0, result.output


# ─────────────────────────────────────────────────────────────────────────
# CLI: `page update`
# ─────────────────────────────────────────────────────────────────────────


class TestPageUpdateCli:
    def test_requires_at_least_one_field(self):
        result = runner.invoke(cli, ["page", "update", "page_1", "--yes"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_invalid_hours_json_rejected(self):
        result = runner.invoke(cli, ["page", "update", "page_1", "--hours-json", "{not valid", "--yes"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_dry_run_makes_zero_api_calls(self, monkeypatch):
        def fail_if_called(*a, **k):
            raise AssertionError("must not be called in --dry-run")

        monkeypatch.setattr("mads_lib.pages.graph_request_with_page_token", fail_if_called)

        result = runner.invoke(cli, ["page", "update", "page_1", "--about", "New about text", "--dry-run"])
        assert result.exit_code == 0, result.output

    def test_success_sends_only_provided_fields(self, monkeypatch):
        calls = []

        def fake(page_id, method, path, **kwargs):
            calls.append((page_id, method, path, kwargs.get("json_body")))
            return {"success": True}

        monkeypatch.setattr("mads_lib.pages.graph_request_with_page_token", fake)

        result = runner.invoke(cli, [
            "page", "update", "page_1", "--about", "New about", "--phone", "+971500000000", "--yes", "--json",
        ])
        assert result.exit_code == 0, result.output
        assert calls == [("page_1", "POST", "page_1", {"about": "New about", "phone": "+971500000000"})]
