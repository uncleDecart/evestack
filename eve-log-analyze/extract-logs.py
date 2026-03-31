#!/usr/bin/env python3
# Copyright (c) 2026 Zededa, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# extract-logs.py — extract and merge compressed EVE device logs from a
# persist/newlog directory (or a full EVE info-collect archive).
#
# Enhancements over the original:
#   --summary     Print only key annotated events to stdout (fast triage).
#   --errors-only Write only error/warning/panic lines (+context) to output file.
#   --context N   Lines of context around each --errors-only match (default: 5).
#   --max-lines N Truncate output at N lines to keep it usable for LLMs (default: unlimited).
#   --last-boot   Only include log entries from the most recent kernel boot.

import argparse
import atexit
import datetime
import gc
import gzip
import heapq
import json
import os
import re
import sys
import tempfile
from datetime import timedelta, timezone
from functools import partial
from multiprocessing import Pool, cpu_count

from dateutil import parser as isoparser

from fast_iso_parser import fast_parse_iso

# Try to import faster JSON parsers
try:
    import orjson

    JSON_PARSER = "orjson"

    def json_loads(s):
        if isinstance(s, str):
            s = s.encode("utf-8")
        return orjson.loads(s)
except ImportError:
    try:
        import ujson

        JSON_PARSER = "ujson"
        json_loads = ujson.loads
    except ImportError:
        JSON_PARSER = "json"
        json_loads = json.loads


# Patterns for --errors-only mode
_ERROR_PATTERNS = re.compile(
    r"\b(error|err\b|warning|warn\b|panic|fatal|crash|failed|failure|oom|"
    r"out of memory|killed|segfault|exception|abort|died|unreachable|timeout|"
    r"watchdog|vault.*lock|tpm.*fail|attest.*fail|cannot|can't|unable)\b",
    re.IGNORECASE,
)


def is_text(data):
    if isinstance(data, bytes):
        try:
            data.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False
    if isinstance(data, str):
        if "\0" in data:
            return False
        return True
    return False


def annotate_line(line):
    timestamep = line.split(" ")[0] + " " + line.split(" ")[1]
    if "Vault is not yet unlocked" in line:
        print(f"\t{timestamep} [VAULT]: NOT YET UNLOCKED")
    elif "Vault is still locked" in line:
        print(f"\t{timestamep} [VAULT]: STILL LOCKED")
    elif "vault is setup and unlocked successfully" in line:
        print(f"\t{timestamep} [VAULT]: UNLOCKED")
    elif "possibly mismatching PCR indexes" in line:
        print(
            f"\t{timestamep} [TPM]: POSSIBLY MISMATCHING PCR INDEXES {line.split(' ')[-1].strip()}"
        )
    elif "successfully sealed the fresh disk key into TPM" in line:
        print(f"\t{timestamep} [TPM]: SEALED DISK KEY")
    elif "successfully unsealed the disk key from TPM" in line:
        print(f"\t{timestamep} [TPM]: UNSEALED DISK KEY")
    elif "[ATTEST] Attestation successful, processing keys given by Controller" in line:
        print(
            f"\t{timestamep} [ATTEST]: ATTESTATION SUCCESSFUL. Got some keys from Controller"
        )
    elif "[ATTEST] no storage keys received from controller" in line:
        print(
            f"\t{timestamep} [ATTEST]: ATTESTATION SUCCESSFUL. No STORAGE KEY from Controller"
        )
    elif (
        "Application Data Store unlocked using key type Key is new and protected using PCRs"
        in line
    ):
        print(
            f"\t{timestamep} [TPM]: UNLOCKED APP DATA STORE. Key is new and protected using PCRs"
        )
    elif "Sealed key in TPM, unlocking Application Data Store" in line:
        print(
            f"\t{timestamep} [TPM]: SEALED KEY IN TPM. Unlocking Application Data Store"
        )
    elif "Successfully unlocked /persist/vault" in line:
        print(f"\t{timestamep} [VAULT]: [EXT4] UNLOCKED /persist/vault")
    elif "Attached SCSI removable disk" in line:
        print(f"\t{timestamep} [KERNEL]: USB attached")
    elif "Hypervisor args: [/usr/lib/xen/bin/qemu-system-x86_64" in line:
        print(f"\t{timestamep} [QEMU]: Application started")
    elif "[ATTEST] Error All attempts to connect to " in line:
        print(
            f"\t{timestamep} [ATTEST]: ATTESTATION FAILED. All attempts to connect to Controller failed"
        )
    elif "[ATTEST] Error Can not connect to " in line:
        print(
            f"\t{timestamep} [ATTEST]: ATTESTATION FAILED. Failed to connect to Controller"
        )
    elif "Current partition RebootReason" in line:
        reason = line.split(":")
        print(f"\t{timestamep} [REBOOT]: RebootReason: {reason[5]} ({reason[6]})")


