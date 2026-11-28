#!/usr/bin/env python3
"""Inspect exact proposed Git blobs for publication-only metadata exposure.

No network, policy execution, or publication occurs. Receipts contain paths,
rule identifiers, counts, and hashes; rejected field values are never emitted.
JSON is parsed; YAML structural keys are checked without an extra dependency.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, unquote, urlsplit


FORBIDDEN_KEYS = {"_private_reference_data", "url_private_api", "url_private_html"}
ALLOWED_FILE_IDS = {71653870, 71653786, 71653801, 71653831, 52080797, 53161835, 44225498}
ARTICLE_PATHS = {
    "data/decision_engine/source_metadata/12672038_metadata.json": True,
    "data/decision_engine/source_metadata/22715158_metadata.json": False,
    "data/decision_engine/source_metadata/28187990_metadata.json": False,
}
YAML_METADATA_PATH = "data/decision_engine/source_metadata/data-files.yml"
URL_PATTERN = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
YAML_TOKEN = re.compile(
    r'''"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|\#.*$|[A-Za-z_][A-Za-z_0-9.-]*|[:{}\[\],]|\S'''
)
MAX_GZIP_TEXT_BYTES = 256 * 1024 * 1024


def git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError("git_inspection_failed")
    return result.stdout


def resolve_tree(revision: str) -> str:
    return git("rev-parse", "--verify", "--end-of-options", revision + "^{tree}").decode().strip()


def tree_entries(tree: str) -> dict[str, tuple[str, str]]:
    result = {}
    for entry in git("ls-tree", "-r", "-z", "--full-tree", tree).split(b"\0"):
        if not entry:
            continue
        head, raw_path = entry.split(b"\t", 1)
        _mode, kind, object_id = head.decode().split()
        result[raw_path.decode("utf-8", errors="surrogateescape")] = (kind, object_id)
    return result


def dictionary_key_paths(value, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + "." + str(key)
            if key in FORBIDDEN_KEYS:
                yield child_path
            yield from dictionary_key_paths(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from dictionary_key_paths(child, f"{path}[{index}]")


def string_values(value, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from string_values(child, path + "." + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from string_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def yaml_forbidden_key_lines(text: str):
    """Recognize block/flow and quoted mapping keys, ignoring comments/scalars.

    Block scalar bodies are skipped so prose about a key is not mistaken for a
    mapping. Quoted scalar values are single tokens; only tokens followed by a
    colon are considered keys. This is a focused key detector, not a YAML loader.
    """
    scalar_indent = None
    for line_number, line in enumerate(text.splitlines(), 1):
        indent = len(line) - len(line.lstrip())
        if scalar_indent is not None:
            if not line.strip() or indent > scalar_indent:
                continue
            scalar_indent = None
        tokens = list(YAML_TOKEN.finditer(line))
        for index, token in enumerate(tokens):
            word = token.group()
            if word.startswith("#"):
                break
            if index + 1 < len(tokens) and tokens[index + 1].group() == ":":
                if word.startswith('"'):
                    try:
                        key = json.loads(word)
                    except (ValueError, TypeError):
                        key = word[1:-1]
                elif word.startswith("'"):
                    key = word[1:-1].replace("''", "'")
                else:
                    key = word
                if key in FORBIDDEN_KEYS:
                    yield line_number, key
        if re.search(r":\s*[>|][0-9+-]*\s*(?:#.*)?$", line):
            scalar_indent = indent


def unsafe_url_rules(text: str) -> set[str]:
    rules = set()
    # JSON escaping and percent-encoding must not hide the URL's structure.
    normalized = text.replace("\\/", "/").replace("&amp;", "&")
    for match in URL_PATTERN.finditer(normalized):
        try:
            url = urlsplit(unquote(match.group().rstrip(".,);]}")))
            host = (url.hostname or "").lower()
            segments = [x.lower() for x in url.path.split("/") if x]
            query_keys = {k.lower() for k, _ in parse_qsl(url.query)}
        except ValueError:
            continue
        figshare = host == "figshare.com" or host.endswith(".figshare.com")
        if figshare and any(s in {"account", "accounts"} for s in segments):
            rules.add("figshare_account_url")
        if (any(s in {"private", "private_link", "private_links"} for s in segments)
                or query_keys & {"private_link", "private_link_id", "private_token"}
                or (figshare and segments and segments[0] == "s")
                or (figshare and query_keys & {"token", "access_token", "auth_token"})):
            rules.add("private_download_link")
    return rules


def audit(base: str, tree: str) -> dict:
    base_tree, target_tree = resolve_tree(base), resolve_tree(tree)
    entries = tree_entries(target_tree)
    changed = [p.decode("utf-8", errors="surrogateescape") for p in
               git("diff", "--name-only", "-z", "--no-renames", base_tree, target_tree).split(b"\0") if p]
    # Always inspect the named metadata if present, even when unchanged.
    paths = sorted(set(changed) | ({*ARTICLE_PATHS, YAML_METADATA_PATH} & set(entries)))
    findings, inventory = [], []
    counts = {"changed_paths": len(changed), "deleted_paths": 0, "blobs": 0,
              "text_blobs": 0, "gzip_text_blobs": 0, "json_documents": 0,
              "yaml_documents": 0, "figshare_articles": 0, "article_file_records": 0}

    def finding(path, rule, key_path=None, line=None):
        item = {"path": path, "rule": rule}
        if key_path is not None:
            item["key_path"] = key_path
        if line is not None:
            item["line"] = line
        if item not in findings:
            findings.append(item)

    for path in paths:
        if path not in entries:
            counts["deleted_paths"] += 1
            continue
        kind, object_id = entries[path]
        if kind != "blob":
            finding(path, "unsupported_non_blob_entry")
            continue
        raw = git("cat-file", "blob", object_id)
        counts["blobs"] += 1
        record = {"path": path, "git_blob": object_id, "bytes": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest(), "changed": path in changed}
        inventory.append(record)
        is_gzip = raw.startswith(b"\x1f\x8b")
        payload = raw
        if is_gzip:
            try:
                import io
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                    payload = stream.read(MAX_GZIP_TEXT_BYTES + 1)
                if len(payload) > MAX_GZIP_TEXT_BYTES:
                    finding(path, "gzip_text_size_limit")
                    continue
            except (OSError, EOFError):
                finding(path, "invalid_gzip")
                continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            record["text"] = False
            continue
        if "\x00" in text:
            record["text"] = False
            continue
        record["text"] = True
        counts["gzip_text_blobs" if is_gzip else "text_blobs"] += 1
        for rule in sorted(unsafe_url_rules(text)):
            finding(path, rule)
        suffix = Path(path.removesuffix(".gz")).suffix.lower()
        documents = []
        if suffix in {".json", ".jsonl", ".ndjson"}:
            try:
                documents = ([json.loads(line) for line in text.splitlines() if line.strip()]
                             if suffix != ".json" else [json.loads(text)])
            except (ValueError, RecursionError):
                finding(path, "invalid_json")
                continue
            counts["json_documents"] += len(documents)
            for index, document in enumerate(documents):
                prefix = "$" if suffix == ".json" else f"$line[{index + 1}]"
                for key_path in dictionary_key_paths(document, prefix):
                    finding(path, "forbidden_dictionary_key", key_path=key_path)
                # Also inspect decoded values, including JSON Unicode escapes.
                for key_path, value in string_values(document, prefix):
                    for rule in sorted(unsafe_url_rules(value)):
                        finding(path, rule, key_path=key_path)
        elif suffix in {".yaml", ".yml"}:
            counts["yaml_documents"] += 1
            for line, key in yaml_forbidden_key_lines(text):
                finding(path, "forbidden_dictionary_key", key_path=key, line=line)
        if path not in ARTICLE_PATHS:
            continue
        counts["figshare_articles"] += 1
        article = documents[0] if len(documents) == 1 else None
        if not isinstance(article, dict) or not isinstance(article.get("files"), list):
            finding(path, "invalid_article_files_schema", key_path="$.files")
            continue
        if ARTICLE_PATHS[path] and article["files"]:
            finding(path, "licence_only_article_has_files", key_path="$.files")
        for key_path, value in string_values(article):
            for match in URL_PATTERN.finditer(value.replace("\\/", "/")):
                try:
                    url = urlsplit(unquote(match.group()))
                    host = (url.hostname or "").lower()
                except ValueError:
                    continue
                if host == "figshare.com" or host.endswith(".figshare.com"):
                    ids = re.findall(r"/(?:files|file)/(\d+)(?:/|$)", url.path)
                    if any(int(identifier) not in ALLOWED_FILE_IDS for identifier in ids):
                        finding(path, "unapproved_public_file_id_in_url", key_path=key_path)
        for index, entry in enumerate(article["files"]):
            counts["article_file_records"] += 1
            prefix = f"$.files[{index}]"
            if not isinstance(entry, dict):
                finding(path, "invalid_article_file_record", key_path=prefix)
                continue
            identifier = entry.get("id")
            if type(identifier) is not int or identifier not in ALLOWED_FILE_IDS:
                finding(path, "unapproved_public_file_id", key_path=prefix + ".id")
            name = entry.get("name")
            if not isinstance(name, str):
                finding(path, "invalid_article_file_name", key_path=prefix + ".name")
            elif (name.startswith(("/", "\\")) or "\\" in name
                  or re.match(r"^[A-Za-z]:", name)):
                finding(path, "absolute_or_windows_article_file_name", key_path=prefix + ".name")
    return {"schema": "erkidu-publication-metadata-audit/v1",
            "status": "passed" if not findings else "failed",
            "base_tree": base_tree, "target_tree": target_tree,
            "counts": counts, "findings": findings, "blob_inventory": inventory,
            "new_policy_runs": 0, "new_reference_jobs": 0, "publication_attempts": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("receipt already exists; choose a new output path")
    try:
        receipt = audit(args.base, args.tree)
    except (RuntimeError, OSError, ValueError):
        # Do not surface Git stderr or parser values from rejected metadata.
        receipt = {"schema": "erkidu-publication-metadata-audit/v1", "status": "failed",
                   "findings": [{"rule": "inspection_error"}], "publication_attempts": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    print(json.dumps({"status": receipt["status"], "findings": len(receipt["findings"]),
                      "counts": receipt.get("counts", {}), "receipt": str(args.out)}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
