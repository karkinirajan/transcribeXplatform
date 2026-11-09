# Deliberate bugs, one at a time: each (name, file, old text, new text) must make the suite fail.
# Run from the repo root:  python3 tests/mutation/mutate.py tests/mutation/mutants.py -- uv run pytest -x -q
# (the driver checks the suite is green first; do not edit the tree while it runs; each pattern must occur exactly once)
#
# Not listed, because they cannot change behaviour:
#  - allowing "/" in the character filter of safe_upload_name: only the last path segment reaches it, so there is no slash to filter
#    (the filter is kept as a second line of defence);
#  - calling copy_limited directly instead of through run_in_threadpool in the upload endpoint (the same bytes are written; the
#    thread only keeps the event loop free, which a unit test cannot observe).

UP = "backend/uploads.py"
JB = "backend/jobs.py"
MN = "backend/main.py"

M = [
 # --- the stored file name
 ("name: backslash paths are not split", UP, "last = PurePosixPath(PureWindowsPath(raw).name).name", "last = PurePosixPath(raw).name"),
 ("name: the whole path is kept", UP, "last = PurePosixPath(PureWindowsPath(raw).name).name", "last = raw"),
 ("name: the stem is unbounded", UP, '.sub("_", stem)[:MAX_FILENAME_STEM].strip(" ._-")', '.sub("_", stem).strip(" ._-")'),
 ("name: an empty stem stays empty", UP, "return f\"{stem or 'upload'}{suffix}\"", 'return f"{stem}{suffix}"'),
 ("name: the old extension is kept", UP, "stem = last[: -len(PurePosixPath(last).suffix)] if PurePosixPath(last).suffix else last", "stem = last"),
 # --- the size
 ("size: exactly the limit is refused", UP, "        if total > max_bytes:", "        if total >= max_bytes:"),
 ("size: no limit", UP, "        if total > max_bytes:\n            raise UploadTooLargeError(max_bytes)\n", ""),
 ("size: the default is lifted", UP, "DEFAULT_MAX_UPLOAD_MB = 2048", "DEFAULT_MAX_UPLOAD_MB = 204800"),
 ("size: a zero limit is allowed", UP, "return max(1, megabytes) * 1024 * 1024", "return megabytes * 1024 * 1024"),
 ("size: a bad setting is an error", UP, "    except ValueError:\n        megabytes = DEFAULT_MAX_UPLOAD_MB", "    except ValueError:\n        raise"),
 ("size: the unit is kilobytes", UP, "return max(1, megabytes) * 1024 * 1024", "return max(1, megabytes) * 1024"),
 # --- the form fields
 ("fields: any language", UP, '_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})?$")', '_LANGUAGE = re.compile(r".*")'),
 ("fields: any model", UP, '_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")', '_MODEL = re.compile(r".*")'),
 ("fields: models unbounded", UP, "len(text) > MAX_MODEL or ", ""),
 ("fields: titles unbounded", UP, "return text[:MAX_TITLE] or None", "return text or None"),
 ("fields: control characters kept in titles", UP, 'if ch.isprintable() or ch in "\\t\\n"', "if True"),
 ("fields: a blank language is refused", UP, "    if not text:\n        return None\n    if not _LANGUAGE.match(text):", "    if not _LANGUAGE.match(text):"),
 # --- the job registry
 ("jobs: expiry is inclusive", JB, "now - job.finished_at > JOB_TTL_SECONDS", "now - job.finished_at >= JOB_TTL_SECONDS"),
 ("jobs: nothing expires", JB, "now - job.finished_at > JOB_TTL_SECONDS", "False"),
 ("jobs: the cap makes no room", JB, "over = len(_store) - MAX_JOBS + 1", "over = 0"),
 ("jobs: the newest finished jobs are evicted first", JB, "key=lambda j: j.finished_at or 0)", "key=lambda j: -(j.finished_at or 0))"),
 ("jobs: the cap is off by one", JB, "        if len(_store) >= MAX_JOBS:\n            raise TooManyJobsError", "        if len(_store) > MAX_JOBS:\n            raise TooManyJobsError"),
 ("jobs: no cap at all", JB, "        if len(_store) >= MAX_JOBS:\n            raise TooManyJobsError(\"Too many jobs are running. Try again when one has finished.\")\n", ""),
 ("jobs: files are not removed", JB, "        shutil.rmtree(job._temp_dir, ignore_errors=True)", "        pass"),
 ("jobs: finishing does not record the time", JB, "    job.finished_at = time.time()\n", ""),
 ("jobs: finishing does not remove the recording", JB, "    job.status = status\n    _forget(job)", "    job.status = status"),
 ("jobs: a removed job stays", JB, "        job = _store.pop(job_id, None)", "        job = _store.get(job_id)"),
 ("jobs: removing says yes for anything", JB, "    if job is None:\n        return False\n", ""),
 # --- the API
 ("api: any method is allowed by CORS", MN, 'allow_methods=["GET", "POST", "DELETE"],', 'allow_methods=["*"],'),
 ("api: any origin may write", MN, "        if origin is not None and origin not in ALLOWED_ORIGINS:", "        if False:"),
 ("api: deletes are not origin-checked", MN, 'if request.method in ("POST", "PUT", "PATCH", "DELETE"):', 'if request.method in ("POST", "PUT", "PATCH"):'),
 ("api: a missing origin is refused", MN, "        if origin is not None and origin not in ALLOWED_ORIGINS:", "        if origin not in ALLOWED_ORIGINS:"),
 ("api: any host is trusted", MN, 'allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]', 'allowed_hosts=["*"]'),
 ("api: the server binds every interface", MN, 'host=os.getenv("TRANSCRIBE_HOST", "127.0.0.1")', 'host=os.getenv("TRANSCRIBE_HOST", "0.0.0.0")'),
 ("api: the declared size is not checked", MN, '    if declared and declared.isdigit() and int(declared) > limit + 1024 * 1024:\n        raise HTTPException(status_code=413, detail=f"The file is larger than the {limit // (1024 * 1024)} MB limit.")\n', ""),
 ("api: the size limit is not applied", MN, "copy_limited(file.file, f, limit)", "copy_limited(file.file, f, 10**13)"),
 ("api: the browser's file name is used", MN, "stored_name = safe_upload_name(file.filename, suffix)", 'stored_name = file.filename or f"upload{suffix}"'),
 ("api: a too-large upload leaves its files", MN, "    except UploadTooLargeError as exc:\n        shutil.rmtree(temp_dir, ignore_errors=True)\n", "    except UploadTooLargeError as exc:\n"),
 ("api: a refused job leaves its files", MN, "    except TooManyJobsError as exc:\n        shutil.rmtree(temp_dir, ignore_errors=True)\n", "    except TooManyJobsError as exc:\n"),
 ("api: the language is not checked", MN, "        language_code = clean_language(language)\n", "        language_code = language or None\n"),
 ("api: the model is not checked", MN, "        model_name = clean_model(model)\n", "        model_name = model\n"),
 ("api: the title is not cleaned", MN, "    clean_name = clean_title(title)\n", "    clean_name = title or None\n"),
 ("api: any backend", MN, "    if backend not in VALID_BACKENDS:", "    if False:"),
 ("api: any file type", MN, "    if suffix not in ALLOWED_EXTENSIONS:", "    if False:"),
 ("api: a failed job is not finished", MN, "        finish_job(job, JobStatus.FAILED, str(exc))\n", "        job.status = JobStatus.FAILED\n"),
 ("api: a finished job keeps the recording", MN, "        finish_job(job, JobStatus.COMPLETED)\n", "        job.status = JobStatus.COMPLETED\n"),
 ("api: delete forgets nothing", MN, "    if not remove_job(job_id):", "    if get_job(job_id) is None:"),
]
