"""
Docstring for scripts.paratranz.download
This script downloads translation files from Paratranz for a specific project,
unzips them, processes JSON files to replace newline characters and compute MD5 hashes for keys,
and combines EBOOT and EVS translations into separate JSON files.

NOTE THAT '\n' IN PARATRANZ IS '\\n', SO WE NEED TO CONVERT IT BACK TO REAL NEWLINE WHEN PROCESSING.
"""

import requests
import zipfile
import os
import argparse
import json
import time
from typing import Optional
from .preprocess import normalize_data, hash_keys_in_data

project_id = 10882  # 替换为你的项目ID


def get_default_headers(auth_key: Optional[str] = None) -> dict:
    """Get default headers for Paratranz API requests"""
    headers = {}
    if auth_key:
        headers["Authorization"] = auth_key
    return headers


def trigger_rebuild(auth_key: str) -> bool:
    """Trigger artifact rebuild on Paratranz API"""
    url = f"https://paratranz.cn/api/projects/{project_id}/artifacts"
    headers = get_default_headers(auth_key)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    
    try:
        response = requests.post(url, headers=headers)
        if response.status_code == 200:
            print("Artifact rebuild triggered successfully.")
            return True
        else:
            print(f"Failed to trigger rebuild. Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error triggering rebuild: {e}")
        return False


def wait_for_rebuild(auth_key: str, max_wait_time: int = 600) -> bool:
    """
    Poll the build job status until rebuild is complete.
    Returns True when the job list is empty (rebuild complete).
    max_wait_time: Maximum time to wait in seconds (default 10 minutes)
    """
    url = f"https://paratranz.cn/api/projects/{project_id}/jobs?type=buildProject"
    headers = get_default_headers(auth_key)
    
    start_time = time.time()
    poll_interval = 2  # Check every 2 seconds
    
    print("Waiting for artifact rebuild to complete...")
    
    while time.time() - start_time < max_wait_time:
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                jobs = response.json()
                
                if isinstance(jobs, list) and len(jobs) == 0:
                    print("Artifact rebuild completed successfully.")
                    return True
                
                if isinstance(jobs, list) and len(jobs) > 0:
                    job = jobs[0]
                    status = job.get("status", -1)
                    finished_at = job.get("finishedAt")
                    print(f"  Build in progress... (status: {status}, finishedAt: {finished_at})")
            else:
                print(f"Warning: Failed to check rebuild status. Status code: {response.status_code}")
        except Exception as e:
            print(f"Error checking rebuild status: {e}")
        
        time.sleep(poll_interval)
    
    print(f"Warning: Rebuild did not complete within {max_wait_time} seconds.")
    return False


def download_function(
    auth_key: str,
    dest_folder: str = "temp/downloads",
    project_id_override: Optional[int] = None,
):
    if project_id_override is not None:
        global project_id
        project_id = project_id_override

    if not auth_key:
        raise ValueError("AUTH_KEY 不能为空")

    # Trigger rebuild before downloading
    print("Triggering artifact rebuild...")
    if not trigger_rebuild(auth_key):
        print("Warning: Failed to trigger rebuild, continuing with download anyway...")
    
    # Wait for rebuild to complete
    if not wait_for_rebuild(auth_key):
        print("Warning: Rebuild did not complete, continuing with download anyway...")

    url = f"https://paratranz.cn/api/projects/{project_id}/artifacts/download"

    zip_path = download_file(url, dest_folder, auth_key)
    print("Files have been downloaded.")

    if zip_path:
        unzip_file(zip_path, dest_folder)
        print(f"Files extracted to {dest_folder}")


def merge_function(dest_folder: str = "temp/downloads"):
    process_utf8_json(dest_folder)
    combine_eboot(dest_folder)
    combine_evs(dest_folder)


def process_utf8_json(dest_folder):
    free_path = os.path.join(dest_folder, "utf8", "free")
    game_path = os.path.join(dest_folder, "utf8", "game")
    cev_path = os.path.join(dest_folder, "utf8", "EVS", "cev")
    if os.path.exists(free_path):
        print("Processing JSON files in utf8/free and utf8/game folders...")
        for file in os.listdir(free_path):
            if file.endswith(".json"):
                file_path = os.path.join(free_path, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data = normalize_data(data)
                data = hash_keys_in_data(data)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"  Processed: {file_path}")

        if os.path.exists(game_path):
            for file in os.listdir(game_path):
                if file.endswith(".json"):
                    file_path = os.path.join(game_path, file)
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data = normalize_data(data)
                    data = hash_keys_in_data(data)
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    print(f"  Processed: {file_path}")

    if os.path.exists(cev_path):
        print("Processing split CEV JSON files in utf8/EVS/cev...")
        for root, _, files in os.walk(cev_path):
            for file in files:
                if not file.endswith(".json"):
                    continue
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data = normalize_data(data)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"  Processed: {file_path}")


def combine_eboot(dest_folder):
    # Combine all the EBOOT Translations.
    eboot_path = os.path.join(dest_folder, "raw", "EBOOT")
    data = []
    for root, dir, files in os.walk(eboot_path):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path, "r", encoding="utf-8") as f:
                data.extend(json.load(f))
    data = normalize_data(data)
    eboot_trans = os.path.join(dest_folder, "eboot_trans.json")
    with open(eboot_trans, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def combine_evs(dest_folder):
    # Combine the EVS translations
    evs_path = os.path.join(dest_folder, "raw", "EVS")
    data = []
    for root, dir, files in os.walk(evs_path):
        dir[:] = [name for name in dir if name != "cev"]
        for file in files:
            if not file.endswith(".json"):
                continue
            if file.startswith("cev"):
                continue
            file_path = os.path.join(root, file)
            with open(file_path, "r", encoding="utf-8") as f:
                data.extend(json.load(f))
    data = normalize_data(data)
    data = hash_keys_in_data(data)
    evs_trans = os.path.join(dest_folder, "evs_trans.json")
    with open(evs_trans, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def download_file(url, dest_folder, auth: str):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    headers = get_default_headers(auth)
    response = requests.get(url, headers=headers, stream=True)
    if response.status_code == 302:
        download_url = response.headers["Location"]
        response = requests.get(download_url, headers=headers, stream=True)

    if response.status_code == 200:
        zip_path = os.path.join(dest_folder, "downloaded.zip")
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=128):
                f.write(chunk)
        return zip_path
    else:
        print(f"Error: {response.status_code}")
        return None


def unzip_file(zip_path, dest_folder):
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(dest_folder)


if __name__ == "__main__":
    # Add Arguments
    parser = argparse.ArgumentParser(
        description="Download and process Paratranz files."
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["download", "merge"],
        required=True,
        help="Action to perform: 'download' to download and unzip files, 'merge' to process and combine translations.",
    )
    parser.add_argument(
        "--dest_folder",
        type=str,
        default="temp/downloads",
        help="Destination folder for downloaded files.",
    )
    args = parser.parse_args()
    dest_folder = args.dest_folder

    if args.action == "download":
        auth_key = os.getenv("AUTH_KEY")
        if not auth_key:
            raise ValueError("AUTH_KEY环境变量未设置")
        download_function(auth_key, dest_folder)
    elif args.action == "merge":
        merge_function(dest_folder)