def prettify_old_format(content_json, time_adjustment=0):
    parsed_line = ""
    time_str = content_json["time"]
    dt = fast_parse_iso(time_str)

    if time_adjustment != 0:
        dt = dt + timedelta(hours=time_adjustment)

    if "msg" in content_json:
        if "file" in content_json:
            parsed_line = f"{content_json['file']}: {content_json['msg']}"
        else:
            parsed_line = f"{content_json['msg']}"
    if "diff" in content_json:
        parsed_line += f"{content_json['diff']}"
    return (dt, parsed_line)


def convert_timestamp(timestamp, time_adjustment=0):
    seconds = timestamp["seconds"]
    nanos = timestamp["nanos"]
    datetime_obj = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
    if nanos > 0:
        datetime_obj = datetime_obj.replace(microsecond=nanos // 1000)
    if time_adjustment != 0:
        datetime_obj = datetime_obj + timedelta(hours=time_adjustment)
    return datetime_obj


def process_single_log_file(args):
    """Process a single log file and return parsed entries."""
    log_file, time_adjustment, file_index, total_files = args
    parsed_logs = []
    last_good_dt = None

    try:
        with gzip.open(log_file, "rt") as file:
            lines = file.readlines()

            for i, line in enumerate(lines):
                if not is_text(line):
                    continue
                parsed_line = line
                dt = None
                try:
                    json_line = json_loads(line)
                    content = json_line.get("content", "")
                    try:
                        content_json = json_loads(content)
                        if isinstance(content_json, dict):
                            dt, parsed_line = prettify_old_format(
                                content_json, time_adjustment
                            )
                        else:
                            timestamp = json_line["timestamp"]
                            dt = convert_timestamp(timestamp, time_adjustment)
                            if json_line.get("source") == "kernel":
                                parsed_line = f"[KERNEL]: {content}"
                            elif "filename" in json_line:
                                parsed_line = f"{json_line['filename']}: {content}"
                            else:
                                source = json_line.get("source", "unknown")
                                parsed_line = f"[{source}]: {content}"
                    except json.JSONDecodeError:
                        if 'diff":' in content:
                            content = (
                                content.replace("\\n", "\n")
                                .replace("\\t", "\t")
                                .replace('\\"', '"')
                                .replace("\\\\", "\\")
                            )
                            parsed_line = f"{content}"
                        else:
                            timestamp = json_line["timestamp"]
                            dt = convert_timestamp(timestamp, time_adjustment)
                            if json_line.get("source") == "kernel":
                                parsed_line = f"[KERNEL]: {content}"
                            elif "filename" in json_line:
                                parsed_line = f"{json_line['filename']}: {content}"
                            else:
                                source = json_line.get("source", "unknown")
                                parsed_line = f"[{source}]: {content}"

                except json.JSONDecodeError:
                    print(
                        f"\nUnknown log line format (JSONDecodeError) in {log_file} at line {i}"
                    )
                    print(f"Raw log line: {line}")
                    sys.exit(1)
                except KeyError as e:
                    if "timestamp" in str(e):
                        print(
                            f"\nUnknown log line format (KeyError: {e}) in {log_file} at line {i}"
                        )
                        print(f"Raw log line: {line}")
                        sys.exit(1)
                    continue

                if dt is None:
                    if last_good_dt is None:
                        continue
                    else:
                        last_good_dt = last_good_dt + timedelta(microseconds=1)
                        dt = last_good_dt
                else:
                    last_good_dt = dt

                if not parsed_line.endswith("\n"):
                    parsed_line += "\n"
                parsed_logs.append((dt, parsed_line))

        return (file_index, os.path.basename(log_file), parsed_logs)

    except Exception as e:
        print(f"\nError processing {log_file}: {str(e)}")
        return (file_index, os.path.basename(log_file), [])


def _consuming_iter(lst):
    lst.reverse()
    while lst:
        yield lst.pop()


def _get_available_memory_mb():
    """Return available system memory in MB. Works on Linux and macOS."""
    # Linux: /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass

    # macOS: vm_stat
    try:
        import subprocess
        out = subprocess.check_output(["vm_stat"], text=True)
        page_size = 4096
        free_pages = 0
        for line in out.splitlines():
            if "Pages free" in line or "Pages inactive" in line:
                free_pages += int(line.split(":")[1].strip().rstrip("."))
        if free_pages:
            return (free_pages * page_size) // (1024 * 1024)
    except Exception:
        pass

    return None


def _format_log_entry(dt, line):
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{dt.microsecond:06d} {line}"


def _formatting_iter(chunk_iter):
    for dt, line in chunk_iter:
        yield _format_log_entry(dt, line)


_temp_files_to_cleanup = []


def _cleanup_temp_files():
    for path in _temp_files_to_cleanup:
        try:
            os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_temp_files)


