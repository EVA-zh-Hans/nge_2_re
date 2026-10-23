"""
Docstring for scripts.paratranz.preprocess

This script preprocesses translation files for Paratranz by normalizing newline characters
and computing MD5 hashes for keys in JSON files.
"""

import argparse
import json
import hashlib


def normalize_newlines(text: str) -> str:
    """Convert escaped newline characters to actual newlines."""
    return text.replace("\\n", "\n")


def normalize_data(data):
    """Recursively normalize newlines in all string values in the data."""
    if isinstance(data, dict):
        return {k: normalize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_data(item) for item in data]
    elif isinstance(data, str):
        return normalize_newlines(data)
    else:
        return data


def hash_keys_in_data(data):
    """Replace keys in JSON data with MD5 hashes of their original text."""
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "original" in item:
                original_text = item["original"]
                hash_object = hashlib.md5(original_text.encode())
                item["key"] = hash_object.hexdigest()
    return data


def process_file(input_path: str, output_path: str, hash_flag: bool):
    """Process a single JSON file to normalize newlines and optionally hash keys."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = normalize_data(data)
    if hash_flag:
        data = hash_keys_in_data(data)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess Paratranz JSON files by normalizing newlines and hashing keys."
    )
    parser.add_argument("input_file", type=str, help="Path to the input JSON file.")
    parser.add_argument("output_file", type=str, help="Path to the output JSON file.")
    parser.add_argument(
        "--hash_keys",
        action="store_true",
        help="If set, replace keys with MD5 hashes of their original text.",
    )
    args = parser.parse_args()

    process_file(args.input_file, args.output_file, args.hash_keys)
