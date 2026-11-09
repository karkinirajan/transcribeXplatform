from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from uploads import (  # noqa: E402
    DEFAULT_MAX_UPLOAD_MB,
    MAX_FILENAME_STEM,
    MAX_MODEL,
    MAX_TITLE,
    UploadTooLargeError,
    clean_language,
    clean_model,
    clean_title,
    copy_limited,
    max_upload_bytes,
    safe_upload_name,
)


class TestSafeUploadName:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("meeting.mp3", "meeting.mp3"),
            ("My Interview (final).mp3", "My Interview _final.mp3"),
            ("../../home/me/Music/song.mp3", "song.mp3"),
            ("..\\..\\Windows\\song.mp3", "song.mp3"),
            ("/etc/cron.d/job.mp3", "job.mp3"),
            ("C:\\Users\\me\\talk.mp3", "talk.mp3"),
            ("a/b\\c/d.mp3", "d.mp3"),
            (".hidden.mp3", "hidden.mp3"),
            ("...mp3", "mp3.mp3"),
            ("-rf.mp3", "rf.mp3"),
            ("-.mp3", "upload.mp3"),
            ("", "upload.mp3"),
            (None, "upload.mp3"),
            ("..", "upload.mp3"),
            ("日本語.mp3", "upload.mp3"),
            ("a\x00b.mp3", "a_b.mp3"),
            ("semi;colon$(rm).mp3", "semi_colon_rm.mp3"),
        ],
    )
    def test_only_a_plain_name_survives(self, filename, expected):
        assert safe_upload_name(filename, ".mp3") == expected

    def test_the_extension_is_the_validated_one_not_whatever_the_name_ended_in(self):
        assert safe_upload_name("talk.exe", ".mp3") == "talk.mp3"
        assert safe_upload_name("talk.mp3.sh", ".wav") == "talk.mp3.wav"

    def test_the_stem_is_bounded(self):
        name = safe_upload_name("x" * 500 + ".mp3", ".mp3")
        assert len(name) == MAX_FILENAME_STEM + len(".mp3")

    @pytest.mark.parametrize("hostile", ["../../x.mp3", "..\\..\\x.mp3", "/abs/x.mp3", "a/../../b.mp3", "%2e%2e/x.mp3", "....//x.mp3"])
    def test_joined_onto_a_directory_it_never_escapes(self, tmp_path, hostile):
        target = (tmp_path / safe_upload_name(hostile, ".mp3")).resolve()
        assert target.parent == tmp_path.resolve()

    def test_never_empty_never_a_separator_never_a_leading_dot_or_dash(self):
        for hostile in ["/", "\\", ".", "..", "-", "--", " ", "\x00", "./", "../", "a/", ".mp3"]:
            name = safe_upload_name(hostile, ".mp3")
            assert name and "/" not in name and "\\" not in name and not name.startswith((".", "-"))


class TestCopyLimited:
    def test_copies_everything_within_the_limit(self):
        src, dst = io.BytesIO(b"x" * 1000), io.BytesIO()
        assert copy_limited(src, dst, 1000, chunk_size=64) == 1000
        assert dst.getvalue() == b"x" * 1000

    def test_exactly_at_the_limit_is_fine_one_byte_over_is_not(self):
        assert copy_limited(io.BytesIO(b"x" * 10), io.BytesIO(), 10) == 10
        with pytest.raises(UploadTooLargeError):
            copy_limited(io.BytesIO(b"x" * 11), io.BytesIO(), 10)

    def test_stops_reading_at_the_limit_instead_of_reading_it_all(self):
        class Endless:
            reads = 0

            def read(self, n):
                Endless.reads += 1
                return b"x" * n

        with pytest.raises(UploadTooLargeError):
            copy_limited(Endless(), io.BytesIO(), 5 * 64, chunk_size=64)
        assert Endless.reads <= 7

    def test_an_empty_source_copies_nothing(self):
        assert copy_limited(io.BytesIO(), io.BytesIO(), 10) == 0

    def test_the_error_names_the_limit_in_megabytes(self):
        with pytest.raises(UploadTooLargeError, match="2 MB"):
            copy_limited(io.BytesIO(b"x" * (3 * 1024 * 1024)), io.BytesIO(), 2 * 1024 * 1024)


class TestMaxUploadBytes:
    def test_default(self):
        assert max_upload_bytes({}) == DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
        assert max_upload_bytes({}) == 2 * 1024**3  # a literal: the default is part of the contract

    def test_override_in_megabytes(self):
        assert max_upload_bytes({"TRANSCRIBE_MAX_UPLOAD_MB": "50"}) == 50 * 1024 * 1024

    @pytest.mark.parametrize("bad", ["", "  ", "abc", "1.5", "-5", "0"])
    def test_a_bad_value_falls_back_or_is_clamped_to_at_least_one_megabyte(self, bad):
        value = max_upload_bytes({"TRANSCRIBE_MAX_UPLOAD_MB": bad})
        assert value >= 1024 * 1024
        if bad not in ("-5", "0"):
            assert value == DEFAULT_MAX_UPLOAD_MB * 1024 * 1024


class TestFormFields:
    @pytest.mark.parametrize("value", ["en", "EN", "en-US", "en_US", "pt-BR", "yue", "zh-Hans"])
    def test_language_codes_accepted(self, value):
        assert clean_language(value) == value

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_no_language_means_detect(self, value):
        assert clean_language(value) is None

    @pytest.mark.parametrize("value", ["english", "e", "en-", "en US", "en;rm", "../x", "en\nUS", "en-US-extra-bits", "1234"])
    def test_language_codes_refused(self, value):
        with pytest.raises(ValueError):
            clean_language(value)

    @pytest.mark.parametrize("value", ["", None, "base", "gpt-4o-mini-transcribe", "nova-3", "openai/whisper-large-v3", "small.en", "a:b"])
    def test_model_names_accepted(self, value):
        assert clean_model(value) == (value or "")

    @pytest.mark.parametrize("value", ["-rf", "a b", "a;b", "$(x)", "../x", "x" * (MAX_MODEL + 1), "a\nb", ".hidden", "a`b"])
    def test_model_names_refused(self, value):
        with pytest.raises(ValueError):
            clean_model(value)

    def test_model_exactly_the_maximum_length_is_fine(self):
        assert clean_model("m" * MAX_MODEL) == "m" * MAX_MODEL

    def test_title_is_tidied_and_bounded(self):
        assert clean_title("  Weekly   sync \n notes ") == "Weekly sync notes"
        assert clean_title("x" * 1000) == "x" * MAX_TITLE
        assert clean_title("a\x00b\x07c") == "abc"

    @pytest.mark.parametrize("value", [None, "", "   ", "\x00\x01"])
    def test_an_empty_title_is_none(self, value):
        assert clean_title(value) is None