def _temp_file_iter(path):
    with open(path, "r") as f:
        current = None
        for line in f:
            if (
                len(line) >= 27
                and line[4] == "-"
                and line[7] == "-"
                and line[10] == " "
                and line[13] == ":"
                and line[16] == ":"
                and line[19] == "."
            ):
                if current is not None:
                    yield current
                current = line
            else:
                if current is not None:
                    current += line
                else:
                    current = line
        if current is not None:
            yield current


def _spill_chunks_to_disk(chunks, temp_dir):
    merged = heapq.merge(*[_consuming_iter(c) for c in chunks], key=lambda x: x[0])
    fd, path = tempfile.mkstemp(prefix="logsort_", suffix=".tmp", dir=temp_dir)
    _temp_files_to_cleanup.append(path)
    count = 0
    with os.fdopen(fd, "w") as f:
        for dt, line in merged:
            f.write(_format_log_entry(dt, line))
            count += 1
            if count % 500000 == 0:
                print(f"\r  spilled {count:,} entries to disk...", end="", flush=True)
    print(f"\r  spilled {count:,} entries to {os.path.basename(path)}")
    return path


def _is_boot_line(formatted):
    return "[KERNEL]: Linux version" in formatted


def parse_logs(
    log_dir,
    output_file,
    time_adjustment=0,
    split=False,
    annotate=False,
    num_workers=None,
    memory_budget_mb=None,
    errors_only=False,
    context_lines=5,
    max_lines=None,
    last_boot=False,
    summary=False,
):
    log_files = []
    for root, dirs, files in os.walk(log_dir):
        for file in files:
            if file.startswith("dev.log.") and file.endswith(".gz"):
                log_files.append(os.path.join(root, file))
    log_files.sort()

    if not log_files:
        print("No log files found!")
        return

    total_files = len(log_files)
    print(f"Found {total_files} log files to process")

    if num_workers is None:
        num_workers = cpu_count()
    print(f"Using {num_workers} worker processes")
    print(f"JSON parser: {JSON_PARSER}")

    process_args = [
        (log_file, time_adjustment, idx, total_files)
        for idx, log_file in enumerate(log_files, start=1)
    ]

    avail_mb = _get_available_memory_mb()
    if memory_budget_mb is not None:
        avail_str = f"{avail_mb:,}" if avail_mb is not None else "?"
        print(
            f"Available memory: {avail_str} MB — user-specified budget: {memory_budget_mb:,} MB"
        )
    elif avail_mb is not None:
        memory_budget_mb = avail_mb // 2
        print(
            f"Available memory: {avail_mb:,} MB — budget for parsed data: {memory_budget_mb:,} MB"
        )
    else:
        memory_budget_mb = 4096
        print(
            f"Could not detect available memory — using {memory_budget_mb:,} MB budget"
        )

    temp_dir = os.path.dirname(os.path.abspath(output_file)) or "."
    bytes_per_entry = 230
    calibrated = False
    parsed_chunks = []
    temp_file_paths = []
    in_memory_entries = 0
    total_entries = 0

    with Pool(processes=num_workers) as pool:
        results = pool.imap_unordered(
            process_single_log_file, process_args, chunksize=1
        )
        completed = 0
        for file_index, filename, parsed_logs in results:
            completed += 1
            print(
                f"\rProcessed {completed}/{total_files} files ({filename}){'':30s}",
                end="",
                flush=True,
            )
            if parsed_logs:
                parsed_logs.sort(key=lambda x: x[0])
                total_entries += len(parsed_logs)
                in_memory_entries += len(parsed_logs)
                parsed_chunks.append(parsed_logs)

                if not calibrated and parsed_logs:
                    sample = parsed_logs[:100]
                    avg = sum(
                        sys.getsizeof(dt) + sys.getsizeof(line) + sys.getsizeof(entry)
                        for entry in sample
                        for dt, line in [entry]
                    ) / len(sample)
                    bytes_per_entry = int(avg)
                    calibrated = True

                estimated_mb = (in_memory_entries * bytes_per_entry) // (1024 * 1024)
                if estimated_mb > memory_budget_mb and len(parsed_chunks) > 0:
                    print(
                        f"\n  Memory estimate {estimated_mb:,} MB > budget {memory_budget_mb:,} MB — spilling to disk..."
                    )
                    path = _spill_chunks_to_disk(parsed_chunks, temp_dir)
                    temp_file_paths.append(path)
                    parsed_chunks = []
                    in_memory_entries = 0
                    gc.collect()

    print(f"\nTotal log entries (pre-dedup): {total_entries:,}")

    merge_sources = []
    for path in temp_file_paths:
        merge_sources.append(_temp_file_iter(path))
    if parsed_chunks:
        if len(parsed_chunks) > 1:
            mem_iter = heapq.merge(
                *[_consuming_iter(c) for c in parsed_chunks], key=lambda x: x[0]
            )
        else:
            mem_iter = _consuming_iter(parsed_chunks[0])
        merge_sources.append(_formatting_iter(mem_iter))
    del parsed_chunks

    if len(merge_sources) > 1:
        n_disk = len(temp_file_paths)
        n_mem = len(merge_sources) - n_disk
        print(f"Streaming merge of {n_disk} disk + {n_mem} memory source(s)...")
        merged_iter = heapq.merge(*merge_sources)
    elif len(merge_sources) == 1:
        merged_iter = merge_sources[0]
    else:
        merged_iter = iter([])

    print(f"Formatting and writing logs to {output_file}...")

    annotation_count = 0
    duplicates_removed = 0
    written = 0
    prev_line = None
    split_files = []
    split_fp = None
    WRITE_BATCH = 10000
    write_batch = []

    # For last_boot: buffer all lines, then trim to after the last boot marker
    if last_boot:
        print("Buffering for --last-boot trimming...")

    # For errors_only: sliding window context
    context_buffer = []  # ring buffer of recent lines
    pending_context = 0  # lines of post-match context still to emit
    errors_written = []

    with open(output_file, "w", buffering=16 * 1024 * 1024) as out:
        all_lines = list(merged_iter) if last_boot else None

        if last_boot and all_lines:
            # Find the last boot marker
            last_boot_idx = None
            for i in range(len(all_lines) - 1, -1, -1):
                if _is_boot_line(all_lines[i]):
                    last_boot_idx = i
                    break
            if last_boot_idx is not None:
                print(f"--last-boot: trimming to {len(all_lines) - last_boot_idx:,} entries after index {last_boot_idx:,}")
                all_lines = all_lines[last_boot_idx:]
            merged_iter = iter(all_lines)

        for formatted in merged_iter:
            if formatted == prev_line:
                duplicates_removed += 1
                continue
            prev_line = formatted

            # Summary mode: only print to stdout, write nothing
            if summary:
                if _is_boot_line(formatted):
                    timestamp = formatted.split("[KERNEL]")[0].strip()
                    print(f"\n=== Boot at {timestamp} ===")
                    annotation_count += 1
                if (
                    "Vault" in formatted
                    or "[TPM]" in formatted
                    or "[ATTEST]" in formatted
                    or "RebootReason" in formatted
                ):
                    annotate_line(formatted)
                    annotation_count += 1
                continue

            written += 1

            if annotate:
                if _is_boot_line(formatted):
                    timestamp = formatted.split("[KERNEL]")[0].strip()
                    print(f"\n=== Boot at {timestamp} ===")
                    annotation_count += 1
                if (
                    "Vault" in formatted
                    or "[TPM]" in formatted
                    or "[ATTEST]" in formatted
                    or "RebootReason" in formatted
                ):
                    annotate_line(formatted)
                    annotation_count += 1

            if split:
                if "[KERNEL]:" in formatted and "Linux version" in formatted:
                    if split_fp is not None:
                        split_fp.close()
                    chunk_file = f"{output_file}-{len(split_files)}"
                    split_files.append(chunk_file)
                    split_fp = open(chunk_file, "w")
                if split_fp is not None:
                    split_fp.write(formatted)

            if errors_only:
                context_buffer.append(formatted)
                if len(context_buffer) > context_lines + 1:
                    context_buffer.pop(0)

                if _ERROR_PATTERNS.search(formatted):
                    # Emit buffered pre-context + current line
                    for ctx_line in context_buffer[:-1]:
                        errors_written.append(ctx_line)
                    errors_written.append(formatted)
                    pending_context = context_lines
                    context_buffer.clear()
                elif pending_context > 0:
                    errors_written.append(formatted)
                    pending_context -= 1
            else:
                write_batch.append(formatted)
                if len(write_batch) >= WRITE_BATCH:
                    out.writelines(write_batch)
                    write_batch.clear()

            if max_lines and written >= max_lines:
                print(f"\n--max-lines {max_lines} reached, truncating output")
                break

            if written % 100000 == 0:
                print(
                    f"\rWritten {written:,}/{total_entries:,} entries",
                    end="",
                    flush=True,
                )

        if errors_only:
            out.writelines(errors_written)
            written = len(errors_written)
        elif write_batch:
            out.writelines(write_batch)
            write_batch.clear()

    if split_fp is not None:
        split_fp.close()

    _cleanup_temp_files()

    if summary:
        print(f"\nSummary complete: {annotation_count:,} key events found")
        return

    print(f"\rWritten {written:,} entries (done)")
    if temp_file_paths:
        print(f"Used {len(temp_file_paths)} disk spill file(s) for external sort")
    if duplicates_removed:
        print(f"Removed {duplicates_removed:,} duplicate log entries")
    if annotate:
        print(f"Annotation complete: {annotation_count:,} annotations found")
    if split:
        print(f"Wrote {len(split_files)} boot chunk files")
    if errors_only:
        print(f"Errors-only mode: {written:,} lines (including context)")
    print(f"Done! Output written to {output_file}")


def find_newlog_dir(persist_dir):
    if not os.path.isdir(persist_dir):
        return None
    for variant in ["newlog", "persist-newlog"]:
        newlog_dir = os.path.join(persist_dir, variant)
        if os.path.isdir(newlog_dir):
            return newlog_dir
    return None


def extract_tar_gz_parallel(tar_file, extract_to, num_workers=None):
    import shutil
    import subprocess

    if shutil.which("pigz") and shutil.which("tar"):
        print(f"Extracting {tar_file} using parallel decompression (pigz)...")
        try:
            cmd = ["tar", "-I", "pigz", "-xf", tar_file, "-C", extract_to]
            subprocess.run(cmd, check=True)
            print("Extraction complete!")
            return True
        except subprocess.CalledProcessError as e:
            print(f"pigz extraction failed: {e}, falling back to standard extraction")

    print(f"Extracting {tar_file} using standard extraction...")
    import tarfile

    with tarfile.open(tar_file, "r:gz") as tar:
        members = tar.getmembers()
        total = len(members)
        for i, member in enumerate(members, 1):
            tar.extract(member, path=extract_to)
            if i % 100 == 0 or i == total:
                print(f"\rExtracted {i}/{total} files", end="", flush=True)
    print("\nExtraction complete!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract and merge EVE device logs from a persist/newlog directory "
        "or a full EVE info-collect archive."
    )
    parser.add_argument(
        "persist_directory",
        help="Path to the persist directory, archive root, or tar.gz file",
    )
    parser.add_argument(
        "-dt", "--time_adjustment", type=int, default=0, help="Time adjustment in hours"
    )
    parser.add_argument(
        "-o", "--output_file", default="parsed-logs.txt", help="Output file name"
    )
    parser.add_argument(
        "-s",
        "--split",
        action="store_true",
        help="Split logs into per-boot chunk files",
    )
    parser.add_argument(
        "-a",
        "--annotate",
        action="store_true",
        help="Annotate key events to stdout (vault, TPM, attest, reboot)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only key annotated events to stdout; do not write output file",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Write only error/warning/panic lines (+ context) to output file",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=5,
        metavar="N",
        help="Lines of context around --errors-only matches (default: 5)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=None,
        metavar="N",
        help="Truncate output at N lines",
    )
    parser.add_argument(
        "--last-boot",
        action="store_true",
        help="Only include log entries from the most recent kernel boot",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel workers (default: all CPU cores)",
    )
    parser.add_argument(
        "-m",
        "--memory-budget",
        type=int,
        default=None,
        metavar="MB",
        help="Memory budget in MB (default: 50%% of available RAM)",
    )
    parser.add_argument(
        "--extract", metavar="TAR_FILE", help="Extract tar.gz file before processing"
    )

    args = parser.parse_args()
    persist_dir = args.persist_directory

    if args.extract:
        extract_to = os.path.dirname(args.extract) or "."
        extract_tar_gz_parallel(args.extract, extract_to, args.jobs)
    elif persist_dir.endswith(".tar.gz") or persist_dir.endswith(".tgz"):
        extract_to = os.path.dirname(persist_dir) or "."
        extract_tar_gz_parallel(persist_dir, extract_to, args.jobs)
        base_name = (
            os.path.basename(persist_dir).replace(".tar.gz", "").replace(".tgz", "")
        )
        potential_dir = os.path.join(extract_to, base_name)
        if os.path.isdir(potential_dir):
            persist_dir = potential_dir
        else:
            persist_dir = extract_to

    newlog_dir = find_newlog_dir(persist_dir)
    if not newlog_dir:
        print(
            "No newlog directory found. Expected 'newlog' or 'persist-newlog' inside the given path."
        )
        print(f"Looked in: {persist_dir}")
        sys.exit(1)

    parse_logs(
        newlog_dir,
        args.output_file,
        args.time_adjustment,
        args.split,
        args.annotate,
        args.jobs,
        args.memory_budget,
        errors_only=args.errors_only,
        context_lines=args.context,
        max_lines=args.max_lines,
        last_boot=args.last_boot,
        summary=args.summary,
    )
